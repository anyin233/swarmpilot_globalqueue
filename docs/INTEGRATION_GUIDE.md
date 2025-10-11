# SwarmPilot Scheduler Integration Guide

> Complete integration guide for external services and LLM agents

**Version**: 2.0.0
**Last Updated**: 2025-10-11
**API Base URL**: `http://localhost:8102` (default)

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [API Reference](#api-reference)
4. [Integration Patterns](#integration-patterns)
5. [Data Models](#data-models)
6. [Error Handling](#error-handling)
7. [Best Practices](#best-practices)
8. [Code Examples](#code-examples)

---

## Overview

### What is SwarmPilot Scheduler?

SwarmPilot Scheduler is a task scheduling service that distributes computational tasks across multiple TaskInstance workers. It provides:

- **Intelligent Routing**: Automatically selects the optimal TaskInstance based on queue length, prediction, and strategy
- **Task Tracking**: Complete lifecycle tracking from submission to completion
- **Multiple Strategies**: ShortestQueue, RoundRobin, Weighted, Probabilistic
- **REST API**: Simple HTTP-based integration

### Architecture

```
┌─────────────┐      ┌──────────────────┐      ┌──────────────┐
│   Client    │─────▶│    Scheduler     │─────▶│ TaskInstance │
│ (Your App)  │◀─────│   (This Module)  │◀─────│   Worker 1   │
└─────────────┘      └──────────────────┘      └──────────────┘
                              │                  ┌──────────────┐
                              └─────────────────▶│ TaskInstance │
                                                 │   Worker 2   │
                                                 └──────────────┘
```

### Key Concepts

- **TaskInstance**: A worker service that executes tasks
- **Scheduler**: This service - routes tasks to optimal TaskInstance
- **Task**: A unit of work submitted for execution
- **Strategy**: Algorithm for selecting which TaskInstance receives a task

---

## Quick Start

### 1. Start the Scheduler

```bash
# Start with default settings
uvicorn src.scheduler.api:app --host 0.0.0.0 --port 8102

# Or with configuration file
python cli.py start --port 8102 --config instances.yaml
```

### 2. Register TaskInstances

```bash
curl -X POST http://localhost:8102/ti/register \
  -H "Content-Type: application/json" \
  -d '{
    "host": "worker1.example.com",
    "port": 8100,
    "model_name": "gpt-3.5-turbo"
  }'
```

### 3. Submit a Task

```bash
curl -X POST http://localhost:8102/queue/submit \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "gpt-3.5-turbo",
    "task_input": {
      "prompt": "What is AI?",
      "max_tokens": 100
    },
    "metadata": {
      "user_id": "user123",
      "priority": "normal"
    }
  }'
```

### 4. Query Task Status

```bash
curl "http://localhost:8102/task/query?task_id=<task_id>"
```

---

## API Reference

### Base URL

```
http://localhost:8102
```

All endpoints return JSON responses.

---

### 1. Health Check

**Endpoint**: `GET /health`

**Description**: Check if the scheduler service is running.

**Request**: None

**Response**:
```json
{
  "status": "healthy",
  "service": "scheduler",
  "version": "2.0.0"
}
```

**Status Codes**:
- `200 OK`: Service is healthy

---

### 2. Register TaskInstance

**Endpoint**: `POST /ti/register`

**Description**: Register a new TaskInstance worker with the scheduler.

**Request Body**:
```json
{
  "host": "string",       // TaskInstance hostname or IP
  "port": integer,        // TaskInstance port number
  "model_name": "string"  // Model name that this instance runs (for queue filtering)
}
```

**Example**:
```json
{
  "host": "192.168.1.100",
  "port": 8100,
  "model_name": "gpt-3.5-turbo"
}
```

**Response**:
```json
{
  "status": "success",
  "message": "TaskInstance registered successfully for model gpt-3.5-turbo",
  "ti_uuid": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Error Response**:
```json
{
  "status": "error",
  "message": "Connection failed: Unable to reach host",
  "ti_uuid": ""
}
```

**Status Codes**:
- `200 OK`: Registration processed (check status field)

---

### 3. Remove TaskInstance

**Endpoint**: `POST /ti/remove`

**Description**: Remove a TaskInstance from the scheduler by host and port.

**Request Body**:
```json
{
  "host": "string",  // Host address of the TaskInstance to remove
  "port": integer    // Port number of the TaskInstance to remove
}
```

**Example**:
```json
{
  "host": "192.168.1.100",
  "port": 8100
}
```

**Response**:
```json
{
  "status": "success",
  "message": "TaskInstance removed successfully",
  "host": "192.168.1.100",
  "port": 8100,
  "ti_uuid": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Error Response**:
```json
{
  "status": "error",
  "message": "TaskInstance at 192.168.1.100:8100 not found",
  "host": "192.168.1.100",
  "port": 8100,
  "ti_uuid": null
}
```

**Status Codes**:
- `200 OK`: Removal processed (check status field)

---

### 4. Submit Task

**Endpoint**: `POST /queue/submit`

**Description**: Submit a task for execution. The scheduler will select the optimal TaskInstance and route the task.

**Request Body**:
```json
{
  "model_name": "string",      // Model type/name to use
  "task_input": object,        // Task-specific input data
  "metadata": object           // Optional metadata
}
```

**Example**:
```json
{
  "model_name": "gpt-3.5-turbo",
  "task_input": {
    "prompt": "Explain quantum computing",
    "max_tokens": 150,
    "temperature": 0.7
  },
  "metadata": {
    "user_id": "user123",
    "session_id": "sess456",
    "priority": "high"
  }
}
```

**Response**:
```json
{
  "status": "success",
  "task_id": "task-abc123",
  "scheduled_ti": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Error Response**:
```json
{
  "detail": "No TaskInstances configured for model gpt-4"
}
```

**Status Codes**:
- `200 OK`: Task successfully scheduled
- `503 Service Unavailable`: No TaskInstances available or no matching model

---

### 5. Get Queue Information

**Endpoint**: `GET /queue/info`

**Description**: Get information about all registered TaskInstance queues.

**Query Parameters**:
- `model_name` (optional): Filter by specific model name

**Example**:
```bash
# Get all queues
GET /queue/info

# Get queues for specific model
GET /queue/info?model_name=gpt-3.5-turbo
```

**Response**:
```json
{
  "status": "success",
  "queues": [
    {
      "model_name": "gpt-3.5-turbo",
      "ti_uuid": "550e8400-e29b-41d4-a716-446655440000",
      "waiting_time_expect": 120.5,
      "waiting_time_error": 15.2
    },
    {
      "model_name": "gpt-3.5-turbo",
      "ti_uuid": "660e8400-e29b-41d4-a716-446655440001",
      "waiting_time_expect": 85.3,
      "waiting_time_error": 12.1
    }
  ]
}
```

**Status Codes**:
- `200 OK`: Queue information retrieved
- `500 Internal Server Error`: Failed to get queue information

---

### 6. Query Task Status

**Endpoint**: `GET /task/query`

**Description**: Query the status of a submitted task.

**Query Parameters**:
- `task_id` (required): The task ID returned from /queue/submit

**Example**:
```bash
GET /task/query?task_id=task-abc123
```

**Response**:
```json
{
  "task_id": "task-abc123",
  "task_status": "completed",
  "scheduled_ti": "550e8400-e29b-41d4-a716-446655440000",
  "submit_time": 1697123456.789,
  "result": {
    "output": "Quantum computing uses quantum mechanics...",
    "tokens_used": 145
  }
}
```

**Task Status Values**:
- `queued`: Task is waiting in queue
- `scheduled`: Task has been sent to TaskInstance
- `completed`: Task execution finished

**Error Response**:
```json
{
  "detail": "Task task-abc123 not found"
}
```

**Status Codes**:
- `200 OK`: Task found
- `404 Not Found`: Task does not exist

---

### 7. Task Completion Notification

**Endpoint**: `POST /notify/task_complete`

**Description**: Notify the scheduler that a task has completed (typically called by TaskInstance).

**Request Body**:
```json
{
  "task_id": "string",
  "instance_id": "string",
  "execution_time": float,
  "result": object
}
```

**Example**:
```json
{
  "task_id": "task-abc123",
  "instance_id": "worker1-instance",
  "execution_time": 125.5,
  "result": {
    "output": "Task completed successfully",
    "status": "success"
  }
}
```

**Response**:
```json
{
  "status": "success",
  "message": "Task task-abc123 completion processed",
  "total_time_ms": 156.8
}
```

**Status Codes**:
- `200 OK`: Notification processed

---

## Integration Patterns

### Pattern 1: Simple Task Submission

```python
import requests

# Submit task and get result
def submit_and_wait(model_name, task_input):
    # 1. Submit task
    response = requests.post(
        "http://localhost:8102/queue/submit",
        json={
            "model_name": model_name,
            "task_input": task_input,
            "metadata": {}
        }
    )
    task_data = response.json()
    task_id = task_data["task_id"]

    # 2. Poll for completion
    import time
    while True:
        status_response = requests.get(
            f"http://localhost:8102/task/query?task_id={task_id}"
        )
        status_data = status_response.json()

        if status_data["task_status"] == "completed":
            return status_data["result"]

        time.sleep(1)  # Wait 1 second before next check
```

### Pattern 2: Batch Task Submission

```python
def submit_batch(tasks):
    """Submit multiple tasks in parallel"""
    task_ids = []

    for task in tasks:
        response = requests.post(
            "http://localhost:8102/queue/submit",
            json={
                "model_name": task["model"],
                "task_input": task["input"],
                "metadata": {"batch_id": task.get("batch_id")}
            }
        )
        task_ids.append(response.json()["task_id"])

    return task_ids
```

### Pattern 3: Queue Monitoring

```python
def monitor_queues(model_name):
    """Monitor queue status for a specific model"""
    response = requests.get(
        f"http://localhost:8102/queue/info?model_name={model_name}"
    )
    data = response.json()

    for queue in data["queues"]:
        print(f"Instance {queue['ti_uuid'][:8]}...")
        print(f"  Expected wait: {queue['waiting_time_expect']:.1f}ms")
        print(f"  Error margin: {queue['waiting_time_error']:.1f}ms")
```

### Pattern 4: Dynamic Instance Management

```python
class SchedulerClient:
    def __init__(self, base_url="http://localhost:8102"):
        self.base_url = base_url
        self.instances = {}

    def register_instance(self, host, port, model_name):
        """Register a new TaskInstance"""
        response = requests.post(
            f"{self.base_url}/ti/register",
            json={"host": host, "port": port, "model_name": model_name}
        )
        data = response.json()
        if data["status"] == "success":
            self.instances[data["ti_uuid"]] = {"host": host, "port": port}
            return data["ti_uuid"]
        return None

    def remove_instance(self, host, port):
        """Remove a TaskInstance by host and port"""
        response = requests.post(
            f"{self.base_url}/ti/remove",
            json={"host": host, "port": port}
        )
        data = response.json()
        if data["status"] == "success":
            # Remove from local tracking using returned UUID
            if data.get("ti_uuid"):
                self.instances.pop(data["ti_uuid"], None)
            return True
        return False
```

---

## Data Models

### Task Input Structure

```json
{
  "model_name": "string",      // Required: Model identifier
  "task_input": {              // Required: Model-specific input
    "prompt": "string",        // Common for LLM tasks
    "max_tokens": integer,     // Optional parameters
    "temperature": float,
    // ... other model-specific fields
  },
  "metadata": {                // Optional: Any additional data
    "user_id": "string",
    "session_id": "string",
    "priority": "string",
    "callback_url": "string"
  }
}
```

### Task Status Response

```json
{
  "task_id": "string",
  "task_status": "queued|scheduled|completed",
  "scheduled_ti": "uuid-string",
  "submit_time": float,         // Unix timestamp
  "result": object|null         // Available when completed
}
```

### Queue Information

```json
{
  "model_name": "string",
  "ti_uuid": "string",
  "waiting_time_expect": float,  // Expected wait in milliseconds
  "waiting_time_error": float    // Prediction error margin
}
```

---

## Error Handling

### Error Response Format

All errors follow this structure:

```json
{
  "detail": "Error message description"
}
```

Or for operations with status field:

```json
{
  "status": "error",
  "message": "Error message description"
}
```

### Common Error Scenarios

#### 1. No TaskInstances Available

**HTTP 503**: Service Unavailable

```json
{
  "detail": "No TaskInstances configured for model gpt-4"
}
```

**Solution**: Register at least one TaskInstance with the required model.

#### 2. Task Not Found

**HTTP 404**: Not Found

```json
{
  "detail": "Task task-xyz not found"
}
```

**Solution**: Verify the task_id is correct. Tasks may be cleaned from history after completion.

#### 3. Invalid UUID Format

**HTTP 200** with error status:

```json
{
  "status": "error",
  "message": "Invalid UUID format"
}
```

**Solution**: Ensure ti_uuid is a valid UUID string.

#### 4. Connection Failed

**HTTP 200** with error status:

```json
{
  "status": "error",
  "message": "Connection failed: Unable to reach host"
}
```

**Solution**: Verify the TaskInstance is running and accessible.

### Error Handling Best Practices

```python
import requests
from requests.exceptions import RequestException

def safe_submit_task(model_name, task_input):
    try:
        response = requests.post(
            "http://localhost:8102/queue/submit",
            json={
                "model_name": model_name,
                "task_input": task_input,
                "metadata": {}
            },
            timeout=30
        )

        # Check HTTP status
        if response.status_code == 503:
            print("No TaskInstances available")
            return None

        response.raise_for_status()

        data = response.json()

        # Check application-level status
        if data.get("status") == "error":
            print(f"Error: {data.get('message')}")
            return None

        return data.get("task_id")

    except RequestException as e:
        print(f"Network error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None
```

---

## Best Practices

### 1. Task Submission

✅ **DO**:
- Always include meaningful metadata for tracking
- Use appropriate timeouts (30-60 seconds)
- Handle 503 errors gracefully (retry with backoff)
- Validate task_input structure before submission

❌ **DON'T**:
- Submit tasks without error handling
- Assume immediate execution
- Ignore task_status when querying
- Submit extremely large payloads (>10MB)

### 2. Task Polling

✅ **DO**:
- Use exponential backoff for polling
- Set maximum poll attempts
- Cache task status to reduce requests
- Use webhooks/callbacks when available

```python
import time

def poll_with_backoff(task_id, max_attempts=20):
    delay = 1  # Start with 1 second
    for attempt in range(max_attempts):
        response = requests.get(
            f"http://localhost:8102/task/query?task_id={task_id}"
        )
        data = response.json()

        if data["task_status"] == "completed":
            return data["result"]

        time.sleep(delay)
        delay = min(delay * 1.5, 30)  # Max 30 seconds

    raise TimeoutError("Task did not complete in time")
```

### 3. Instance Management

✅ **DO**:
- Register instances at startup
- Remove instances gracefully on shutdown
- Monitor instance health regularly
- Keep instance registry synchronized

```python
class InstanceManager:
    def __init__(self, scheduler_url):
        self.scheduler_url = scheduler_url
        self.registered_instances = []

    def register_all(self, instances):
        for instance in instances:
            try:
                response = requests.post(
                    f"{self.scheduler_url}/ti/register",
                    json={
                        "host": instance["host"],
                        "port": instance["port"],
                        "model_name": instance["model_name"]
                    },
                    timeout=10
                )
                data = response.json()
                if data["status"] == "success":
                    # Store both UUID and address for removal
                    self.registered_instances.append({
                        "ti_uuid": data["ti_uuid"],
                        "host": instance["host"],
                        "port": instance["port"]
                    })
            except Exception as e:
                print(f"Failed to register {instance}: {e}")

    def cleanup(self):
        for instance in self.registered_instances:
            try:
                requests.post(
                    f"{self.scheduler_url}/ti/remove",
                    json={
                        "host": instance["host"],
                        "port": instance["port"]
                    },
                    timeout=5
                )
            except:
                pass
```

### 4. Load Balancing

The scheduler uses strategies to balance load:

- **ShortestQueue** (default): Selects instance with shortest expected wait
- **RoundRobin**: Distributes evenly across instances
- **Weighted**: Prioritizes based on instance capacity
- **Probabilistic**: Stochastic selection based on queue size

You don't need to implement load balancing - the scheduler handles it automatically.

### 5. Monitoring

Monitor these metrics:

```python
def get_scheduler_health():
    health = requests.get("http://localhost:8102/health").json()
    queues = requests.get("http://localhost:8102/queue/info").json()

    return {
        "scheduler_status": health["status"],
        "total_queues": len(queues["queues"]),
        "avg_wait_time": sum(q["waiting_time_expect"] for q in queues["queues"]) / len(queues["queues"]) if queues["queues"] else 0
    }
```

---

## Code Examples

### Complete Integration Example

```python
import requests
import time
from typing import Optional, Dict, Any

class SwarmPilotClient:
    """Complete client for SwarmPilot Scheduler"""

    def __init__(self, base_url: str = "http://localhost:8102"):
        self.base_url = base_url
        self.timeout = 30

    def health_check(self) -> bool:
        """Check if scheduler is healthy"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5
            )
            return response.json().get("status") == "healthy"
        except:
            return False

    def register_instance(self, host: str, port: int, model_name: str) -> Optional[str]:
        """Register a TaskInstance"""
        try:
            response = requests.post(
                f"{self.base_url}/ti/register",
                json={"host": host, "port": port, "model_name": model_name},
                timeout=self.timeout
            )
            data = response.json()
            if data["status"] == "success":
                return data["ti_uuid"]
        except Exception as e:
            print(f"Registration failed: {e}")
        return None

    def submit_task(
        self,
        model_name: str,
        task_input: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Submit a task for execution"""
        try:
            response = requests.post(
                f"{self.base_url}/queue/submit",
                json={
                    "model_name": model_name,
                    "task_input": task_input,
                    "metadata": metadata or {}
                },
                timeout=self.timeout
            )

            if response.status_code == 503:
                raise RuntimeError("No TaskInstances available")

            response.raise_for_status()
            return response.json()["task_id"]

        except Exception as e:
            print(f"Task submission failed: {e}")
            return None

    def query_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Query task status"""
        try:
            response = requests.get(
                f"{self.base_url}/task/query",
                params={"task_id": task_id},
                timeout=self.timeout
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()
            return response.json()

        except Exception as e:
            print(f"Task query failed: {e}")
            return None

    def wait_for_completion(
        self,
        task_id: str,
        max_wait: int = 300,
        poll_interval: float = 1.0
    ) -> Optional[Any]:
        """Wait for task to complete and return result"""
        start_time = time.time()

        while time.time() - start_time < max_wait:
            task_info = self.query_task(task_id)

            if not task_info:
                raise RuntimeError(f"Task {task_id} not found")

            if task_info["task_status"] == "completed":
                return task_info["result"]

            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.2, 5.0)  # Exponential backoff

        raise TimeoutError(f"Task {task_id} did not complete within {max_wait}s")

    def get_queue_info(self, model_name: Optional[str] = None) -> list:
        """Get queue information"""
        try:
            params = {"model_name": model_name} if model_name else {}
            response = requests.get(
                f"{self.base_url}/queue/info",
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()["queues"]
        except Exception as e:
            print(f"Failed to get queue info: {e}")
            return []


# Usage Example
if __name__ == "__main__":
    # Initialize client
    client = SwarmPilotClient()

    # Check health
    if not client.health_check():
        print("Scheduler is not healthy!")
        exit(1)

    # Register instances (if needed)
    ti_uuid = client.register_instance("localhost", 8100, "gpt-3.5-turbo")
    if ti_uuid:
        print(f"Registered instance: {ti_uuid}")

    # Submit task
    task_id = client.submit_task(
        model_name="gpt-3.5-turbo",
        task_input={
            "prompt": "What is machine learning?",
            "max_tokens": 100
        },
        metadata={"user_id": "user123"}
    )

    if task_id:
        print(f"Task submitted: {task_id}")

        # Wait for completion
        try:
            result = client.wait_for_completion(task_id, max_wait=60)
            print(f"Task result: {result}")
        except TimeoutError:
            print("Task timed out")
        except Exception as e:
            print(f"Error: {e}")
```

### Async Integration Example

```python
import asyncio
import aiohttp
from typing import Optional, Dict, Any

class AsyncSwarmPilotClient:
    """Async client for SwarmPilot Scheduler"""

    def __init__(self, base_url: str = "http://localhost:8102"):
        self.base_url = base_url
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def submit_task(
        self,
        session: aiohttp.ClientSession,
        model_name: str,
        task_input: Dict[str, Any]
    ) -> Optional[str]:
        """Submit task asynchronously"""
        try:
            async with session.post(
                f"{self.base_url}/queue/submit",
                json={
                    "model_name": model_name,
                    "task_input": task_input,
                    "metadata": {}
                },
                timeout=self.timeout
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["task_id"]
        except Exception as e:
            print(f"Submission failed: {e}")
        return None

    async def query_task(
        self,
        session: aiohttp.ClientSession,
        task_id: str
    ) -> Optional[Dict[str, Any]]:
        """Query task asynchronously"""
        try:
            async with session.get(
                f"{self.base_url}/task/query",
                params={"task_id": task_id},
                timeout=self.timeout
            ) as response:
                if response.status == 200:
                    return await response.json()
        except Exception as e:
            print(f"Query failed: {e}")
        return None

    async def submit_and_wait(
        self,
        model_name: str,
        task_input: Dict[str, Any],
        max_wait: int = 60
    ) -> Optional[Any]:
        """Submit task and wait for result"""
        async with aiohttp.ClientSession() as session:
            # Submit
            task_id = await self.submit_task(session, model_name, task_input)
            if not task_id:
                return None

            # Poll for completion
            start_time = asyncio.get_event_loop().time()
            poll_interval = 1.0

            while asyncio.get_event_loop().time() - start_time < max_wait:
                task_info = await self.query_task(session, task_id)

                if task_info and task_info["task_status"] == "completed":
                    return task_info["result"]

                await asyncio.sleep(poll_interval)
                poll_interval = min(poll_interval * 1.2, 5.0)

            return None


# Async usage example
async def main():
    client = AsyncSwarmPilotClient()

    # Submit multiple tasks concurrently
    tasks = [
        client.submit_and_wait(
            "gpt-3.5-turbo",
            {"prompt": f"Question {i}", "max_tokens": 50}
        )
        for i in range(10)
    ]

    results = await asyncio.gather(*tasks)
    print(f"Completed {len([r for r in results if r])} tasks")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Configuration

### Scheduler Configuration

The scheduler can be configured via:

1. **Environment Variables**:
   - `SCHEDULER_CONFIG_PATH`: Path to instance configuration file
   - `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

2. **Configuration File** (`config.yaml`):
```yaml
instances:
  - host: localhost
    port: 8100
  - host: localhost
    port: 8101
```

### Client Configuration

```python
# Configure client with custom settings
client = SwarmPilotClient(
    base_url="http://scheduler.example.com:8102"
)
client.timeout = 60  # Increase timeout for long-running tasks
```

---

## Troubleshooting

### Issue: Tasks Not Being Scheduled

**Symptoms**: Submit returns 503 error

**Solutions**:
1. Check if any TaskInstances are registered:
   ```bash
   curl http://localhost:8102/queue/info
   ```
2. Verify TaskInstance model_name matches your request
3. Check TaskInstance health and connectivity

### Issue: Task Status Stuck at "scheduled"

**Symptoms**: Task never reaches "completed" status

**Solutions**:
1. Check TaskInstance is processing tasks
2. Verify TaskInstance sends completion notifications
3. Check scheduler logs for errors

### Issue: Slow Response Times

**Symptoms**: API calls taking too long

**Solutions**:
1. Increase connection pool size
2. Use async client for concurrent requests
3. Monitor queue wait times via `/queue/info`
4. Add more TaskInstances

---

## Support and Resources

### Documentation
- [API Specification](Scheduler.md)
- [Development Guide](REFACTORING_PROGRESS.md)
- [Lookup Predictor](LOOKUP_PREDICTOR.md)

### Example Code
- [Basic Usage](../examples/basic_usage.py)
- [Custom Strategy](../examples/custom_strategy.py)

### GitHub
- Repository: [SwarmPilot GlobalQueue](https://github.com/yourorg/swarmpilot_globalqueue)
- Issues: Report bugs and request features

---

## Changelog

### v2.0.0 (2025-10-11)
- Complete architectural refactoring
- New TaskTracker for state management
- Multiple scheduling strategies
- Comprehensive REST API
- Full test coverage

---

## License

MIT License - See LICENSE file for details

---

**Last Updated**: 2025-10-11
**Document Version**: 2.0.0
