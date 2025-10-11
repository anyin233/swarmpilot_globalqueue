# Scheduler

Scheduler负责将任务分发到不同的Task Instance上，每个Scheduler内部应当维护的信息包括
- 每个Task Instance当前的队列信息（预测信息）
- 每个Task Instance的连接信息
- 每个模型所对应的所有Task Instance
所有的Task Instance使用一个UUID进行标识

具体来说，数据结构分别为
```python
ti_queue_info: Dict{UUID: (float, float)}
ti_conn_info : Dict{UUID: List[str, Any]}
model_to_ti  : Dict{str: List[UUID]}
```

## 接口设计

### `/ti/register`

将一个Task Instance注册到当前的Scheduler

参数设计
```python
{
    "host": str,            # Task Instance的主机地址
    "port": int,            # Task Instance的端口
    "model_name": str       # Task Instance运行的模型名称，用于调度时的队列筛选
}
```

返回格式
```python
{
    "status": str,      # "success" 或 "error"
    "message": str,     # 描述信息
    "ti_uuid": UUID     # 注册的Task Instance UUID
}
```

### `/ti/remove`

将一个Task Instance从当前的Scheduler中移除

参数设计
```python
{
    "host": str,        # 要移除的Task Instance的主机地址
    "port": int         # 要移除的Task Instance的端口
}
```

返回格式
```python
{
    "status": str,      # "success" 或 "error"
    "message": str,     # 描述信息
    "host": str,        # 移除的Task Instance主机地址
    "port": int,        # 移除的Task Instance端口
    "ti_uuid": str      # 移除的Task Instance UUID（如果找到）
}
```

### `/queue/submit`

将一个需要调度的任务提交到当前Scheduler

参数设计
```python
{
    "model_name": str,            # 目标模型名称
    "task_input": Dict[str, Any], # 提交给Task Instance的任务信息
    "metadata": Dict[str, Any]    # 提交给Predictor用于预测模型执行时间分布的元数据
}
```

返回格式
```python
{
    "status": str,              # "success" 或 "error"
    "task_id": str,             # 提交的任务ID
    "scheduled_ti": UUID,       # 被调度到的Task Instance UUID
}
```

### `/queue/info`

获取当前Scheduler上所有的Queue的信息

参数设计
```python
{
    "model_name": str           # (可选) 指定模型名称，若不指定则返回所有模型的信息
}
```

返回格式
```python
{
    "status": str,
    "queues": List[{
        "model_name": str,
        "ti_uuid": UUID,
        "waiting_time_expect": float,  # 预计等待时间的期望
        "waiting_time_error": float,   # 预计等待时间的误差
    }]
}
```

### `/task/query`

查询一个特定的Task的调度信息

参数设计
```python
{
    "task_id": str              # 任务唯一标识符
}
```

返回格式
```python
{
    "task_id": str,
    "task_status": str,         # "queued", "scheduled", "completed"
    "scheduled_ti": UUID,       # 被调度到的Task Instance UUID
    "submit_time": float,       # 提交时间戳
    "result": Any               # 任务结果(如果已完成)
}
```
