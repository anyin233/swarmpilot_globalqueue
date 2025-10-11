"""
Unit tests for update_queue functionality in ShortestQueueStrategy

Tests cover:
1. Queue state initialization
2. Task enqueue updates
3. Task completion updates
4. Error propagation calculations
5. Integration with Predictor service (mocked)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from uuid import UUID, uuid4
from math import sqrt

import sys
sys.path.append('/home/yanweiye/Project/swarmpilot/swarmpilot_globalqueue')
sys.path.append('/home/yanweiye/Project/swarmpilot/swarmpilot_taskinstance/src')

from strategy_refactored import (
    ShortestQueueStrategy,
    TaskInstance,
    SelectionRequest,
    QueueState
)
from task_instance_client_refactored import TaskInstanceClient, EnqueueResponse


@pytest.fixture
def mock_task_instance():
    """Create a mock TaskInstance"""
    ti_uuid = uuid4()
    mock_client = Mock(spec=TaskInstanceClient)
    mock_client.base_url = "http://localhost:8101"

    task_instance = TaskInstance(
        uuid=ti_uuid,
        instance=mock_client,
        model_type="tx_det_dummy"
    )
    return task_instance


@pytest.fixture
def mock_task_instances():
    """Create multiple mock TaskInstances"""
    instances = []
    for i in range(3):
        ti_uuid = uuid4()
        mock_client = Mock(spec=TaskInstanceClient)
        mock_client.base_url = f"http://localhost:810{i+1}"

        task_instance = TaskInstance(
            uuid=ti_uuid,
            instance=mock_client,
            model_type="tx_det_dummy"
        )
        instances.append(task_instance)
    return instances


@pytest.fixture
def strategy(mock_task_instances):
    """Create ShortestQueueStrategy with mock instances"""
    return ShortestQueueStrategy(
        taskinstances=mock_task_instances,
        predictor_url="http://localhost:8100",
        predictor_timeout=10.0
    )


def add_instance_to_strategy(strategy, task_instance):
    """Helper to add a new instance to an existing strategy"""
    if task_instance not in strategy.taskinstances:
        strategy.taskinstances.append(task_instance)
    if task_instance.uuid not in strategy.queue_states:
        strategy.queue_states[task_instance.uuid] = QueueState()


class TestQueueStateInitialization:
    """Test queue state initialization"""

    def test_queue_states_initialized_for_all_instances(self, strategy, mock_task_instances):
        """Queue states should be initialized for all task instances"""
        assert len(strategy.queue_states) == len(mock_task_instances)

        for ti in mock_task_instances:
            assert ti.uuid in strategy.queue_states
            queue_state = strategy.queue_states[ti.uuid]
            assert isinstance(queue_state, QueueState)
            assert queue_state.expected_ms == 0.0
            assert queue_state.error_ms == 0.0
            assert queue_state.task_count == 0

    def test_queue_state_has_correct_fields(self, strategy, mock_task_instances):
        """Queue state should have all required fields"""
        queue_state = strategy.queue_states[mock_task_instances[0].uuid]

        assert hasattr(queue_state, 'expected_ms')
        assert hasattr(queue_state, 'error_ms')
        assert hasattr(queue_state, 'last_update_time')
        assert hasattr(queue_state, 'task_count')


class TestErrorPropagation:
    """Test error propagation calculations"""

    def test_compute_distribution_summary_with_valid_quantiles(self, strategy):
        """Should correctly compute expectation and error from quantiles"""
        quantiles = {
            "0.25": 100.0,
            "0.5": 150.0,
            "0.75": 200.0,
            "0.99": 300.0
        }

        result = strategy._compute_distribution_summary(quantiles)

        assert result is not None
        assert "expected_ms" in result
        assert "error_ms" in result

        # Expected: 0.7 * 150 + 0.15 * 100 + 0.15 * 200 = 150
        expected = 0.7 * 150.0 + 0.15 * 100.0 + 0.15 * 200.0
        assert result["expected_ms"] == pytest.approx(expected)

        # Error calculation
        iqr = 200.0 - 100.0  # 100
        base_std = iqr / 1.349  # ~74.13
        ratio_denominator = 200.0 - 150.0  # 50
        ratio = (300.0 - 150.0) / (1.65 * ratio_denominator)  # 150 / 82.5 ~= 1.82
        multiplier = min(1.5, ratio)  # 1.5
        expected_error = base_std * multiplier

        assert result["error_ms"] == pytest.approx(expected_error, rel=0.01)

    def test_compute_distribution_summary_with_missing_quantiles(self, strategy):
        """Should return None if required quantiles are missing"""
        quantiles = {
            "0.5": 150.0,
            "0.75": 200.0
            # Missing 0.25
        }

        result = strategy._compute_distribution_summary(quantiles)
        assert result is None

    def test_compute_distribution_summary_with_empty_quantiles(self, strategy):
        """Should return None for empty quantiles"""
        result = strategy._compute_distribution_summary({})
        assert result is None

    def test_extract_quantile_predictions(self, strategy):
        """Should correctly extract quantiles from predictor response"""
        response = {
            "quantiles": [0.25, 0.5, 0.75, 0.99],
            "quantile_predictions": [100.0, 150.0, 200.0, 300.0]
        }

        result = strategy._extract_quantile_predictions(response)

        assert len(result) == 4
        assert "0.25" in result
        assert result["0.25"] == 100.0
        assert result["0.5"] == 150.0


class TestUpdateQueueOnEnqueue:
    """Test update_queue method when task is enqueued"""

    @patch('strategy_refactored.ShortestQueueStrategy._get_predictor_client')
    def test_update_queue_adds_task_prediction_to_queue_state(
        self,
        mock_get_client,
        strategy,
        mock_task_instance
    ):
        """Should add task prediction to queue state"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Mock predictor client
        mock_predictor = MagicMock()
        mock_predictor.predict_from_trace.return_value = {
            "status": "success",
            "quantiles": [0.25, 0.5, 0.75, 0.99],
            "quantile_predictions": [100.0, 150.0, 200.0, 300.0]
        }
        mock_get_client.return_value = mock_predictor

        # Create request and response
        request = SelectionRequest(
            model_type="tx_det_dummy",
            input_data={"test": "data"},
            metadata={
                "model_id": "tx_det_dummy",
                "model_name": "dummy",
                "hardware": "CPU",
                "software_name": "vllm",
                "software_version": "0.1.0",
                "input_tokens": 512
            }
        )

        enqueue_response = EnqueueResponse(
            task_id="test-task-id",
            queue_size=1,
            enqueue_time=123.45
        )

        # Get initial state
        initial_expected = strategy.queue_states[mock_task_instance.uuid].expected_ms
        initial_error = strategy.queue_states[mock_task_instance.uuid].error_ms

        # Update queue
        strategy.update_queue(mock_task_instance, request, enqueue_response)

        # Verify state was updated
        final_state = strategy.queue_states[mock_task_instance.uuid]
        assert final_state.expected_ms > initial_expected
        assert final_state.error_ms > initial_error
        assert final_state.task_count == 1

    @patch('strategy_refactored.ShortestQueueStrategy._get_predictor_client')
    def test_update_queue_accumulates_multiple_tasks(
        self,
        mock_get_client,
        strategy,
        mock_task_instance
    ):
        """Should correctly accumulate predictions for multiple tasks"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Mock predictor to return consistent predictions
        mock_predictor = MagicMock()
        mock_predictor.predict_from_trace.return_value = {
            "status": "success",
            "quantiles": [0.25, 0.5, 0.75, 0.99],
            "quantile_predictions": [100.0, 150.0, 200.0, 300.0]
        }
        mock_get_client.return_value = mock_predictor

        request = SelectionRequest(
            model_type="tx_det_dummy",
            input_data={},
            metadata={
                "model_id": "tx_det_dummy",
                "model_name": "dummy",
                "hardware": "CPU",
                "software_name": "vllm",
                "software_version": "0.1.0"
            }
        )

        # Add first task
        response1 = EnqueueResponse(task_id="task-1", queue_size=1, enqueue_time=1.0)
        strategy.update_queue(mock_task_instance, request, response1)

        state_after_1 = strategy.queue_states[mock_task_instance.uuid]
        expected_1 = state_after_1.expected_ms
        error_1 = state_after_1.error_ms

        # Add second task
        response2 = EnqueueResponse(task_id="task-2", queue_size=2, enqueue_time=2.0)
        strategy.update_queue(mock_task_instance, request, response2)

        state_after_2 = strategy.queue_states[mock_task_instance.uuid]

        # Expected should add linearly
        assert state_after_2.expected_ms == pytest.approx(2 * expected_1)

        # Error should add using sqrt(e1^2 + e2^2)
        expected_error = sqrt(error_1 ** 2 + error_1 ** 2)
        assert state_after_2.error_ms == pytest.approx(expected_error, rel=0.01)

        assert state_after_2.task_count == 2

    def test_update_queue_handles_predictor_failure_gracefully(
        self,
        strategy,
        mock_task_instance
    ):
        """Should handle predictor failures without raising exceptions"""
        request = SelectionRequest(
            model_type="tx_det_dummy",
            input_data={},
            metadata={}
        )

        response = EnqueueResponse(task_id="task-1", queue_size=1, enqueue_time=1.0)

        # Should not raise even if predictor fails
        try:
            strategy.update_queue(mock_task_instance, request, response)
        except Exception as e:
            pytest.fail(f"update_queue raised exception: {e}")


class TestUpdateQueueOnCompletion:
    """Test update_queue_on_completion method"""

    def test_update_queue_on_completion_subtracts_execution_time(
        self,
        strategy,
        mock_task_instance
    ):
        """Should subtract execution time from expected_ms"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Set initial queue state
        queue_state = strategy.queue_states[mock_task_instance.uuid]
        queue_state.expected_ms = 500.0
        queue_state.error_ms = 50.0
        queue_state.task_count = 2

        # Complete a task
        execution_time = 200.0
        strategy.update_queue_on_completion(mock_task_instance.uuid, execution_time)

        # Verify update
        assert queue_state.expected_ms == pytest.approx(300.0)
        assert queue_state.error_ms == 50.0  # Unchanged
        assert queue_state.task_count == 1

    def test_update_queue_on_completion_does_not_go_negative(
        self,
        strategy,
        mock_task_instance
    ):
        """Should not allow expected_ms to go negative"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Set initial queue state
        queue_state = strategy.queue_states[mock_task_instance.uuid]
        queue_state.expected_ms = 100.0
        queue_state.task_count = 1

        # Complete a task with longer execution time
        execution_time = 200.0
        strategy.update_queue_on_completion(mock_task_instance.uuid, execution_time)

        # Should be clamped to 0
        assert queue_state.expected_ms == 0.0
        assert queue_state.task_count == 0

    def test_update_queue_on_completion_preserves_error(
        self,
        strategy,
        mock_task_instance
    ):
        """Should preserve error_ms unchanged"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Set initial queue state
        queue_state = strategy.queue_states[mock_task_instance.uuid]
        queue_state.expected_ms = 500.0
        queue_state.error_ms = 75.0
        initial_error = queue_state.error_ms

        # Complete a task
        strategy.update_queue_on_completion(mock_task_instance.uuid, 200.0)

        # Error should be unchanged
        assert queue_state.error_ms == initial_error

    def test_update_queue_on_completion_handles_unknown_instance(
        self,
        strategy
    ):
        """Should handle completion for unknown instance gracefully"""
        unknown_uuid = uuid4()

        # Should not raise
        try:
            strategy.update_queue_on_completion(unknown_uuid, 100.0)
        except Exception as e:
            pytest.fail(f"update_queue_on_completion raised exception: {e}")


class TestPredictionErrorMonitoring:
    """Test prediction error monitoring and warnings

    Note: These tests verify the warning logic by checking state behavior.
    The actual warnings are logged via loguru and can be seen in test output.
    """

    def test_handles_large_prediction_error(
        self,
        strategy,
        mock_task_instance
    ):
        """Should handle large prediction errors (>50%) correctly"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Set up queue state with expected time
        queue_state = strategy.queue_states[mock_task_instance.uuid]
        queue_state.expected_ms = 100.0
        queue_state.task_count = 1

        # Complete task with 2x expected time (100% error)
        # This should trigger the large prediction error warning
        strategy.update_queue_on_completion(mock_task_instance.uuid, 200.0)

        # Verify state was updated correctly despite large error
        assert queue_state.expected_ms == 0.0  # Clamped
        assert queue_state.task_count == 0

    def test_handles_execution_exceeding_expectation(
        self,
        strategy,
        mock_task_instance
    ):
        """Should handle execution time exceeding total queue expectation"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Set up queue state
        queue_state = strategy.queue_states[mock_task_instance.uuid]
        queue_state.expected_ms = 100.0
        queue_state.task_count = 1

        # Complete task that exceeds total expectation
        # This should trigger the exceeding expectation warning
        strategy.update_queue_on_completion(mock_task_instance.uuid, 150.0)

        # State should be clamped to zero
        assert queue_state.expected_ms == 0.0
        assert queue_state.task_count == 0

    def test_clamps_negative_values_to_zero(
        self,
        strategy,
        mock_task_instance
    ):
        """Should clamp negative expected_ms to zero when truncated"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Set up queue state
        queue_state = strategy.queue_states[mock_task_instance.uuid]
        queue_state.expected_ms = 100.0
        queue_state.task_count = 1

        # Complete task that causes clamping
        strategy.update_queue_on_completion(mock_task_instance.uuid, 150.0)

        # Verify clamping occurred (would be -50 without clamping)
        assert queue_state.expected_ms == 0.0
        assert queue_state.task_count == 0

    def test_no_clamping_for_accurate_prediction(
        self,
        strategy,
        mock_task_instance
    ):
        """Should not clamp when prediction is accurate"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Set up queue state
        queue_state = strategy.queue_states[mock_task_instance.uuid]
        queue_state.expected_ms = 100.0
        queue_state.task_count = 1

        # Complete task with reasonable prediction (20% error, under 50% threshold)
        strategy.update_queue_on_completion(mock_task_instance.uuid, 80.0)

        # State should be updated normally without clamping
        assert queue_state.expected_ms == pytest.approx(20.0)
        assert queue_state.task_count == 0

    def test_calculates_per_task_expected_correctly(
        self,
        strategy,
        mock_task_instance
    ):
        """Should correctly calculate per-task expected time for error checking"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Set up queue state with multiple tasks
        queue_state = strategy.queue_states[mock_task_instance.uuid]
        queue_state.expected_ms = 300.0  # 3 tasks * 100ms each
        queue_state.task_count = 3

        # Complete one task - should compare against 100ms per task
        # 150ms vs 100ms = 50% error, which is at the threshold
        strategy.update_queue_on_completion(mock_task_instance.uuid, 150.0)

        # Queue should now have 150ms remaining (300 - 150)
        assert queue_state.expected_ms == pytest.approx(150.0)
        assert queue_state.task_count == 2


class TestIntegration:
    """Integration tests for complete workflow"""

    @patch('strategy_refactored.ShortestQueueStrategy._get_predictor_client')
    def test_enqueue_and_complete_workflow(
        self,
        mock_get_client,
        strategy,
        mock_task_instance
    ):
        """Test complete workflow: enqueue -> complete"""
        # Add instance to strategy
        add_instance_to_strategy(strategy, mock_task_instance)

        # Mock predictor
        mock_predictor = MagicMock()
        mock_predictor.predict_from_trace.return_value = {
            "status": "success",
            "quantiles": [0.25, 0.5, 0.75, 0.99],
            "quantile_predictions": [100.0, 150.0, 200.0, 300.0]
        }
        mock_get_client.return_value = mock_predictor

        # Enqueue task
        request = SelectionRequest(
            model_type="tx_det_dummy",
            input_data={},
            metadata={
                "model_id": "tx_det_dummy",
                "model_name": "dummy",
                "hardware": "CPU",
                "software_name": "vllm",
                "software_version": "0.1.0"
            }
        )

        enqueue_response = EnqueueResponse(
            task_id="test-task",
            queue_size=1,
            enqueue_time=1.0
        )

        strategy.update_queue(mock_task_instance, request, enqueue_response)

        # Verify enqueue updated state
        state = strategy.queue_states[mock_task_instance.uuid]
        assert state.expected_ms > 0
        assert state.error_ms > 0
        assert state.task_count == 1

        expected_before_complete = state.expected_ms

        # Complete task
        actual_execution_time = 175.0
        strategy.update_queue_on_completion(mock_task_instance.uuid, actual_execution_time)

        # Verify completion updated state
        # Note: If actual_execution_time > expected_before_complete, result is clamped to 0
        expected_after_complete = max(0.0, expected_before_complete - actual_execution_time)
        assert state.expected_ms == pytest.approx(expected_after_complete)
        assert state.task_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
