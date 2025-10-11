"""
API Endpoint Unit Tests

Tests for FastAPI endpoints using TestClient
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from uuid import uuid4

from src.scheduler.api import app, scheduler
from src.scheduler.models import TaskStatus


@pytest.fixture
def client():
    """Create a test client"""
    return TestClient(app)


@pytest.fixture
def reset_scheduler():
    """Reset scheduler state before each test"""
    scheduler.taskinstances = []
    scheduler.task_tracker = type(scheduler.task_tracker)()
    # Reset strategy to use the current taskinstances list
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances
    yield
    scheduler.taskinstances = []
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances


def test_health_check(client):
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "scheduler"
    assert data["version"] == "2.0.0"


def test_register_task_instance_success(client, reset_scheduler):
    """Test successful task instance registration"""
    with patch('src.scheduler.core.TaskInstanceClient'):
        response = client.post("/ti/register", json={
            "host": "localhost",
            "port": 8100,
            "model_name": "test_model"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "ti_uuid" in data
        assert data["ti_uuid"] != ""


def test_register_task_instance_error(client, reset_scheduler):
    """Test task instance registration with error"""
    with patch('src.scheduler.core.TaskInstanceClient', side_effect=Exception("Connection failed")):
        response = client.post("/ti/register", json={
            "host": "invalid_host",
            "port": 8100,
            "model_name": "test_model"
        })

        assert response.status_code == 200  # API returns 200 with error status
        data = response.json()
        assert data["status"] == "error"
        assert "Connection failed" in data["message"]


def test_remove_task_instance_success(client, reset_scheduler):
    """Test successful task instance removal"""
    # First register an instance
    with patch('src.scheduler.core.TaskInstanceClient') as mock_client_class:
        # Setup mock to have base_url attribute
        mock_client = Mock()
        mock_client.base_url = "http://localhost:8100"
        mock_client_class.return_value = mock_client

        reg_response = client.post("/ti/register", json={
            "host": "localhost",
            "port": 8100,
            "model_name": "test_model"
        })
        assert reg_response.json()["status"] == "success"

        # Now remove it using host and port
        response = client.post("/ti/remove", json={
            "host": "localhost",
            "port": 8100
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["host"] == "localhost"
        assert data["port"] == 8100
        assert data["ti_uuid"] is not None


def test_remove_task_instance_not_found(client, reset_scheduler):
    """Test removing non-existent task instance"""
    response = client.post("/ti/remove", json={
        "host": "nonexistent",
        "port": 9999
    })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "not found" in data["message"]
    assert data["host"] == "nonexistent"
    assert data["port"] == 9999


def test_submit_task_success(client, reset_scheduler, mock_task_instance):
    """Test successful task submission"""
    # Add a mock instance to scheduler
    scheduler.taskinstances = [mock_task_instance]
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances

    response = client.post("/queue/submit", json={
        "model_name": "test_model",
        "task_input": {"prompt": "Hello"},
        "metadata": {"user": "test"}
    })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "task_id" in data
    assert "scheduled_ti" in data


def test_submit_task_no_instances(client, reset_scheduler):
    """Test task submission with no instances"""
    response = client.post("/queue/submit", json={
        "model_name": "test_model",
        "task_input": {"prompt": "Hello"},
        "metadata": {}
    })

    assert response.status_code == 503  # Service Unavailable
    assert "No TaskInstances configured" in response.json()["detail"]


def test_get_queue_info_empty(client, reset_scheduler):
    """Test getting queue info with no instances"""
    response = client.get("/queue/info")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["queues"] == []


def test_get_queue_info_with_instances(client, reset_scheduler, mock_task_instance):
    """Test getting queue info with instances"""
    scheduler.taskinstances = [mock_task_instance]
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances

    response = client.get("/queue/info")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["queues"]) == 1
    assert data["queues"][0]["model_name"] == "test_model"


def test_get_queue_info_filter_by_model(client, reset_scheduler, mock_task_instance):
    """Test getting queue info filtered by model name"""
    scheduler.taskinstances = [mock_task_instance]
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances

    # Query with matching model
    response = client.get("/queue/info?model_name=test_model")
    assert response.status_code == 200
    data = response.json()
    assert len(data["queues"]) == 1

    # Query with non-matching model
    response = client.get("/queue/info?model_name=other_model")
    assert response.status_code == 200
    data = response.json()
    assert len(data["queues"]) == 0


def test_query_task_success(client, reset_scheduler, mock_task_instance):
    """Test successful task query"""
    # Submit a task first
    scheduler.taskinstances = [mock_task_instance]
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances

    submit_response = client.post("/queue/submit", json={
        "model_name": "test_model",
        "task_input": {"prompt": "Hello"},
        "metadata": {}
    })
    task_id = submit_response.json()["task_id"]

    # Query the task
    response = client.get(f"/task/query?task_id={task_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == task_id
    assert data["task_status"] in ["queued", "scheduled", "running", "completed"]
    assert "scheduled_ti" in data
    assert "submit_time" in data


def test_query_task_not_found(client, reset_scheduler):
    """Test querying non-existent task"""
    response = client.get("/task/query?task_id=nonexistent-task")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_notify_task_completion_success(client, reset_scheduler, mock_task_instance):
    """Test task completion notification"""
    # Submit a task first
    scheduler.taskinstances = [mock_task_instance]
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances

    submit_response = client.post("/queue/submit", json={
        "model_name": "test_model",
        "task_input": {"prompt": "Hello"},
        "metadata": {}
    })
    task_id = submit_response.json()["task_id"]

    # Send completion notification
    response = client.post("/notify/task_complete", json={
        "task_id": task_id,
        "instance_id": "test-instance-1",
        "execution_time": 50.0,
        "result": {"output": "done"}
    })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "total_time_ms" in data


def test_notify_task_completion_unknown_instance(client, reset_scheduler):
    """Test completion notification for unknown instance"""
    response = client.post("/notify/task_complete", json={
        "task_id": "task-123",
        "instance_id": "unknown-instance",
        "execution_time": 50.0,
        "result": {"output": "done"}
    })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "warning"
    assert "not found" in data["message"]


def test_api_workflow_integration(client, reset_scheduler):
    """Test complete API workflow"""
    from src.scheduler.models import InstanceStatusResponse

    with patch('src.scheduler.core.TaskInstanceClient') as mock_client_class:
        mock_client = Mock()
        mock_client.base_url = "http://localhost:8100"  # Add base_url for removal test
        mock_client.get_status.return_value = InstanceStatusResponse(
            instance_id="test-instance",
            model_type="test_model",
            replicas_running=1,
            queue_size=0,
            status="running"
        )
        mock_client_class.return_value = mock_client

        # 1. Register an instance
        reg_response = client.post("/ti/register", json={
            "host": "localhost",
            "port": 8100,
            "model_name": "test_model"
        })
        assert reg_response.status_code == 200

        # 2. Check queue info
        queue_response = client.get("/queue/info")
        assert queue_response.status_code == 200

        # 3. Remove the instance using host and port
        remove_response = client.post("/ti/remove", json={
            "host": "localhost",
            "port": 8100
        })
        assert remove_response.status_code == 200
        assert remove_response.json()["status"] == "success"


def test_concurrent_task_submissions(client, reset_scheduler, mock_task_instance):
    """Test multiple concurrent task submissions"""
    scheduler.taskinstances = [mock_task_instance]
    # Update strategy's taskinstances reference
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances

    task_ids = []
    for i in range(5):
        response = client.post("/queue/submit", json={
            "model_name": "test_model",
            "task_input": {"prompt": f"Test {i}"},
            "metadata": {"index": i}
        })
        assert response.status_code == 200
        task_ids.append(response.json()["task_id"])

    # All tasks should be queryable
    for task_id in task_ids:
        response = client.get(f"/task/query?task_id={task_id}")
        assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
