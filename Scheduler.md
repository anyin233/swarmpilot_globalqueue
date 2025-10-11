# Scheduler

Scheduler负责将任务分发到不同的Task Instance上。Scheduler作为中央调度器，维护所有Task Instance的状态信息，并根据选定的调度策略和队列预测结果，将每个任务路由到最优的Task Instance执行。

每个Scheduler内部应当维护的信息包括：
- 每个Task Instance当前的队列信息（预测信息）：包括预计等待时间的期望值和误差范围
- 每个Task Instance的连接信息：包括网络地址、端口、健康状态等
- 每个模型所对应的所有Task Instance：支持多模型调度，每种模型可以有多个Task Instance实例

所有的Task Instance使用一个UUID进行唯一标识，确保在分布式环境中的唯一性。

具体来说，数据结构分别为
```python
ti_queue_info: Dict{UUID: (float, float)}  # UUID -> (期望等待时间, 误差)
ti_conn_info : Dict{UUID: List[str, Any]}  # UUID -> [连接地址, 其他配置信息]
model_to_ti  : Dict{str: List[UUID]}       # 模型名称 -> Task Instance UUID列表
```

## 接口设计


### `/scheduler/set`

选择并设置调度器使用的调度策略。Scheduler支持多种调度策略，包括最短队列（shortest_queue）、轮询（round_robin）、加权（weighted）、概率性（probabilistic）等。更改策略会立即生效，影响后续所有任务的调度决策。

参数设计
```python
{
    "name": str  # 调度策略名称，如 "shortest_queue", "round_robin", "weighted", "probabilistic"
}
```

返回格式

```python
{
    "status": str,   # "success" 表示策略设置成功，"error" 表示设置失败
    "message": str,  # 若status为success，该项为"OK"；若为error，返回具体错误原因（如策略名称不存在）
}
```

### `/scheduler/predict_mode`

选择预测器的工作模式。预测器负责估算任务在各个Task Instance上的执行时间，支持两种工作模式：

- **标准预测模式（default）**：使用训练好的机器学习模型进行实时预测，精度较高但有一定计算开销
- **速查表模式（lookup_table）**：使用预先计算好的结果查询表，速度快但灵活性较低

参数设计
```python
{
    "mode": str,  # 预测模式：
                  # "default" - 使用标准预测模型进行实时预测
                  # "lookup_table" - 使用预先计算的速查表快速查询
}
```

返回格式

```python
{
    "status": str,   # "success" 表示模式切换成功，"error" 表示切换失败
    "message": str,  # 若status为success，该项为"OK"；若为error，返回具体错误原因（如不支持的模式类型）
}
```

### `/ti/register`

将一个Task Instance注册到当前的Scheduler。注册成功后，Scheduler会将该Task Instance纳入调度池，后续提交的任务可能被分配到该实例。注册时会验证Task Instance的可达性和健康状态。

参数设计
```python
{
    "host": str,  # Task Instance的主机地址，可以是IP地址（如"192.168.1.100"）或域名（如"worker1.example.com"）
    "port": int   # Task Instance的HTTP服务端口号，默认通常为8100
}
```

返回格式
```python
{
    "status": str,    # "success" 表示注册成功，"error" 表示注册失败
    "message": str,   # 成功时返回描述信息（如"TaskInstance registered successfully"）
                      # 失败时返回错误原因（如"Connection refused"或"Health check failed"）
    "ti_uuid": UUID   # 为该Task Instance分配的全局唯一标识符，后续操作需要使用此UUID
                      # 注册失败时该字段为空字符串
}
```

### `/ti/remove`

将一个Task Instance从当前的Scheduler中移除。移除后，该Task Instance不再接收新任务，但已分配给它的进行中任务会继续执行直到完成。移除操作是安全的，不会中断正在执行的任务。

参数设计
```python
{
    "ti_uuid": UUID  # 要移除的Task Instance的唯一标识符，该UUID在注册时由Scheduler分配
                     # 必须是已注册的有效UUID，否则操作失败
}
```

返回格式
```python
{
    "status": str,    # "success" 表示移除成功，"error" 表示移除失败
    "message": str,   # 成功时返回描述信息（如"TaskInstance removed successfully"）
                      # 失败时返回错误原因（如"TaskInstance not found"或"Invalid UUID format"）
    "ti_uuid": UUID   # 被移除的Task Instance的UUID，用于确认操作对象
                      # 若UUID不存在，该字段返回传入的UUID以供调试
}
```

### `/queue/submit`

将一个需要调度的任务提交到当前Scheduler。Scheduler会根据当前的调度策略、各Task Instance的队列状态和预测的执行时间，选择最优的Task Instance执行该任务。提交成功后返回任务ID，可用于后续查询任务状态。

参数设计
```python
{
    "model_name": str,            # 目标模型名称（如"gpt-3.5-turbo"、"llama-7b"等）
                                  # Scheduler会在注册了该模型的Task Instance中进行选择

    "task_input": Dict[str, Any], # 提交给Task Instance的任务输入信息
                                  # 具体格式取决于目标模型的要求
                                  # 常见字段如：{"prompt": "...", "max_tokens": 100, "temperature": 0.7}

    "metadata": Dict[str, Any]    # 提交给Predictor的元数据，用于预测模型执行时间分布
                                  # 可包含：{"hardware": "A100", "input_tokens": 100, "output_tokens": 50}
                                  # 更详细的metadata有助于提高预测精度
}
```

返回格式
```python
{
    "status": str,              # "success" 表示任务成功调度，"error" 表示调度失败
    "task_id": str,             # 提交的任务的全局唯一标识符，用于后续查询任务状态和结果
                                # 格式通常为"task-{uuid}"

    "scheduled_ti": UUID,       # 任务被调度到的Task Instance的UUID
                                # 可用于追踪任务分配情况和负载均衡分析
                                # 调度失败时该字段可能为空
}
```

**注意事项**：
- 如果没有注册任何Task Instance，提交会失败
- 如果指定的model_name没有对应的Task Instance，提交会失败
- 建议在metadata中提供尽可能详细的信息以提高调度质量

### `/queue/info`

获取当前Scheduler上所有Queue的信息。返回每个Task Instance的队列状态，包括预计等待时间的期望值和误差范围。该接口常用于监控系统负载、分析调度效果和做出负载均衡决策。

参数设计
```python
{
    "model_name": str  # (可选参数) 指定模型名称，仅返回该模型对应的Task Instance队列信息
                       # 若不指定（为null或空），则返回所有模型的所有Task Instance的信息
                       # 用于过滤和聚焦特定模型的负载情况
}
```

返回格式
```python
{
    "status": str,      # "success" 表示查询成功，"error" 表示查询失败
    "queues": List[{    # 队列信息列表，每个元素代表一个Task Instance的队列状态
        "model_name": str,                 # 该Task Instance运行的模型名称
        "ti_uuid": UUID,                   # Task Instance的唯一标识符
        "waiting_time_expect": float,      # 预计等待时间的期望值（单位：毫秒）
                                           # 表示新任务提交到该实例后，预计需要等待多久才能开始执行
        "waiting_time_error": float,       # 预计等待时间的误差（标准差，单位：毫秒）
                                           # 表示预测的不确定性范围，值越小表示预测越准确
    }]
}
```

**使用场景**：
- 监控面板实时显示各队列负载
- 客户端主动选择负载较低的队列提交任务
- 分析系统瓶颈和优化调度策略

### `/task/query`

查询一个特定Task的调度信息和执行状态。可用于追踪任务的完整生命周期，从提交、调度、执行到完成的全过程。支持轮询方式等待任务完成。

参数设计
```python
{
    "task_id": str  # 任务的全局唯一标识符，在任务提交时由Scheduler返回
                    # 格式通常为"task-{uuid}"
                    # 必须是有效的、已提交的任务ID
}
```

返回格式
```python
{
    "task_id": str,               # 任务ID，与查询参数一致

    "task_status": str,           # 任务当前状态，可能的值：
                                  # "queued" - 已提交但尚未调度到Task Instance
                                  # "scheduled" - 已调度到Task Instance，等待或正在执行
                                  # "completed" - 执行完成，结果已返回

    "scheduled_ti": UUID,         # 任务被调度到的Task Instance的UUID
                                  # 可用于定位任务执行位置

    "submit_time": float,         # 任务提交时间戳（Unix timestamp，精确到毫秒）
                                  # 可用于计算任务总耗时

    "result": Any                 # 任务执行结果（仅在task_status为"completed"时有值）
                                  # 具体格式取决于任务类型
                                  # 执行失败时也在此字段返回错误信息
                                  # 未完成时该字段为null
}
```

**使用建议**：
- 使用轮询方式查询时，建议采用指数退避策略，避免频繁请求
- 任务完成后，结果可能在一段时间后被清理，建议及时获取
- 可结合submit_time计算任务的端到端延迟
