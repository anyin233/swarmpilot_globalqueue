# Predictor

Predictor负责预测任务的执行时间分布（使用分位数表示），内部维护所有的预测模型，接受外界传入的任务特征信息，返回任务的执行时间分布交由Scheduler用于预测

## 接口设计

### `/train`

训练分位数执行时间预测模型

参数设计
```python
{
    "config": File              # 训练配置文件
}
```

config的格式参考项目中其他的训练配置文件

返回格式
```python
{
    "status": str,
    "model_key": str,           # 该Model Key对应训练出的分位数执行时间预测模型存储的Key
    "metrics": Dict[str, Any],
    "duration_seconds": int
}
```

### `/predict/single/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}`

预测单个任务的执行时间分布

路径参数
```
model_type: str           # 模型类型
model_name: str           # 模型名称
hardware: str             # 硬件配置
software_name: str        # 软件名称
software_version: str     # 软件版本
```

`model_type`, `model_name`, `hardware`, `software_name`, `software_version`参数设置模式参见yaml配置文件

请求体参数
```python
{
    "trace": TracePayload,      # 任务trace信息，格式参考项目中的示例trace文件，该接口只接受一个trace项
    "confidence_level": float,   # 置信度设置,
    "lookup_table": bool, # （可选）是否使用预置的查询表
    "lookup_table_name": str # （可选，当lookup_table == True时必选）若希望使用查询表，查询表的文件名
}
```

说明：
- lookup table: 实验时使用的可以加快实验实现的速查表，内部存放提前预测完成的结果，具体实现为以一个csv文件保存，输入的feature在前，预测的分位数结果和期望误差在后。

返回格式
```python
{
    "summary": {
        "total": int,
        "success": int,
        "failed": int,
        "confidence_level": float,
        "duration_seconds": int
    },
    "results": {
        "status": str,
        "quantile_predictions": List[float],
        "quantiles": List[float],
        "model_info": {
            "type": str,
            "name": str,
            "hardware": str,
            "software_name": str,
            "software_version": str
        },
        "expect": float,
        "error": float # 基于分位数分布的理论，计算其期望和误差（误差使用标准差）
    }
}
```

### `/predict/batch/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}`

批量预测多个任务的执行时间分布

路径参数
```
model_type: str           # 模型类型
model_name: str           # 模型名称
hardware: str             # 硬件配置
software_name: str        # 软件名称
software_version: str     # 软件版本
```

`model_type`, `model_name`, `hardware`, `software_name`, `software_version`参数设置模式参见yaml配置文件

请求体参数
```python
{
    "trace": List[TracePayload],  # 任务trace信息列表，格式参考项目中的示例trace文件，接受一组trace
    "confidence_level": float,     # 置信度设置
    "lookup_table": bool, # （可选）是否使用预置的查询表
    "lookup_table_name": str # （可选，当lookup_table == True时必选）若希望使用查询表，查询表的文件名
}
```

说明：
- lookup table: 实验时使用的可以加快实验实现的速查表，内部存放提前预测完成的结果，具体实现为以一个csv文件保存，输入的feature在前，预测的分位数结果和期望误差在后。

返回格式
```python
{
    "summary": {
        "total": int,
        "success": int,
        "failed": int,
        "confidence_level": float,
        "duration_seconds": int
    },
    "results": List[{
        "status": str,
        "quantile_predictions": List[float],
        "quantiles": List[float],
        "model_info": {
            "type": str,
            "name": str,
            "hardware": str,
            "software_name": str,
            "software_version": str
        },
        "expect": float,
        "error": float # 基于分位数分布的理论，计算其期望和误差（误差使用标准差）
    }],
    "expect": float,
    "error": float # 基于误差累计理论，计算当前所有被预测的任务的总的期望和误差（误差使用标准差）
}
```

### `/predict/table/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}`

接口说明：该接口将会生成速查表，同时返回速查表的路径

请求体参数
```python
{
    "trace_file": upload_file,  # 任务trace信息列表，接受一个有效的trace文件
    "confidence_level": float,     # 置信度设置
}
```

返回格式
```python
{
	"status": str,  # successful, failed
	"path": str,  # path to lookup table
}
```