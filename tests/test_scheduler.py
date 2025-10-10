#!/usr/bin/env python3
"""
Unit tests for the Scheduler /schedule API

Tests the SwarmPilotScheduler.schedule() method and the /schedule endpoint
with various scenarios using mocked TaskInstance clients.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from uuid import uuid4, UUID
from typing import Dict, Any

from scheduler import SwarmPilotScheduler, SchedulerRequest, SchedulerResponse
from task_instance_client_refactored import (
    TaskInstanceClient,
    InstanceStatusResponse,
    EnqueueResponse,
    PredictResponse,
    QueueStatusResponse
)
from strategy_refactored import (
    TaskInstance,
    ShortestQueueStrategy,
    RoundRobinStrategy,
    WeightedStrategy
)


# ========== Test Fixtures ==========

@pytest.fixture
def mock_task_instance():
    """Create a mock TaskInstance with a mocked client"""
    ti_uuid = uuid4()
    mock_client = Mock(spec=TaskInstanceClient)
    mock_client.base_url = "http://localhost:8100"

    # Default status response
    mock_client.get_status.return_value = InstanceStatusResponse(
        instance_id="test-instance-1",
        model_type="tx_det_dummy",
        replicas_running=2,
        queue_size=0,
        status="running"
    )

    # Default predict response
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

    return TaskInstance(uuid=ti_uuid, instance=mock_client)


@pytest.fixture
def scheduler_with_instances(mock_task_instance):
    """Create a scheduler with mock task instances"""
    scheduler = SwarmPilotScheduler()
    scheduler.taskinstances = [mock_task_instance]
    return scheduler


@pytest.fixture
def scheduler_with_multiple_instances():
    """Create a scheduler with multiple mock task instances"""
    scheduler = SwarmPilotScheduler()

    # Instance 1: Lower queue (should be selected by shortest_queue)
    ti1_uuid = uuid4()
    mock_client1 = Mock(spec=TaskInstanceClient)
    mock_client1.base_url = "http://localhost:8100"
    mock_client1.get_status.return_value = InstanceStatusResponse(
        instance_id="instance-1",
        model_type="tx_det_dummy",
        replicas_running=2,
        queue_size=2,
        status="running"
    )
    mock_client1.predict_queue.return_value = PredictResponse(
        expected_ms=50.0,
        error_ms=5.0,
        queue_size=2
    )
    mock_client1.enqueue_task.return_value = EnqueueResponse(
        task_id="task-1",
        queue_size=3,
        enqueue_time=1234567890.0
    )

    # Instance 2: Higher queue
    ti2_uuid = uuid4()
    mock_client2 = Mock(spec=TaskInstanceClient)
    mock_client2.base_url = "http://localhost:8101"
    mock_client2.get_status.return_value = InstanceStatusResponse(
        instance_id="instance-2",
        model_type="tx_det_dummy",
        replicas_running=2,
        queue_size=5,
        status="running"
    )
    mock_client2.predict_queue.return_value = PredictResponse(
        expected_ms=150.0,
        error_ms=15.0,
        queue_size=5
    )
    mock_client2.enqueue_task.return_value = EnqueueResponse(
        task_id="task-2",
        queue_size=6,
        enqueue_time=1234567891.0
    )

    # Instance 3: Medium queue
    ti3_uuid = uuid4()
    mock_client3 = Mock(spec=TaskInstanceClient)
    mock_client3.base_url = "http://localhost:8102"
    mock_client3.get_status.return_value = InstanceStatusResponse(
        instance_id="instance-3",
        model_type="tx_det_dummy",
        replicas_running=2,
        queue_size=3,
        status="running"
    )
    mock_client3.predict_queue.return_value = PredictResponse(
        expected_ms=100.0,
        error_ms=10.0,
        queue_size=3
    )
    mock_client3.enqueue_task.return_value = EnqueueResponse(
        task_id="task-3",
        queue_size=4,
        enqueue_time=1234567892.0
    )

    scheduler.taskinstances = [
        TaskInstance(uuid=ti1_uuid, instance=mock_client1),
        TaskInstance(uuid=ti2_uuid, instance=mock_client2),
        TaskInstance(uuid=ti3_uuid, instance=mock_client3)
    ]

    return scheduler


# ========== Basic Functionality Tests ==========

def test_schedule_success(scheduler_with_instances):
    """Test successful task scheduling"""
    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"},
        metadata={"priority": "high"}
    )

    response = scheduler_with_instances.schedule(request)

    # Verify response structure
    assert isinstance(response, SchedulerResponse)
    assert response.task_id == "task-123"
    assert response.model_type == "tx_det_dummy"
    assert response.queue_size == 1
    assert response.instance_url == "http://localhost:8100"

    # Verify enqueue was called with correct parameters
    mock_client = scheduler_with_instances.taskinstances[0].instance
    mock_client.enqueue_task.assert_called_once_with(
        input_data={"image": "test.jpg"},
        metadata={"priority": "high"}
    )


def test_schedule_no_instances():
    """Test scheduling when no instances are configured"""
    scheduler = SwarmPilotScheduler()

    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    with pytest.raises(RuntimeError, match="No TaskInstances configured"):
        scheduler.schedule(request)


def test_schedule_no_matching_model_type(scheduler_with_instances):
    """Test scheduling when no instance supports the requested model type"""
    # Set the instance to support a different model type
    mock_client = scheduler_with_instances.taskinstances[0].instance
    mock_client.get_status.return_value = InstanceStatusResponse(
        instance_id="test-instance-1",
        model_type="different_model",
        replicas_running=2,
        queue_size=0,
        status="running"
    )

    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    with pytest.raises(RuntimeError, match="No available instances for model type tx_det_dummy"):
        scheduler_with_instances.schedule(request)


def test_schedule_instance_with_no_replicas(scheduler_with_instances):
    """Test scheduling when instance has no running replicas"""
    mock_client = scheduler_with_instances.taskinstances[0].instance
    mock_client.get_status.return_value = InstanceStatusResponse(
        instance_id="test-instance-1",
        model_type="tx_det_dummy",
        replicas_running=0,  # No running replicas
        queue_size=0,
        status="idle"
    )

    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    with pytest.raises(RuntimeError, match="No available instances for model type tx_det_dummy"):
        scheduler_with_instances.schedule(request)


def test_schedule_enqueue_failure(scheduler_with_instances):
    """Test handling of enqueue failures"""
    mock_client = scheduler_with_instances.taskinstances[0].instance
    mock_client.enqueue_task.side_effect = Exception("Connection failed")

    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    with pytest.raises(RuntimeError, match="Failed to schedule task"):
        scheduler_with_instances.schedule(request)


def test_schedule_saves_routing_info(scheduler_with_instances):
    """Test that routing information is properly saved"""
    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"},
        request_id="req-123"
    )

    scheduler_with_instances.schedule(request)

    routing_info = scheduler_with_instances.get_last_routing_info()

    assert routing_info["request_id"] == "req-123"
    assert routing_info["task_id"] == "task-123"
    assert routing_info["model_type"] == "tx_det_dummy"
    assert routing_info["instance_url"] == "http://localhost:8100"
    assert "instance_uuid" in routing_info
    assert "expected_ms" in routing_info
    assert "queue_size_before" in routing_info


def test_schedule_generates_request_id_if_missing(scheduler_with_instances):
    """Test that request_id is auto-generated if not provided"""
    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    assert request.request_id is None

    scheduler_with_instances.schedule(request)

    # After scheduling, routing info should have a generated request_id
    routing_info = scheduler_with_instances.get_last_routing_info()
    assert routing_info["request_id"] is not None
    assert isinstance(routing_info["request_id"], str)


# ========== Strategy-Specific Tests ==========

def test_schedule_with_shortest_queue_strategy(scheduler_with_multiple_instances):
    """Test scheduling with shortest queue strategy"""
    scheduler_with_multiple_instances.set_strategy("shortest_queue")

    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    response = scheduler_with_multiple_instances.schedule(request)

    # Should select instance 1 (expected_ms=50.0, lowest)
    assert response.task_id == "task-1"
    assert response.instance_url == "http://localhost:8100"


def test_schedule_with_round_robin_strategy(scheduler_with_multiple_instances):
    """Test scheduling with round-robin strategy"""
    scheduler_with_multiple_instances.set_strategy("round_robin")

    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    # First request should go to instance at index 0
    response1 = scheduler_with_multiple_instances.schedule(request)

    # Second request should go to instance at index 1
    response2 = scheduler_with_multiple_instances.schedule(request)

    # Third request should go to instance at index 2
    response3 = scheduler_with_multiple_instances.schedule(request)

    # Fourth request should wrap around to index 0
    response4 = scheduler_with_multiple_instances.schedule(request)

    # Verify round-robin behavior
    assert response1.instance_url == "http://localhost:8100"
    assert response2.instance_url == "http://localhost:8101"
    assert response3.instance_url == "http://localhost:8102"
    assert response4.instance_url == "http://localhost:8100"


def test_schedule_with_weighted_strategy(scheduler_with_multiple_instances):
    """Test scheduling with weighted strategy"""
    scheduler_with_multiple_instances.set_strategy("weighted")

    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    response = scheduler_with_multiple_instances.schedule(request)

    # With default error_weight=0.5, instance 1 should still be selected:
    # Instance 1: 50 + 0.5*5 = 52.5
    # Instance 2: 150 + 0.5*15 = 157.5
    # Instance 3: 100 + 0.5*10 = 105.0
    assert response.task_id == "task-1"
    assert response.instance_url == "http://localhost:8100"


def test_set_strategy_invalid():
    """Test setting an invalid strategy"""
    scheduler = SwarmPilotScheduler()

    with pytest.raises(ValueError, match="Unknown strategy"):
        scheduler.set_strategy("invalid_strategy")


# ========== Edge Cases ==========

def test_schedule_with_mixed_model_types():
    """Test scheduling when instances support different model types"""
    scheduler = SwarmPilotScheduler()

    # Instance 1: supports tx_det_dummy
    ti1_uuid = uuid4()
    mock_client1 = Mock(spec=TaskInstanceClient)
    mock_client1.base_url = "http://localhost:8100"
    mock_client1.get_status.return_value = InstanceStatusResponse(
        instance_id="instance-1",
        model_type="tx_det_dummy",
        replicas_running=2,
        queue_size=0,
        status="running"
    )
    mock_client1.predict_queue.return_value = PredictResponse(
        expected_ms=50.0, error_ms=5.0, queue_size=0
    )
    mock_client1.enqueue_task.return_value = EnqueueResponse(
        task_id="task-1", queue_size=1, enqueue_time=1234567890.0
    )

    # Instance 2: supports easyocr
    ti2_uuid = uuid4()
    mock_client2 = Mock(spec=TaskInstanceClient)
    mock_client2.base_url = "http://localhost:8101"
    mock_client2.get_status.return_value = InstanceStatusResponse(
        instance_id="instance-2",
        model_type="easyocr",
        replicas_running=2,
        queue_size=0,
        status="running"
    )
    mock_client2.predict_queue.return_value = PredictResponse(
        expected_ms=100.0, error_ms=10.0, queue_size=0
    )
    mock_client2.enqueue_task.return_value = EnqueueResponse(
        task_id="task-2", queue_size=1, enqueue_time=1234567891.0
    )

    scheduler.taskinstances = [
        TaskInstance(uuid=ti1_uuid, instance=mock_client1),
        TaskInstance(uuid=ti2_uuid, instance=mock_client2)
    ]

    # Request for tx_det_dummy should go to instance 1
    request1 = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )
    response1 = scheduler.schedule(request1)
    assert response1.instance_url == "http://localhost:8100"

    # Request for easyocr should go to instance 2
    request2 = SchedulerRequest(
        model_type="easyocr",
        input_data={"image": "test.jpg"}
    )
    response2 = scheduler.schedule(request2)
    assert response2.instance_url == "http://localhost:8101"


def test_schedule_with_instance_status_error(scheduler_with_multiple_instances):
    """Test scheduling when one instance fails to respond to status check"""
    # Make instance 1 fail status check
    mock_client1 = scheduler_with_multiple_instances.taskinstances[0].instance
    mock_client1.get_status.side_effect = Exception("Connection timeout")

    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    response = scheduler_with_multiple_instances.schedule(request)

    # Should still succeed by using other available instances
    # Instance 2 has higher expected_ms, but instance 1 failed, so instance 3 should be selected
    # Actually, shortest queue will select instance 3 (100ms) over instance 2 (150ms)
    assert response.instance_url in ["http://localhost:8101", "http://localhost:8102"]
    assert response.model_type == "tx_det_dummy"


def test_schedule_empty_input_data(scheduler_with_instances):
    """Test scheduling with empty input data"""
    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={},
        metadata={}
    )

    response = scheduler_with_instances.schedule(request)

    assert isinstance(response, SchedulerResponse)
    assert response.task_id == "task-123"

    # Verify enqueue was called with empty data
    mock_client = scheduler_with_instances.taskinstances[0].instance
    mock_client.enqueue_task.assert_called_once_with(
        input_data={},
        metadata={}
    )


def test_schedule_large_queue(scheduler_with_instances):
    """Test scheduling when queue has many items"""
    mock_client = scheduler_with_instances.taskinstances[0].instance
    mock_client.get_status.return_value = InstanceStatusResponse(
        instance_id="test-instance-1",
        model_type="tx_det_dummy",
        replicas_running=2,
        queue_size=1000,  # Large queue
        status="running"
    )
    mock_client.predict_queue.return_value = PredictResponse(
        expected_ms=50000.0,  # 50 seconds
        error_ms=5000.0,
        queue_size=1000
    )

    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    response = scheduler_with_instances.schedule(request)

    # Should still successfully schedule
    assert isinstance(response, SchedulerResponse)
    assert response.task_id == "task-123"


# ========== Integration with API Models Tests ==========

def test_scheduler_request_validation():
    """Test SchedulerRequest validation"""
    # Valid request
    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"key": "value"}
    )
    assert request.model_type == "tx_det_dummy"
    assert request.input_data == {"key": "value"}
    assert request.metadata == {}

    # Request with metadata
    request_with_metadata = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"key": "value"},
        metadata={"priority": "high"}
    )
    assert request_with_metadata.metadata == {"priority": "high"}


def test_scheduler_response_structure(scheduler_with_instances):
    """Test that SchedulerResponse has all required fields"""
    request = SchedulerRequest(
        model_type="tx_det_dummy",
        input_data={"image": "test.jpg"}
    )

    response = scheduler_with_instances.schedule(request)

    # Verify all required fields are present
    assert hasattr(response, 'task_id')
    assert hasattr(response, 'instance_id')
    assert hasattr(response, 'instance_url')
    assert hasattr(response, 'model_type')
    assert hasattr(response, 'queue_size')

    # Verify field types
    assert isinstance(response.task_id, str)
    assert isinstance(response.instance_id, str)
    assert isinstance(response.instance_url, str)
    assert isinstance(response.model_type, str)
    assert isinstance(response.queue_size, int)


# ========== Run Tests ==========

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
