"""
Shortest Queue Strategy

Strategy that selects the instance with shortest expected completion time,
maintaining local queue state for accurate prediction.

This strategy features:
- Integration with PredictorClient from predictor_client.py
- Local queue state tracking (expected_ms and error_ms)
- Error propagation using variance theory
- Real-time prediction for each incoming request
"""

from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from uuid import UUID
from loguru import logger
from math import sqrt
import time
import json
from datetime import datetime
from pathlib import Path

from .base import BaseStrategy, TaskInstance, TaskInstanceQueue, SelectionRequest
from ..models import EnqueueResponse
from ..predictor_client import PredictorClient


@dataclass
class QueueState:
    """Local queue state tracking for scheduler-side prediction"""
    expected_ms: float = 0.0
    error_ms: float = 0.0
    last_update_time: float = field(default_factory=time.time)
    task_count: int = 0


class ShortestQueueStrategy(BaseStrategy):
    """
    Strategy that selects the instance with shortest expected completion time

    Features:
    - Selects instance with minimum expected_ms and minimum error_ms
    - Maintains local queue state tracking in strategy
    - Uses PredictorClient for execution time prediction
    - Uses error propagation theory for queue state updates
    """

    def __init__(
        self,
        taskinstances: List[TaskInstance],
        predictor_url: str = "http://localhost:8100",
        predictor_timeout: float = 10.0,
        debug_log_path: Optional[str] = None,
        get_debug_enabled: Optional[Callable[[], bool]] = None
    ):
        """
        Initialize ShortestQueue strategy with PredictorClient

        Args:
            taskinstances: List of available TaskInstances
            predictor_url: URL of the Predictor service
            predictor_timeout: Timeout for predictor requests in seconds
            debug_log_path: Path to debug log file (default: "./shortest_queue_debug.jsonl")
            get_debug_enabled: Callable to check if debug logging is enabled
        """
        super().__init__(taskinstances)
        self.predictor_url = predictor_url
        self.predictor_timeout = predictor_timeout

        # Track queue state for each TaskInstance
        self.queue_states: Dict[UUID, QueueState] = {}
        for ti in taskinstances:
            self.queue_states[ti.uuid] = QueueState()

        # PredictorClient instance
        self.predictor_client = PredictorClient(
            base_url=predictor_url,
            timeout=predictor_timeout
        )

        # Debug logging configuration
        self.debug_log_path = debug_log_path or "./shortest_queue_debug.jsonl"
        self.get_debug_enabled = get_debug_enabled or (lambda: False)

        logger.info(f"Initialized ShortestQueueStrategy with PredictorClient at {predictor_url}")

    def _write_debug_log(self, queue_states_snapshot: Dict[str, Dict[str, float]]):
        """Write debug log entry to JSON file"""
        try:
            if not self.get_debug_enabled():
                return

            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "strategy": "shortest_queue",
                "queue_states": queue_states_snapshot
            }

            # Append to JSONL file
            Path(self.debug_log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.debug_log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

        except Exception as e:
            logger.warning(f"Failed to write debug log: {e}")

    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Select the instance with shortest expected completion time and smallest error
        Uses locally maintained queue states instead of querying TaskInstance
        """
        # Use locally maintained queue states
        updated_candidates = []
        for ti, old_queue_info in candidates:
            try:
                # Get queue state from local tracking
                queue_state = self.queue_states.get(ti.uuid)
                if queue_state is None:
                    logger.warning(f"No queue state for TaskInstance {ti.uuid}, initializing")
                    queue_state = QueueState()
                    self.queue_states[ti.uuid] = queue_state

                # Get current queue size from TaskInstance
                try:
                    client = ti.instance
                    status = client.get_status()
                    queue_size = status.queue_size
                except Exception as e:
                    logger.debug(f"Failed to get status for TaskInstance {ti.uuid}: {e}")
                    queue_size = old_queue_info.queue_size

                # Create updated queue info using local state
                updated_queue_info = TaskInstanceQueue(
                    expected_ms=queue_state.expected_ms,
                    error_ms=queue_state.error_ms,
                    queue_size=queue_size,
                    model_type=old_queue_info.model_type,
                    instance_id=old_queue_info.instance_id,
                    ti_uuid=ti.uuid
                )

                updated_candidates.append((ti, updated_queue_info))

            except Exception as e:
                logger.warning(f"Failed to update queue info for TaskInstance {ti.uuid}: {e}")
                updated_candidates.append((ti, old_queue_info))

        # Select instance with minimum expected_ms and minimum error_ms
        selected = min(updated_candidates, key=lambda x: (x[1].expected_ms, x[1].error_ms))

        logger.info(
            f"ShortestQueueStrategy selected: instance {selected[0].uuid} "
            f"with expected_ms={selected[1].expected_ms:.2f}ms, error_ms={selected[1].error_ms:.2f}ms"
        )

        # Write debug log if enabled
        if self.get_debug_enabled():
            queue_states_snapshot = {}
            for ti, queue_info in updated_candidates:
                queue_states_snapshot[str(ti.uuid)] = {
                    "expected_ms": queue_info.expected_ms,
                    "error_ms": queue_info.error_ms,
                    "queue_size": queue_info.queue_size,
                    "selected": (ti.uuid == selected[0].uuid)
                }
            self._write_debug_log(queue_states_snapshot)

        return selected

    def update_queue(
        self,
        selected_instance: TaskInstance,
        request: SelectionRequest,
        enqueue_response: EnqueueResponse
    ):
        """
        Update queue state after task enqueue

        Uses PredictorClient to predict execution time and accumulates
        the expectation and error to the target queue
        """
        try:
            # Check if real execution time is provided
            if 'server_time_cost' in request.metadata:
                task_expected = float(request.metadata['server_time_cost'])
                task_error = sqrt(task_expected * 0.05)
                logger.info(f"Using real execution time: {task_expected:.2f}ms")
            else:
                # Use PredictorClient to get prediction
                logger.debug(f"Requesting prediction for model_type={request.model_type}")
                prediction_response = self.predictor_client.predict(
                    model_type=request.model_type,
                    metadata=request.metadata
                )

                # Check prediction status (new format: response.results.status)
                if prediction_response.results.status != "success":
                    logger.warning(
                        f"Prediction failed: {prediction_response.results.status}, "
                        "skipping queue state update"
                    )
                    return

                # Use expect and error directly from results
                if prediction_response.results.expect is not None and prediction_response.results.error is not None:
                    task_expected = prediction_response.results.expect
                    task_error = prediction_response.results.error
                    logger.info(
                        f"Prediction for {request.model_type}: "
                        f"expected={task_expected:.2f}ms, error={task_error:.2f}ms"
                    )
                else:
                    # Fallback: Extract quantile predictions and compute summary
                    if not prediction_response.results.quantiles or not prediction_response.results.quantile_predictions:
                        logger.warning("No quantile data or expect/error in prediction response")
                        return

                    # Convert to dict format for compatibility
                    quantiles = {}
                    for q, pred in zip(prediction_response.results.quantiles, prediction_response.results.quantile_predictions):
                        quantiles[str(q)] = pred

                    # Compute distribution summary
                    summary = self._compute_distribution_summary(quantiles)
                    if not summary or 'expected_ms' not in summary:
                        logger.warning("Could not get valid prediction summary")
                        return

                    task_expected = summary['expected_ms']
                    task_error = summary['error_ms']

                    logger.info(
                        f"Prediction for {request.model_type}: "
                        f"expected={task_expected:.2f}ms, error={task_error:.2f}ms"
                    )

            # Update queue state using error propagation
            queue_state = self.queue_states[selected_instance.uuid]
            new_expected = queue_state.expected_ms + task_expected
            new_error = sqrt(queue_state.error_ms ** 2 + task_error ** 2)

            queue_state.expected_ms = new_expected
            queue_state.error_ms = new_error
            queue_state.task_count += 1
            queue_state.last_update_time = time.time()

            logger.info(
                f"Updated queue state for instance {selected_instance.uuid}: "
                f"expected={new_expected:.2f}ms, error={new_error:.2f}ms, tasks={queue_state.task_count}"
            )

        except Exception as e:
            logger.error(f"Failed to update queue state: {e}", exc_info=True)

    def update_queue_on_completion(self, instance_uuid: UUID, task_id: str, execution_time: float):
        """Update queue state when task completes"""
        if instance_uuid not in self.queue_states:
            logger.warning(f"Received completion for unknown instance {instance_uuid}")
            return

        queue_state = self.queue_states[instance_uuid]
        old_expected = queue_state.expected_ms

        # Subtract actual execution time
        new_expected = max(0.0, old_expected - execution_time)
        queue_state.expected_ms = new_expected
        queue_state.task_count = max(0, queue_state.task_count - 1)
        queue_state.last_update_time = time.time()

        logger.info(
            f"Updated queue state on completion for instance {instance_uuid}: "
            f"{old_expected:.2f}ms -> {new_expected:.2f}ms (subtracted {execution_time:.2f}ms)"
        )

    @staticmethod
    def _compute_distribution_summary(quantiles: Dict[str, float]) -> Optional[Dict[str, Optional[float]]]:
        """
        Compute expectation and error from quantile predictions

        Formula: A_i = 0.7·t0.50 + 0.15·t0.25 + 0.15·t0.75
        """
        if not quantiles:
            return None

        numeric_quantiles: Dict[float, float] = {}
        for raw_key, raw_value in quantiles.items():
            try:
                quantile_key = float(raw_key)
                quantile_value = float(raw_value)
            except (TypeError, ValueError):
                continue
            numeric_quantiles[quantile_key] = quantile_value

        required_quantiles = (0.25, 0.5, 0.75)
        if not all(key in numeric_quantiles for key in required_quantiles):
            return None

        q25 = numeric_quantiles[0.25]
        q50 = numeric_quantiles[0.5]
        q75 = numeric_quantiles[0.75]

        expectation = 0.7 * q50 + 0.15 * q25 + 0.15 * q75

        interquartile_range = q75 - q25
        if interquartile_range <= 0:
            error: Optional[float] = 0.0
        else:
            base_std = interquartile_range / 1.349
            ratio_denominator = q75 - q50
            multiplier = 1.5
            q99 = numeric_quantiles.get(0.99)
            if q99 is not None and ratio_denominator > 0:
                ratio = (q99 - q50) / (1.65 * ratio_denominator)
                if ratio > 0:
                    multiplier = min(1.5, ratio)
                else:
                    multiplier = 0.0
            error = base_std * multiplier
            error = max(error, 0.0)

        return {
            "expected_ms": expectation,
            "error_ms": error,
        }
