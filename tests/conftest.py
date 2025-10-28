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
    """Create a mock TaskInstance"""
    ti_uuid = uuid4()
    mock_client = Mock(spec=TaskInstanceClient)
    mock_client.base_url = "http://localhost:8100"

    # Default status response
    mock_client.get_status.return_value = InstanceStatusResponse(
        instance_id="test-instance-1",
        model_type="test_model",
        replicas_running=2,
        queue_size=0,
        status="running"
    )

    # Default prediction response
    mock_client.predict_queue.return_value = PredictResponse(
        expected_ms=100.0,
        error_ms=10.0,
        queue_size=0
    )

    # Default enqueue response
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
    """Create a scheduler with mock instances"""
    from src.scheduler import SwarmPilotScheduler

    scheduler = SwarmPilotScheduler()
    scheduler.taskinstances = [mock_task_instance]
    # Update strategy's taskinstances reference
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances
    return scheduler


@pytest.fixture
def fake_data_path():
    """Get fake data directory path"""
    from pathlib import Path
    # Path relative to project root
    project_root = Path(__file__).parent.parent
    fake_data_dir = project_root.parent / "swarmpilot_fake_predictor" / "fake_data"
    return str(fake_data_dir)


@pytest.fixture
def mock_task_instances_16():
    """Create 16 mock task instances for integration testing"""
    from tests.fixtures.mock_task_instance import create_mock_task_instance_client
    from src.scheduler.strategies import TaskInstance
    from uuid import uuid4

    instances = []
    mock_clients = []  # Keep references

    for i in range(16):
        port = 8100 + i
        host = "localhost"

        # Create mock client
        mock_client = create_mock_task_instance_client(
            host=host,
            port=port,
            model_name="fake_t2vid",
            replicas=1
        )
        mock_clients.append(mock_client)

        # Wrap in TaskInstance
        ti = TaskInstance(
            uuid=uuid4(),
            instance=mock_client,
            model_type="fake_t2vid"
        )

        # Set instance_id (normally set during registration)
        ti.instance_id = f"{host}:{port}"

        instances.append(ti)

    yield instances

    # Teardown: close all mock clients
    for mock_client in mock_clients:
        try:
            mock_client.close()
        except Exception:
            pass


@pytest.fixture
def scheduler_with_fake_data(fake_data_path):
    """Create scheduler with 16 mock instances and fake data enabled"""
    from src.scheduler import SwarmPilotScheduler
    from src.scheduler.strategies import TaskInstance
    from tests.fixtures.mock_task_instance import create_mock_task_instance_client
    from uuid import uuid4

    # Create scheduler with fake data bypass
    scheduler = SwarmPilotScheduler(
        get_debug_enabled=lambda: False,
        get_fake_data_enabled=lambda: True,
        get_fake_data_path=lambda: fake_data_path,
        get_probabilistic_quantiles=lambda: [0.25, 0.5, 0.75, 0.99],
        use_lockfree=True
    )

    # Directly create and add 16 TaskInstance objects
    mock_clients = []  # Keep references to prevent GC
    for i in range(16):
        port = 8100 + i
        host = "localhost"

        # Create mock client
        mock_client = create_mock_task_instance_client(
            host=host,
            port=port,
            model_name="fake_t2vid",
            replicas=1
        )
        mock_clients.append(mock_client)  # Keep reference

        # Create TaskInstance directly
        ti = TaskInstance(
            uuid=uuid4(),
            instance=mock_client,
            model_type="fake_t2vid"
        )

        # Set instance_id (normally set by add_task_instance)
        ti.instance_id = f"{host}:{port}"

        # Add to scheduler's taskinstances list
        scheduler.taskinstances.append(ti)

    # Update strategy's taskinstances reference
    if scheduler.strategy:
        scheduler.strategy.taskinstances = scheduler.taskinstances

    # Store mock_clients as attribute to keep them alive
    scheduler._test_mock_clients = mock_clients

    yield scheduler

    # Teardown: close all resources
    # 1. Stop async scheduler manager if it's running
    try:
        if hasattr(scheduler, 'async_scheduler_manager') and scheduler.async_scheduler_manager is not None:
            scheduler.async_scheduler_manager.stop(timeout=5.0)
    except Exception:
        pass  # Ignore errors during cleanup

    # 2. Shutdown task tracker (stops background cleanup thread)
    try:
        if hasattr(scheduler, 'task_tracker') and scheduler.task_tracker is not None:
            if hasattr(scheduler.task_tracker, 'shutdown'):
                scheduler.task_tracker.shutdown()
    except Exception:
        pass  # Ignore errors during cleanup

    # 3. Shutdown thread pool executor
    try:
        if hasattr(scheduler, 'executor') and scheduler.executor is not None:
            scheduler.executor.shutdown(wait=True, cancel_futures=True)
    except Exception:
        pass  # Ignore errors during cleanup

    # 4. Close strategy's predictor client if it exists
    try:
        if hasattr(scheduler.strategy, 'predictor_client'):
            scheduler.strategy.predictor_client.close()
    except Exception:
        pass  # Ignore errors during cleanup

    # 5. Close all mock clients to release resources
    for mock_client in mock_clients:
        try:
            mock_client.close()
        except Exception:
            pass  # Ignore errors during cleanup
