# Scheduler

The Scheduler is responsible for distributing tasks to different Task Instances. Each Scheduler internally maintains:
- Queue information (prediction info) for each Task Instance
- Connection information for each Task Instance
- All Task Instances corresponding to each model

All Task Instances are identified by a UUID.

Specifically, the data structures are:
```python
ti_queue_info: Dict{UUID: (float, float)}
ti_conn_info : Dict{UUID: List[str, Any]}
model_to_ti  : Dict{str: List[UUID]}
```

## API Design

### `/ti/register`

Register a Task Instance to the current Scheduler

Parameter Design
```python
{
    "host": str,            # Task Instance host address
    "port": int,            # Task Instance port
    "model_name": str       # Model name running on this Task Instance, used for queue filtering during scheduling
}
```

Return Format
```python
{
    "status": str,      # "success" or "error"
    "message": str,     # Description message
    "ti_uuid": UUID     # Registered Task Instance UUID
}
```

### `/ti/remove`

Remove a Task Instance from the current Scheduler

Parameter Design
```python
{
    "host": str,        # Host address of the Task Instance to remove
    "port": int         # Port of the Task Instance to remove
}
```

Return Format
```python
{
    "status": str,      # "success" or "error"
    "message": str,     # Description message
    "host": str,        # Host address of removed Task Instance
    "port": int,        # Port of removed Task Instance
    "ti_uuid": str      # UUID of removed Task Instance (if found)
}
```

### `/queue/submit`

Submit a task to be scheduled to the current Scheduler

Parameter Design
```python
{
    "model_name": str,            # Target model name
    "task_input": Dict[str, Any], # Task information submitted to Task Instance
    "metadata": Dict[str, Any]    # Metadata submitted to Predictor for predicting model execution time distribution
}
```

Return Format
```python
{
    "status": str,              # "success" or "error"
    "task_id": str,             # Submitted task ID
    "scheduled_ti": UUID,       # UUID of Task Instance scheduled to
}
```

### `/queue/info`

Get information about all Queues on the current Scheduler

Parameter Design
```python
{
    "model_name": str           # (Optional) Specify model name, if not specified returns information for all models
}
```

Return Format
```python
{
    "status": str,
    "queues": List[{
        "model_name": str,
        "ti_uuid": UUID,
        "waiting_time_expect": float,  # Expected waiting time (mean)
        "waiting_time_error": float,   # Waiting time error (standard deviation)
    }]
}
```

### `/task/query`

Query scheduling information for a specific Task

Parameter Design
```python
{
    "task_id": str              # Task unique identifier
}
```

Return Format
```python
{
    "task_id": str,
    "task_status": str,         # "queued", "scheduled", "completed"
    "scheduled_ti": UUID,       # UUID of Task Instance scheduled to
    "submit_time": float,       # Submission timestamp
    "result": Any               # Task result (if completed)
}
```
