"""
Pytest configuration file

Adds the parent directory to sys.path so that tests can import
modules from the project root.
"""
import sys
from pathlib import Path

# Add the parent directory to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import pytest and fixtures for Phase 2 tests
import pytest
from unittest.mock import Mock
from uuid import uuid4

from src.scheduler.client import TaskInstanceClient
from src.scheduler.strategies import TaskInstance
from src.scheduler.models import (
    InstanceStatusResponse,
    EnqueueResponse,
    PredictResponse
)


@pytest.fixture
def mock_task_instance():
    """创建一个 mock TaskInstance"""
    ti_uuid = uuid4()
    mock_client = Mock(spec=TaskInstanceClient)
    mock_client.base_url = "http://localhost:8100"

    # 默认状态响应
    mock_client.get_status.return_value = InstanceStatusResponse(
        instance_id="test-instance-1",
        model_type="test_model",
        replicas_running=2,
        queue_size=0,
        status="running"
    )

    # 默认预测响应
    mock_client.predict_queue.return_value = PredictResponse(
        expected_ms=100.0,
        error_ms=10.0,
        queue_size=0
    )

    # 默认入队响应
    mock_client.enqueue_task.return_value = EnqueueResponse(
        task_id="task-123",
        queue_size=1,
        enqueue_time=1234567890.0
    )

    # Create TaskInstance with model_type set
    ti = TaskInstance(uuid=ti_uuid, instance=mock_client, model_type="test_model")
    return ti


@pytest.fixture
def scheduler_with_instances(mock_task_instance):
    """创建一个带有 mock 实例的调度器"""
    from src.scheduler import SwarmPilotScheduler

    scheduler = SwarmPilotScheduler()
    scheduler.taskinstances = [mock_task_instance]
    # Update strategy's taskinstances reference
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances
    return scheduler
