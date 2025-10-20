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
class TaskPrediction:
    """Single task prediction information cache"""
    task_id: str
    expected_ms: float
    error_ms: float
    enqueue_time: float


@dataclass
class QueueState:
    """Local queue state tracking for scheduler-side prediction"""
    expected_ms: float = 0.0
    error_ms: float = 0.0
    last_update_time: float = field(default_factory=time.time)
    task_count: int = 0
    # Pending tasks prediction cache for error recalculation
    pending_tasks: Dict[str, TaskPrediction] = field(default_factory=dict)


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
        error_recalc_threshold: float = 2.0,
        debug_log_path: Optional[str] = None,
        get_debug_enabled: Optional[Callable[[], bool]] = None,
        fake_data_bypass: bool = False,
        fake_data_path: Optional[str] = None
    ):
        """
        Initialize ShortestQueue strategy with PredictorClient

        Args:
            taskinstances: List of available TaskInstances
            predictor_url: URL of the Predictor service
            predictor_timeout: Timeout for predictor requests in seconds
            error_recalc_threshold: Error recalculation threshold (default: 2.0)
                When error_ms > threshold * expected_ms, trigger recalculation
            debug_log_path: Path to debug log file (default: "./shortest_queue_debug.jsonl")
            get_debug_enabled: Callable to check if debug logging is enabled
            fake_data_bypass: Enable fake data bypass mode
            fake_data_path: Path to fake data directory
        """
        super().__init__(taskinstances)
        self.predictor_url = predictor_url
        self.predictor_timeout = predictor_timeout
        self.error_recalc_threshold = error_recalc_threshold

        # Track queue state for each TaskInstance
        self.queue_states: Dict[UUID, QueueState] = {}
        for ti in taskinstances:
            self.queue_states[ti.uuid] = QueueState()

        # PredictorClient instance
        self.predictor_client = PredictorClient(
            base_url=predictor_url,
            timeout=predictor_timeout,
            fake_data_bypass=fake_data_bypass,
            fake_data_path=fake_data_path
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

        # Select instance with minimum expected_ms, error_ms, and task_count (for tie-breaking)
        # Adding task_count ensures fair distribution when queue times are equal
        # Using UUID as final tie-breaker for deterministic behavior
        selected = min(
            updated_candidates,
            key=lambda x: (
                x[1].expected_ms,
                x[1].error_ms,
                self.queue_states[x[0].uuid].task_count,  # Prefer instances with fewer tasks
                str(x[0].uuid)  # Deterministic tie-breaker
            )
        )

        logger.info(
            f"ShortestQueueStrategy selected: instance {selected[0].uuid} "
            f"with expected_ms={selected[1].expected_ms:.2f}ms, error_ms={selected[1].error_ms:.2f}ms, "
            f"task_count={self.queue_states[selected[0].uuid].task_count}"
        )

        # Write debug log if enabled
        if self.get_debug_enabled():
            queue_states_snapshot = {}
            for ti, queue_info in updated_candidates:
                queue_states_snapshot[str(ti.uuid)] = {
                    "expected_ms": queue_info.expected_ms,
                    "error_ms": queue_info.error_ms,
                    "queue_size": queue_info.queue_size,
                    "task_count": self.queue_states[ti.uuid].task_count,
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
        logger.debug(
            f"update_queue called for instance {selected_instance.uuid}, "
            f"model_type={request.model_type}"
        )
        try:
            # Check if real execution time is provided
            if 'server_time_cost' in request.metadata:
                task_expected = float(request.metadata['server_time_cost'])
                task_error = sqrt(task_expected * 0.05)
                logger.info(f"Using real execution time: {task_expected:.2f}ms")
            else:
                # Use PredictorClient to get prediction
                logger.debug(f"Requesting prediction for model_type={request.model_type}, metadata={request.metadata}")
                prediction_response = self.predictor_client.predict(
                    model_type=request.model_type,
                    metadata=request.metadata
                )

                # Check prediction status (new format: response.results.status)
                if prediction_response.results.status != "success":
                    logger.warning(
                        f"Prediction failed for model_type={request.model_type}: "
                        f"status={prediction_response.results.status}, "
                        f"expect={prediction_response.results.expect}, "
                        f"error={prediction_response.results.error}. "
                        "Skipping queue state update"
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
                    logger.debug(
                        f"No expect/error in prediction response. "
                        f"expect={prediction_response.results.expect}, "
                        f"error={prediction_response.results.error}, "
                        f"quantiles={prediction_response.results.quantiles}, "
                        f"predictions={prediction_response.results.quantile_predictions}"
                    )
                    if not prediction_response.results.quantiles or not prediction_response.results.quantile_predictions:
                        logger.warning(
                            f"No quantile data or expect/error in prediction response. "
                            f"Model: {request.model_type}. Skipping queue state update"
                        )
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

            # Cache task prediction information for error recalculation
            task_id = enqueue_response.task_id
            queue_state = self.queue_states[selected_instance.uuid]

            queue_state.pending_tasks[task_id] = TaskPrediction(
                task_id=task_id,
                expected_ms=task_expected,
                error_ms=task_error,
                enqueue_time=enqueue_response.enqueue_time
            )

            # Update queue state using error propagation
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

            # Write debug log after update if enabled
            if self.get_debug_enabled():
                queue_states_snapshot = {}
                for ti in self.taskinstances:
                    ti_queue_state = self.queue_states[ti.uuid]
                    try:
                        # Get current queue size
                        status = ti.instance.get_status()
                        queue_size = status.queue_size
                    except Exception:
                        queue_size = 0

                    queue_states_snapshot[str(ti.uuid)] = {
                        "expected_ms": ti_queue_state.expected_ms,
                        "error_ms": ti_queue_state.error_ms,
                        "queue_size": queue_size,
                        "task_count": ti_queue_state.task_count,
                        "selected": (ti.uuid == selected_instance.uuid)
                    }
                self._write_debug_log(queue_states_snapshot)

        except Exception as e:
            logger.error(f"Failed to update queue state: {e}", exc_info=True)

    def update_queue_on_completion(self, instance_uuid: UUID, task_id: str, execution_time: float):
        """
        Update queue state when task completes with error recalculation

        This method:
        1. Removes completed task from pending_tasks cache
        2. Subtracts actual execution time from expected_ms
        3. Checks if error ratio exceeds threshold
        4. If yes, recalculates queue state from remaining pending tasks
        """
        if instance_uuid not in self.queue_states:
            logger.warning(f"Received completion for unknown instance {instance_uuid}")
            return

        queue_state = self.queue_states[instance_uuid]
        old_expected = queue_state.expected_ms
        old_error = queue_state.error_ms

        # Step 1: Remove completed task from cache (for recalculation)
        if task_id in queue_state.pending_tasks:
            queue_state.pending_tasks.pop(task_id)
            logger.debug(f"Removed task {task_id} from pending_tasks cache")
        else:
            logger.warning(
                f"Task {task_id} not found in pending_tasks cache for instance {instance_uuid}"
            )

        # Step 2: Subtract actual execution time (maintain current behavior)
        new_expected = max(0.0, old_expected - execution_time)
        queue_state.expected_ms = new_expected
        queue_state.task_count = max(0, queue_state.task_count - 1)

        # Step 3: Check if error recalculation is needed
        should_recalculate = (
            queue_state.expected_ms > 0 and
            old_error > self.error_recalc_threshold * queue_state.expected_ms
        )

        if should_recalculate:
            logger.warning(
                f"High error ratio detected for instance {instance_uuid}: "
                f"error={old_error:.2f}ms > {self.error_recalc_threshold}×expected={queue_state.expected_ms:.2f}ms. "
                f"Triggering queue state recalculation from {len(queue_state.pending_tasks)} pending tasks."
            )

            # Step 4: Recalculate from pending tasks
            recalculated_expected = 0.0
            recalculated_variance = 0.0

            for pending_task in queue_state.pending_tasks.values():
                recalculated_expected += pending_task.expected_ms
                recalculated_variance += pending_task.error_ms ** 2

            # Override current values with recalculated ones
            queue_state.expected_ms = recalculated_expected
            queue_state.error_ms = sqrt(recalculated_variance) if recalculated_variance > 0 else 0.0

            logger.info(
                f"Recalculated queue state for instance {instance_uuid}: "
                f"expected={old_expected:.2f}ms -> {queue_state.expected_ms:.2f}ms (recalculated from pending tasks), "
                f"error={old_error:.2f}ms -> {queue_state.error_ms:.2f}ms, "
                f"tasks={queue_state.task_count}"
            )
        else:
            logger.info(
                f"Updated queue state on completion for instance {instance_uuid}: "
                f"expected={old_expected:.2f}ms -> {new_expected:.2f}ms (subtracted {execution_time:.2f}ms), "
                f"error={old_error:.2f}ms, tasks={queue_state.task_count}"
            )

        queue_state.last_update_time = time.time()

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
