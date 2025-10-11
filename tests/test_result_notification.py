"""
Integration test for result notification from TaskInstance to Scheduler

This test verifies that TaskInstance can successfully notify Scheduler
about task completions and that the Scheduler updates queue state accordingly.
"""

import pytest
from uuid import uuid4
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from scheduler import SwarmPilotScheduler
from strategy_refactored import (
    ShortestQueueStrategy,
    TaskInstance,
    QueueState
)
from task_instance_client_refactored import TaskInstanceClient


class TestResultNotification:
    """Test result notification integration"""

    def test_scheduler_notification_endpoint(self):
        """Test that Scheduler can receive and process task completion notifications"""
        # Create scheduler with ShortestQueueStrategy
        scheduler = SwarmPilotScheduler()

        # Create mock TaskInstance
        mock_client = Mock(spec=TaskInstanceClient)
        mock_client.base_url = "http://localhost:8101"

        # Mock status response
        status_mock = Mock()
        status_mock.instance_id = "ti-12345"
        status_mock.model_type = "tx_det_dummy"
        status_mock.replicas_running = 1
        status_mock.queue_size = 0
        status_mock.status = "running"
        mock_client.get_status.return_value = status_mock

        ti_uuid = uuid4()
        task_instance = TaskInstance(uuid=ti_uuid, instance=mock_client)

        # Add to scheduler
        scheduler.taskinstances.append(task_instance)

        # Set strategy to ShortestQueueStrategy
        strategy = ShortestQueueStrategy(
            taskinstances=scheduler.taskinstances,
            predictor_url="http://localhost:8100"
        )
        scheduler.strategy = strategy

        # Initialize queue state (override default)
        strategy.queue_states[ti_uuid] = QueueState(
            expected_ms=100.0,
            error_ms=10.0,
            task_count=1
        )

        # Simulate task completion notification
        # In real scenario, this would come from TaskInstance via HTTP POST
        initial_expected = strategy.queue_states[ti_uuid].expected_ms
        execution_time = 45.0  # 45ms actual execution

        # Call update_queue_on_completion (this is what the API endpoint calls)
        strategy.update_queue_on_completion(
            instance_uuid=ti_uuid,
            execution_time=execution_time
        )

        # Verify queue state was updated
        queue_state = strategy.queue_states[ti_uuid]
        expected_new = max(0.0, initial_expected - execution_time)

        assert queue_state.expected_ms == expected_new
        assert queue_state.task_count == 0
        # Error should remain unchanged
        assert queue_state.error_ms == 10.0

    def test_scheduler_notification_with_truncation(self):
        """Test that queue state is truncated to 0 when execution exceeds expectation"""
        scheduler = SwarmPilotScheduler()

        # Create mock TaskInstance
        mock_client = Mock(spec=TaskInstanceClient)
        mock_client.base_url = "http://localhost:8101"

        status_mock = Mock()
        status_mock.instance_id = "ti-67890"
        status_mock.model_type = "tx_det_dummy"
        status_mock.replicas_running = 1
        status_mock.queue_size = 0
        status_mock.status = "running"
        mock_client.get_status.return_value = status_mock

        ti_uuid = uuid4()
        task_instance = TaskInstance(uuid=ti_uuid, instance=mock_client)
        scheduler.taskinstances.append(task_instance)

        strategy = ShortestQueueStrategy(
            taskinstances=scheduler.taskinstances,
            predictor_url="http://localhost:8100"
        )
        scheduler.strategy = strategy

        # Initialize queue state with small expected time (override default)
        strategy.queue_states[ti_uuid] = QueueState(
            expected_ms=30.0,
            error_ms=5.0,
            task_count=1
        )

        # Task took longer than expected
        execution_time = 80.0

        strategy.update_queue_on_completion(
            instance_uuid=ti_uuid,
            execution_time=execution_time
        )

        # Should be truncated to 0
        queue_state = strategy.queue_states[ti_uuid]
        assert queue_state.expected_ms == 0.0
        assert queue_state.task_count == 0
        # Error unchanged
        assert queue_state.error_ms == 5.0

    def test_scheduler_api_notification_handler(self):
        """Test the Scheduler API notification endpoint logic"""
        scheduler = SwarmPilotScheduler()

        # Create mock TaskInstance
        mock_client = Mock(spec=TaskInstanceClient)
        mock_client.base_url = "http://localhost:8101"

        status_mock = Mock()
        status_mock.instance_id = "ti-test-123"
        status_mock.model_type = "tx_det_dummy"
        status_mock.replicas_running = 1
        status_mock.queue_size = 0
        status_mock.status = "running"
        mock_client.get_status.return_value = status_mock

        ti_uuid = uuid4()
        task_instance = TaskInstance(uuid=ti_uuid, instance=mock_client)
        scheduler.taskinstances.append(task_instance)

        strategy = ShortestQueueStrategy(
            taskinstances=scheduler.taskinstances,
            predictor_url="http://localhost:8100"
        )
        scheduler.strategy = strategy

        # Initialize queue state (override default)
        strategy.queue_states[ti_uuid] = QueueState(
            expected_ms=150.0,
            error_ms=15.0,
            task_count=2
        )

        # Simulate notification payload from TaskInstance
        notification = {
            "task_id": "task-abc-123",
            "instance_id": "ti-test-123",
            "execution_time": 50.0
        }

        # Simulate what the API endpoint does:
        # 1. Find TaskInstance UUID by instance_id
        instance_uuid = None
        for ti in scheduler.taskinstances:
            status = ti.instance.get_status()
            if status.instance_id == notification["instance_id"]:
                instance_uuid = ti.uuid
                break

        assert instance_uuid is not None
        assert instance_uuid == ti_uuid

        # 2. Update queue state
        scheduler.strategy.update_queue_on_completion(
            instance_uuid=instance_uuid,
            execution_time=notification["execution_time"]
        )

        # 3. Verify update
        queue_state = strategy.queue_states[ti_uuid]
        assert queue_state.expected_ms == 100.0  # 150 - 50
        assert queue_state.task_count == 1
        assert queue_state.error_ms == 15.0

    def test_multiple_notifications(self):
        """Test multiple sequential task completion notifications"""
        scheduler = SwarmPilotScheduler()

        # Create mock TaskInstance
        mock_client = Mock(spec=TaskInstanceClient)
        mock_client.base_url = "http://localhost:8101"

        status_mock = Mock()
        status_mock.instance_id = "ti-multi-test"
        status_mock.model_type = "tx_det_dummy"
        status_mock.replicas_running = 1
        status_mock.queue_size = 0
        status_mock.status = "running"
        mock_client.get_status.return_value = status_mock

        ti_uuid = uuid4()
        task_instance = TaskInstance(uuid=ti_uuid, instance=mock_client)
        scheduler.taskinstances.append(task_instance)

        strategy = ShortestQueueStrategy(
            taskinstances=scheduler.taskinstances,
            predictor_url="http://localhost:8100"
        )
        scheduler.strategy = strategy

        # Initialize queue state with multiple tasks (override default)
        strategy.queue_states[ti_uuid] = QueueState(
            expected_ms=300.0,
            error_ms=20.0,
            task_count=5
        )

        # Simulate 5 task completions
        execution_times = [60.0, 55.0, 70.0, 50.0, 65.0]

        for i, exec_time in enumerate(execution_times):
            initial_expected = strategy.queue_states[ti_uuid].expected_ms
            initial_count = strategy.queue_states[ti_uuid].task_count

            strategy.update_queue_on_completion(
                instance_uuid=ti_uuid,
                execution_time=exec_time
            )

            queue_state = strategy.queue_states[ti_uuid]
            assert queue_state.expected_ms == max(0.0, initial_expected - exec_time)
            assert queue_state.task_count == initial_count - 1
            assert queue_state.error_ms == 20.0  # Error unchanged

        # Final state: all tasks completed
        final_state = strategy.queue_states[ti_uuid]
        assert final_state.task_count == 0
        assert final_state.error_ms == 20.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
