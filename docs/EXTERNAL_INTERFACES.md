# External Interfaces Documentation

> Complete specification for all external module interfaces

**Version**: 2.0.0
**Last Updated**: 2025-10-11

---

## Table of Contents

1. [Overview](#overview)
2. [TaskInstance Interface](#taskinstance-interface)
3. [Predictor Interface](#predictor-interface)
4. [Implementation Status](#implementation-status)
5. [Integration Examples](#integration-examples)

---

## Overview

The Scheduler interacts with two external services:

1. **TaskInstance Service**: Executes tasks and manages model replicas
2. **Predictor Service**: Provides execution time predictions for scheduling decisions

Both interfaces are fully defined with request/response models and client implementations.

---

## TaskInstance Interface

### Overview

TaskInstance is a worker service that manages model replicas and executes tasks. The Scheduler communicates with TaskInstance to:
- Submit tasks for execution
- Query queue status
- Retrieve execution results
- Manage model replicas (start/stop)

### Client Implementation

**Class**: `TaskInstanceClient` (in `src/scheduler/client.py`)

**Status**: ✅ **FULLY IMPLEMENTED**

**Usage**:
```python
from src.scheduler import TaskInstanceClient

client = TaskInstanceClient("http://localhost:8100")

# Enqueue a task
response = client.enqueue_task(
    input_data={"prompt": "Hello, world!"},
    metadata={"user_id": "123"}
)
print(f"Task ID: {response.task_id}")
```

### API Endpoints

#### 1. Start Models

**Endpoint**: `POST /models/start`

**Description**: Start homogeneous model replicas on this TaskInstance.

**Request**:
```json
{
  "model_type": "gpt-3.5-turbo",
  "count": 2,
  "config": {},
  "num_gpus_per_model": 1
}
```

**Response**:
```json
{
  "detail": "Started 2 replicas",
  "model_type": "gpt-3.5-turbo",
  "replicas_started": 2,
  "total_replicas": 2
}
```

**Client Method**: `client.start_models(model_type, count, config, num_gpus_per_model)`

---

#### 2. Stop Models

**Endpoint**: `POST /models/stop`

**Description**: Stop model replicas.

**Request**:
```json
{
  "count": 1  // Number to stop, null = stop all
}
```

**Response**:
```json
{
  "detail": "Stopped 1 replica(s)",
  "stopped_replicas": ["replica-1"],
  "remaining_replicas": 1
}
```

**Client Method**: `client.stop_models(count)`

---

#### 3. Get Instance Status

**Endpoint**: `GET /status`

**Description**: Get TaskInstance status and configuration.

**Response**:
```json
{
  "instance_id": "task-instance-1",
  "model_type": "gpt-3.5-turbo",
  "replicas_running": 2,
  "queue_size": 5,
  "status": "running"  // or "idle"
}
```

**Client Method**: `client.get_status()`

---

#### 4. Enqueue Task

**Endpoint**: `POST /queue/enqueue`

**Description**: Submit a task to this TaskInstance's queue.

**Request**:
```json
{
  "input_data": {
    "prompt": "What is AI?",
    "max_tokens": 100,
    "temperature": 0.7
  },
  "metadata": {
    "user_id": "user123",
    "priority": "normal"
  }
}
```

**Response**:
```json
{
  "task_id": "task-abc123",
  "queue_size": 6,
  "enqueue_time": 1697123456.789
}
```

**Client Method**: `client.enqueue_task(input_data, metadata)`

---

#### 5. Predict Queue Time

**Endpoint**: `POST /queue/predict`

**Description**: Get predicted queue completion time based on current queue state.

**Response**:
```json
{
  "expected_ms": 1500.5,
  "error_ms": 200.0,
  "queue_size": 5
}
```

**Client Method**: `client.predict_queue()`

---

#### 6. Get Queue Status

**Endpoint**: `GET /queue/status`

**Description**: Get current queue status.

**Response**:
```json
{
  "queue_size": 5,
  "model_type": "gpt-3.5-turbo",
  "expected_ms": 1500.5,
  "error_ms": 200.0
}
```

**Client Method**: `client.get_queue_status()`

---

#### 7. Get Task Result

**Endpoint**: `GET /results/{task_id}`

**Description**: Retrieve result for a completed task.

**Response**:
```json
{
  "task_id": "task-abc123",
  "result": {
    "output": "AI stands for Artificial Intelligence...",
    "tokens_used": 95
  },
  "status": "completed",
  "error": null,
  "enqueue_time": 1697123456.789,
  "completion_time": 1697123458.234,
  "wait_time": 500.0,
  "execution_time": 945.0,
  "total_time": 1445.0
}
```

**Client Method**: `client.get_result(task_id)`

---

#### 8. Get All Results

**Endpoint**: `GET /results`

**Description**: Get all available results from this TaskInstance.

**Response**: Array of `TaskResult` objects (see above)

**Client Method**: `client.get_all_results()`

---

### TaskInstance Data Models

All models are defined in `src/scheduler/models.py`:

- `StartModelsRequest` / `StartModelsResponse`
- `StopModelsRequest` / `StopModelsResponse`
- `InstanceStatusResponse`
- `QueueStatusResponse`
- `EnqueueRequest` / `EnqueueResponse`
- `PredictResponse`
- `TaskResult`

---

## Predictor Interface

### Overview

Predictor is a service that provides execution time predictions for tasks. The Scheduler uses these predictions to:
- Estimate queue wait times
- Make informed scheduling decisions
- Select optimal TaskInstance for each task

The Predictor analyzes model type and metadata to return quantile-based execution time distributions.

### Client Implementation

**Class**: `PredictorClient` (in `src/scheduler/predictor_client.py`)

**Status**: ⚠️ **INTERFACE DEFINED - AWAITING IMPLEMENTATION**

**Usage**:
```python
from src.scheduler import PredictorClient

predictor = PredictorClient("http://localhost:8200")

# Get prediction
response = predictor.predict(
    model_type="gpt-3.5-turbo",
    metadata={
        "hardware": "A100",
        "input_tokens": 100,
        "output_tokens": 50
    }
)

if response.status == "success":
    print(f"Median prediction: {response.quantile_predictions[2]}ms")
```

### API Endpoints

#### 1. Predict Execution Time

**Endpoint**: `POST /predict`

**Description**: Request execution time prediction for a task.

**Request**:
```json
{
  "model_type": "gpt-3.5-turbo",
  "metadata": {
    "model_name": "gpt-3.5-turbo-0613",
    "hardware": "A100",
    "software_name": "vllm",
    "software_version": "0.2.0",
    "input_tokens": 100,
    "output_tokens": 50,
    "batch_size": 1
  }
}
```

**Response (Success)**:
```json
{
  "status": "success",
  "message": null,
  "model_type": "gpt-3.5-turbo",
  "quantiles": [0.1, 0.25, 0.5, 0.75, 0.9],
  "quantile_predictions": [850.0, 1050.0, 1300.0, 1650.0, 2100.0],
  "prediction_method": "lookup",
  "confidence": 0.85
}
```

**Response (Error)**:
```json
{
  "status": "error",
  "message": "No prediction data available for model type: unknown-model"
}
```

**Client Method**: `predictor.predict(model_type, metadata)`

**Implementation Status**: 🔴 **TODO - Requires Predictor Service**

The client method is implemented with TODO placeholders. To complete:

1. Deploy a Predictor service at the configured URL
2. Implement the `/predict` endpoint in the Predictor service
3. Uncomment the actual HTTP request code in `PredictorClient.predict()`

**Code Location**: `src/scheduler/predictor_client.py:87-159`

---

#### 2. Health Check

**Endpoint**: `GET /health`

**Description**: Check if Predictor service is healthy.

**Response**:
```json
{
  "status": "healthy",
  "service": "predictor",
  "version": "1.0.0",
  "total_models": 15
}
```

**Client Method**: `predictor.health_check()`

**Implementation Status**: 🔴 **TODO - Requires Predictor Service**

**Code Location**: `src/scheduler/predictor_client.py:161-188`

---

#### 3. List Available Models

**Endpoint**: `GET /models`

**Description**: Get list of models available for prediction.

**Response**:
```json
{
  "status": "success",
  "models": [
    {
      "model_type": "gpt-3.5-turbo",
      "model_name": "GPT-3.5 Turbo",
      "total_predictions": 1500,
      "hardware_types": ["A100", "V100"],
      "software_versions": ["vllm-0.2.0", "vllm-0.2.1"]
    },
    {
      "model_type": "llama-7b",
      "model_name": "LLaMA 7B",
      "total_predictions": 800,
      "hardware_types": ["A100"],
      "software_versions": ["vllm-0.2.0"]
    }
  ]
}
```

**Client Method**: `predictor.get_available_models()`

**Implementation Status**: 🔴 **TODO - Requires Predictor Service**

**Code Location**: `src/scheduler/predictor_client.py:190-220`

---

### Predictor Data Models

All models are defined in `src/scheduler/models.py`:

- `PredictorRequest`: Input for prediction
- `PredictorResponse`: Prediction results with quantiles
- `PredictorHealthResponse`: Health check response
- `PredictorModelInfo`: Model metadata
- `PredictorModelsResponse`: List of available models

### Metadata Fields

The `metadata` field in `PredictorRequest` can include various fields for better predictions:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `model_name` | str | Specific model variant | `"gpt-3.5-turbo-0613"` |
| `hardware` | str | Hardware identifier | `"A100"`, `"V100"` |
| `software_name` | str | Framework name | `"vllm"`, `"pytorch"` |
| `software_version` | str | Framework version | `"0.2.0"` |
| `input_tokens` | int | Input token count | `100` |
| `output_tokens` | int | Output token count | `50` |
| `batch_size` | int | Batch size | `1` |

All fields are optional. More detailed metadata typically leads to more accurate predictions.

---

## Implementation Status

### Summary Table

| Component | Status | Implementation |
|-----------|--------|----------------|
| **TaskInstanceClient** | ✅ Complete | Fully implemented in `client.py` |
| **TaskInstance Models** | ✅ Complete | Defined in `models.py` |
| **PredictorClient** | ⚠️ Interface Defined | Client exists with TODO placeholders |
| **Predictor Models** | ✅ Complete | Defined in `models.py` |
| **Predictor Service** | 🔴 Not Implemented | Requires external implementation |

### What's Implemented

1. ✅ **TaskInstanceClient**: Complete HTTP client for TaskInstance API
2. ✅ **All Data Models**: Pydantic models for all requests/responses
3. ✅ **PredictorClient Interface**: Complete interface with method signatures and documentation
4. ✅ **Error Handling**: Graceful error handling for all client methods
5. ✅ **Type Safety**: Full type hints and Pydantic validation

### What Needs Implementation

1. 🔴 **Predictor Service**: External service at `http://predictor:8200` (or configured URL)
   - Must implement `/predict` endpoint
   - Must implement `/health` endpoint
   - Must implement `/models` endpoint
   - See endpoint specifications above for request/response formats

2. 🔴 **Predictor Client Activation**: Uncomment actual HTTP requests in `predictor_client.py`
   - Currently returns placeholder error responses
   - Search for `# TODO: Replace with actual` comments in code

---

## Integration Examples

### Example 1: Using TaskInstanceClient

```python
from src.scheduler import TaskInstanceClient

# Initialize client
client = TaskInstanceClient("http://taskinstance:8100")

# Start models
start_response = client.start_models(
    model_type="gpt-3.5-turbo",
    count=2,
    num_gpus_per_model=1
)
print(f"Started {start_response.replicas_started} replicas")

# Submit task
task_response = client.enqueue_task(
    input_data={"prompt": "Hello!", "max_tokens": 100},
    metadata={"user_id": "123"}
)
print(f"Task ID: {task_response.task_id}")

# Get queue prediction
prediction = client.predict_queue()
print(f"Expected wait time: {prediction.expected_ms}ms ± {prediction.error_ms}ms")

# Check if task completed (poll in real scenario)
try:
    result = client.get_result(task_response.task_id)
    if result.status == "completed":
        print(f"Result: {result.result}")
except httpx.HTTPError:
    print("Task not yet completed")

# Cleanup
client.close()
```

### Example 2: Using PredictorClient (After Implementation)

```python
from src.scheduler import PredictorClient

# Initialize client
predictor = PredictorClient("http://predictor:8200")

# Check if service is available
if predictor.is_available():
    # Get prediction
    response = predictor.predict(
        model_type="gpt-3.5-turbo",
        metadata={
            "hardware": "A100",
            "input_tokens": 100,
            "output_tokens": 50
        }
    )

    if response.status == "success":
        # Use quantile predictions
        median_time = response.quantile_predictions[2]  # Assuming 0.5 quantile at index 2
        print(f"Median execution time: {median_time}ms")

        # Get prediction range (convenience method)
        min_time, max_time = predictor.get_prediction_range(
            "gpt-3.5-turbo",
            {"hardware": "A100"},
            confidence_level=0.8  # 80% confidence
        )
        print(f"80% confidence range: {min_time}ms - {max_time}ms")
else:
    print("Predictor service not available")

predictor.close()
```

### Example 3: Integrated Scheduling Flow

```python
from src.scheduler import (
    SwarmPilotScheduler,
    TaskInstanceClient,
    PredictorClient,
    SchedulerRequest
)

# Initialize components
scheduler = SwarmPilotScheduler()
predictor = PredictorClient("http://predictor:8200")

# Register TaskInstances
ti_client_1 = TaskInstanceClient("http://ti1:8100")
ti_uuid_1 = scheduler.add_task_instance("http://ti1:8100", model_name="gpt-3.5-turbo")

ti_client_2 = TaskInstanceClient("http://ti2:8100")
ti_uuid_2 = scheduler.add_task_instance("http://ti2:8100", model_name="gpt-3.5-turbo")

# Submit task with prediction
metadata = {
    "hardware": "A100",
    "input_tokens": 100,
    "output_tokens": 50
}

# Get prediction (optional, for logging/monitoring)
if predictor.is_available():
    pred_response = predictor.predict("gpt-3.5-turbo", metadata)
    if pred_response.status == "success":
        print(f"Expected time: {pred_response.quantile_predictions[2]}ms")

# Schedule task (scheduler handles TaskInstance selection)
request = SchedulerRequest(
    model_type="gpt-3.5-turbo",
    input_data={"prompt": "What is AI?", "max_tokens": 100},
    metadata=metadata
)

response = scheduler.schedule(request)
print(f"Task {response.task_id} scheduled to instance {response.instance_id}")

# Query task status
task_info = scheduler.task_tracker.get_task_info(response.task_id)
print(f"Task status: {task_info.task_status}")
```

### Example 4: Context Manager Usage

```python
from src.scheduler import TaskInstanceClient, PredictorClient

# Using context managers for automatic cleanup
with TaskInstanceClient("http://taskinstance:8100") as ti_client, \
     PredictorClient("http://predictor:8200") as predictor:

    # Get prediction
    pred = predictor.predict("gpt-3.5-turbo", {"hardware": "A100"})

    # Submit task
    if pred.status == "success":
        response = ti_client.enqueue_task(
            input_data={"prompt": "Hello!"},
            metadata={"expected_time": pred.quantile_predictions[2]}
        )
        print(f"Task ID: {response.task_id}")

# Clients automatically closed after context exit
```

---

## Fallback Mechanisms

### LookupPredictor (Current Fallback)

When the Predictor service is not available, the system can use `LookupPredictor`:

```python
from src.scheduler import LookupPredictor

# Initialize with local prediction file
predictor = LookupPredictor("/path/to/predictions.json")

# Get prediction from local file
prediction = predictor.predict(
    model_type="gpt-3.5-turbo",
    metadata={"hardware": "A100"}
)

if prediction:
    quantile_predictions = prediction["quantile_predictions"]
    median = quantile_predictions[len(quantile_predictions) // 2]
    print(f"Median: {median}ms")
```

**Prediction File Format** (`predictions.json`):
```json
[
  {
    "status": "success",
    "model_type": "gpt-3.5-turbo",
    "model_info": {
      "type": "gpt-3.5-turbo",
      "hardware": "A100",
      "software_name": "vllm",
      "software_version": "0.2.0"
    },
    "quantiles": [0.1, 0.25, 0.5, 0.75, 0.9],
    "quantile_predictions": [850.0, 1050.0, 1300.0, 1650.0, 2100.0]
  }
]
```

---

## Testing

### Testing TaskInstanceClient

TaskInstanceClient is fully tested in `tests/test_client.py`. Run tests:

```bash
uv run pytest tests/test_client.py -v
```

### Testing PredictorClient

Basic tests for PredictorClient interface are in `tests/test_predictor_client.py`. These test:
- Client initialization
- Model validation
- Error handling
- Convenience methods

Once the Predictor service is implemented, add integration tests.

---

## Troubleshooting

### Issue: TaskInstanceClient connection errors

**Symptoms**: `httpx.ConnectError` when calling TaskInstanceClient methods

**Solutions**:
1. Verify TaskInstance service is running: `curl http://localhost:8100/status`
2. Check network connectivity
3. Verify base_url is correct
4. Check firewall rules

### Issue: PredictorClient returns error responses

**Symptoms**: `predictor.predict()` returns `status="error"`

**Cause**: Predictor service not yet implemented (expected behavior)

**Solutions**:
1. Use `LookupPredictor` as fallback with local prediction file
2. Implement Predictor service according to API specification
3. Activate PredictorClient by uncommenting HTTP request code

### Issue: Empty prediction results

**Symptoms**: `response.quantile_predictions` is None or empty

**Solutions**:
1. Check that metadata fields match available prediction data
2. Verify model_type is correct
3. For LookupPredictor: check prediction file format and content
4. For PredictorClient: check service logs for errors

---

## See Also

- [Integration Guide](INTEGRATION_GUIDE.md) - Complete Scheduler API integration
- [API Specification](Scheduler.md) - Scheduler REST API endpoints
- [Lookup Predictor](LOOKUP_PREDICTOR.md) - Local file-based predictor documentation

---

**Last Updated**: 2025-10-11
**Document Version**: 2.0.0
