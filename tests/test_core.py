"""
Core Scheduler Unit Tests

Tests for SwarmPilotScheduler functionality
"""

import pytest
from unittest.mock import Mock
from uuid import uuid4

from src.scheduler import SwarmPilotScheduler
from src.scheduler.models import SchedulerRequest, TaskStatus
from src.scheduler.strategies import (
    ShortestQueueStrategy,
    RoundRobinStrategy,
    WeightedStrategy,
    ProbabilisticQueueStrategy
)


def test_schedule_success(scheduler_with_instances):
    """Test successful task scheduling"""
    request = SchedulerRequest(
        model_type="test_model",
        input_data={"prompt": "test"},
        metadata={}
    )

    response = scheduler_with_instances.schedule(request)

    assert response.task_id == "task-123"
    assert response.model_type == "test_model"
    assert response.instance_id is not None


def test_schedule_no_instances():
    """Test scheduling with no instances configured"""
    scheduler = SwarmPilotScheduler()

    request = SchedulerRequest(
        model_type="test_model",
        input_data={"prompt": "test"},
        metadata={}
    )

    with pytest.raises(RuntimeError, match="No TaskInstances configured"):
        scheduler.schedule(request)


def test_schedule_with_metadata(scheduler_with_instances):
    """Test scheduling with metadata"""
    request = SchedulerRequest(
        model_type="test_model",
        input_data={"prompt": "test"},
        metadata={"user": "test_user", "priority": "high"}
    )

    response = scheduler_with_instances.schedule(request)

    assert response.task_id == "task-123"
    # Verify task is tracked
    task_info = scheduler_with_instances.task_tracker.get_task_info(response.task_id)
    assert task_info is not None
    assert task_info.task_status == TaskStatus.SCHEDULED


def test_add_task_instance():
    """Test adding a task instance"""
    scheduler = SwarmPilotScheduler()

    # Mock the client creation
    from unittest.mock import patch
    with patch('src.scheduler.core.TaskInstanceClient') as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        ti_uuid = scheduler.add_task_instance("http://localhost:8100")

        assert ti_uuid is not None
        assert len(scheduler.taskinstances) == 1
        mock_client_class.assert_called_once_with("http://localhost:8100")


def test_remove_task_instance():
    """Test removing a task instance"""
    scheduler = SwarmPilotScheduler()

    # Add an instance first
    from unittest.mock import patch
    with patch('src.scheduler.core.TaskInstanceClient'):
        ti_uuid = scheduler.add_task_instance("http://localhost:8100")

        # Remove it
        result = scheduler.remove_task_instance(ti_uuid)

        assert result is True
        assert len(scheduler.taskinstances) == 0


def test_remove_nonexistent_instance():
    """Test removing non-existent instance"""
    scheduler = SwarmPilotScheduler()
    fake_uuid = uuid4()

    result = scheduler.remove_task_instance(fake_uuid)

    assert result is False


def test_strategy_switching(scheduler_with_instances):
    """Test switching between strategies"""
    scheduler = scheduler_with_instances

    # Default strategy
    assert scheduler.strategy is not None

    # Switch to RoundRobin
    scheduler.set_strategy("round_robin")
    assert isinstance(scheduler.strategy, RoundRobinStrategy)

    # Switch to Weighted
    scheduler.set_strategy("weighted")
    assert isinstance(scheduler.strategy, WeightedStrategy)

    # Switch to Probabilistic
    scheduler.set_strategy("probabilistic")
    assert isinstance(scheduler.strategy, ProbabilisticQueueStrategy)

    # Switch to ShortestQueue
    scheduler.set_strategy("shortest_queue")
    assert isinstance(scheduler.strategy, ShortestQueueStrategy)


def test_invalid_strategy():
    """Test setting invalid strategy"""
    scheduler = SwarmPilotScheduler()

    with pytest.raises(ValueError, match="Unknown strategy"):
        scheduler.set_strategy("invalid_strategy")


def test_handle_task_completion(scheduler_with_instances):
    """Test handling task completion"""
    scheduler = scheduler_with_instances

    # First schedule a task
    request = SchedulerRequest(
        model_type="test_model",
        input_data={"prompt": "test"},
        metadata={}
    )
    response = scheduler.schedule(request)
    task_id = response.task_id

    # Get the instance UUID
    task_info = scheduler.task_tracker.get_task_info(task_id)
    instance_uuid = task_info.scheduled_ti

    # Complete the task
    execution_time = 50.0
    total_time = scheduler.handle_task_completion(
        task_id=task_id,
        instance_uuid=instance_uuid,
        execution_time=execution_time
    )

    # Verify task is marked as completed
    task_info = scheduler.task_tracker.get_task_info(task_id)
    assert task_info.task_status == TaskStatus.COMPLETED

    # Total time should be positive
    assert total_time is not None
    assert total_time > 0


def test_get_instance_statuses(scheduler_with_instances):
    """Test getting all instance statuses"""
    scheduler = scheduler_with_instances

    statuses = scheduler.get_instance_statuses()

    assert len(statuses) == 1
    assert statuses[0]["uuid"] is not None
    assert statuses[0]["model_type"] == "test_model"
    assert statuses[0]["queue_size"] == 0
    assert statuses[0]["status"] == "running"


def test_get_instance_statuses_with_error():
    """Test getting instance statuses when one instance has an error"""
    scheduler = SwarmPilotScheduler()

    # Create two mock instances
    from unittest.mock import patch
    with patch('src.scheduler.core.TaskInstanceClient') as mock_client_class:
        # First instance - working
        mock_client1 = Mock()
        mock_client1.get_status.return_value = Mock(
            instance_id="test-1",
            model_type="test_model",
            queue_size=0,
            status="running"
        )

        # Second instance - error
        mock_client2 = Mock()
        mock_client2.get_status.side_effect = Exception("Connection failed")

        mock_client_class.side_effect = [mock_client1, mock_client2]

        scheduler.add_task_instance("http://localhost:8100")
        scheduler.add_task_instance("http://localhost:8101")

        statuses = scheduler.get_instance_statuses()

        # Should have 2 statuses
        assert len(statuses) == 2

        # First should be successful
        assert statuses[0]["status"] == "running"

        # Second should show error
        assert statuses[1]["status"] == "error"


def test_load_task_instances_from_config(tmp_path):
    """Test loading task instances from config file"""
    import yaml

    # Create a config file
    config_data = {
        "instances": [
            {"host": "localhost", "port": 8100},
            {"host": "localhost", "port": 8101}
        ]
    }

    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # Load config
    scheduler = SwarmPilotScheduler()

    from unittest.mock import patch
    with patch('src.scheduler.core.TaskInstanceClient'):
        scheduler.load_task_instances_from_config(str(config_file))

        assert len(scheduler.taskinstances) == 2


def test_schedule_updates_task_tracker(scheduler_with_instances):
    """Test that scheduling updates the task tracker"""
    scheduler = scheduler_with_instances

    request = SchedulerRequest(
        model_type="test_model",
        input_data={"prompt": "test"},
        metadata={}
    )

    response = scheduler.schedule(request)

    # Check task is in tracker
    task_info = scheduler.task_tracker.get_task_info(response.task_id)
    assert task_info is not None
    assert task_info.task_id == response.task_id
    assert task_info.model_name == "test_model"
    assert task_info.task_status == TaskStatus.SCHEDULED


def test_multiple_schedules(scheduler_with_instances):
    """Test scheduling multiple tasks"""
    scheduler = scheduler_with_instances

    task_ids = []
    for i in range(5):
        request = SchedulerRequest(
            model_type="test_model",
            input_data={"prompt": f"test {i}"},
            metadata={"index": i}
        )
        response = scheduler.schedule(request)
        task_ids.append(response.task_id)

    # All tasks should be tracked
    for task_id in task_ids:
        task_info = scheduler.task_tracker.get_task_info(task_id)
        assert task_info is not None
        assert task_info.task_status == TaskStatus.SCHEDULED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
