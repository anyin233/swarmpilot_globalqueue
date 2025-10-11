# Scheduler

The Scheduler is responsible for distributing tasks to different Task Instances. Acting as a central scheduler, it maintains state information for all Task Instances and routes each task to the optimal Task Instance based on the selected scheduling strategy and queue prediction results.

Each Scheduler internally maintains:
- Queue information (prediction info) for each Task Instance: includes expected wait time mean and error range
- Connection information for each Task Instance: includes network address, port, health status, etc.
- All Task Instances corresponding to each model: supports multi-model scheduling, each model can have multiple Task Instance replicas

All Task Instances are uniquely identified by a UUID to ensure uniqueness in distributed environments.

Specifically, the data structures are:
```python
ti_queue_info: Dict{UUID: (float, float)}  # UUID -> (expected wait time, error)
ti_conn_info : Dict{UUID: List[str, Any]}  # UUID -> [connection address, other config info]
model_to_ti  : Dict{str: List[UUID]}       # model name -> Task Instance UUID list
```

## API Design


### `/scheduler/set`

Select and set the scheduling strategy used by the Scheduler. The Scheduler supports multiple scheduling strategies, including shortest_queue, round_robin, weighted, and probabilistic. Strategy changes take effect immediately, affecting all subsequent task scheduling decisions.

Parameter Design
```python
{
    "name": str  # Scheduling strategy name, e.g., "shortest_queue", "round_robin", "weighted", "probabilistic"
}
```

Return Format

```python
{
    "status": str,   # "success" indicates strategy set successfully, "error" indicates failure
    "message": str,  # "OK" if status is success; specific error reason if status is error (e.g., strategy name does not exist)
}
```

### `/scheduler/predict_mode`

Select the working mode of the predictor. The predictor estimates task execution time on each Task Instance and supports two working modes:

- **Standard Prediction Mode (default)**: Uses trained machine learning models for real-time prediction, higher accuracy but with some computational overhead
- **Lookup Table Mode (lookup_table)**: Uses pre-computed lookup tables, faster but less flexible

Parameter Design
```python
{
    "mode": str,  # Prediction mode:
                  # "default" - Use standard prediction model for real-time prediction
                  # "lookup_table" - Use pre-computed lookup table for fast queries
}
```

Return Format

```python
{
    "status": str,   # "success" indicates mode switch successful, "error" indicates failure
    "message": str,  # "OK" if status is success; specific error reason if status is error (e.g., unsupported mode type)
}
```

### `/ti/register`

Register a Task Instance to the current Scheduler. After successful registration, the Scheduler will include the Task Instance in the scheduling pool, and subsequently submitted tasks may be assigned to this instance. Registration will verify the Task Instance's reachability and health status.

Parameter Design
```python
{
    "host": str,  # Task Instance host address, can be an IP address (e.g., "192.168.1.100") or domain name (e.g., "worker1.example.com")
    "port": int   # Task Instance HTTP service port number, typically defaults to 8100
}
```

Return Format
```python
{
    "status": str,    # "success" indicates successful registration, "error" indicates failure
    "message": str,   # Returns description on success (e.g., "TaskInstance registered successfully")
                      # Returns error reason on failure (e.g., "Connection refused" or "Health check failed")
    "ti_uuid": UUID   # Globally unique identifier assigned to this Task Instance, required for subsequent operations
                      # Empty string if registration fails
}
```

### `/ti/remove`

Remove a Task Instance from the current Scheduler. After removal, the Task Instance will no longer receive new tasks, but tasks already assigned to it will continue executing until completion. The removal operation is safe and will not interrupt running tasks.

Parameter Design
```python
{
    "ti_uuid": UUID  # Unique identifier of the Task Instance to remove, assigned by Scheduler during registration
                     # Must be a valid registered UUID, otherwise operation fails
}
```

Return Format
```python
{
    "status": str,    # "success" indicates successful removal, "error" indicates failure
    "message": str,   # Returns description on success (e.g., "TaskInstance removed successfully")
                      # Returns error reason on failure (e.g., "TaskInstance not found" or "Invalid UUID format")
    "ti_uuid": UUID   # UUID of the removed Task Instance, used to confirm the operation target
                      # Returns the provided UUID for debugging if UUID does not exist
}
```

### `/queue/submit`

Submit a task to be scheduled to the current Scheduler. The Scheduler will select the optimal Task Instance to execute the task based on the current scheduling strategy, queue status of each Task Instance, and predicted execution time. Returns a task ID upon successful submission for subsequent status queries.

Parameter Design
```python
{
    "model_name": str,            # Target model name (e.g., "gpt-3.5-turbo", "llama-7b", etc.)
                                  # Scheduler will select from Task Instances registered with this model

    "task_input": Dict[str, Any], # Task input information submitted to Task Instance
                                  # Specific format depends on target model requirements
                                  # Common fields: {"prompt": "...", "max_tokens": 100, "temperature": 0.7}

    "metadata": Dict[str, Any]    # Metadata submitted to Predictor for predicting model execution time distribution
                                  # May include: {"hardware": "A100", "input_tokens": 100, "output_tokens": 50}
                                  # More detailed metadata helps improve prediction accuracy
}
```

Return Format
```python
{
    "status": str,              # "success" indicates task successfully scheduled, "error" indicates scheduling failure
    "task_id": str,             # Globally unique identifier for the submitted task, used for subsequent status and result queries
                                # Format typically "task-{uuid}"

    "scheduled_ti": UUID,       # UUID of the Task Instance the task was scheduled to
                                # Can be used to track task allocation and load balancing analysis
                                # May be empty if scheduling fails
}
```

**Important Notes**:
- Submission will fail if no Task Instances are registered
- Submission will fail if the specified model_name has no corresponding Task Instances
- Recommend providing as much detail as possible in metadata to improve scheduling quality

### `/queue/info`

Get information about all Queues on the current Scheduler. Returns the queue status of each Task Instance, including expected wait time mean and error range. This interface is commonly used for monitoring system load, analyzing scheduling effectiveness, and making load balancing decisions.

Parameter Design
```python
{
    "model_name": str  # (Optional parameter) Specify model name to return only Task Instance queue info for that model
                       # If not specified (null or empty), returns info for all Task Instances across all models
                       # Used to filter and focus on specific model load conditions
}
```

Return Format
```python
{
    "status": str,      # "success" indicates successful query, "error" indicates failure
    "queues": List[{    # Queue information list, each element represents a Task Instance's queue status
        "model_name": str,                 # Model name running on this Task Instance
        "ti_uuid": UUID,                   # Unique identifier of the Task Instance
        "waiting_time_expect": float,      # Expected wait time mean (unit: milliseconds)
                                           # Indicates how long a newly submitted task to this instance is expected to wait before starting execution
        "waiting_time_error": float,       # Wait time error (standard deviation, unit: milliseconds)
                                           # Indicates prediction uncertainty range; smaller value means more accurate prediction
    }]
}
```

**Use Cases**:
- Monitoring dashboard displays real-time queue loads
- Clients proactively select lower-load queues to submit tasks
- Analyze system bottlenecks and optimize scheduling strategies

### `/task/query`

Query scheduling information and execution status of a specific Task. Can be used to track the complete lifecycle of a task, from submission, scheduling, execution to completion. Supports polling to wait for task completion.

Parameter Design
```python
{
    "task_id": str  # Globally unique identifier of the task, returned by Scheduler upon task submission
                    # Format typically "task-{uuid}"
                    # Must be a valid, submitted task ID
}
```

Return Format
```python
{
    "task_id": str,               # Task ID, consistent with query parameter

    "task_status": str,           # Current task status, possible values:
                                  # "queued" - Submitted but not yet scheduled to Task Instance
                                  # "scheduled" - Scheduled to Task Instance, waiting or executing
                                  # "completed" - Execution complete, result returned

    "scheduled_ti": UUID,         # UUID of the Task Instance the task was scheduled to
                                  # Can be used to locate task execution location

    "submit_time": float,         # Task submission timestamp (Unix timestamp, milliseconds precision)
                                  # Can be used to calculate total task duration

    "result": Any                 # Task execution result (only has value when task_status is "completed")
                                  # Specific format depends on task type
                                  # Also returns error information in this field on execution failure
                                  # null when not yet completed
}
```

**Usage Recommendations**:
- When polling queries, recommend using exponential backoff strategy to avoid frequent requests
- After task completion, results may be cleaned up after some time; recommend retrieving promptly
- Can combine with submit_time to calculate end-to-end task latency
