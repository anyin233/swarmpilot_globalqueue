"""
Probabilistic Queue Strategy

Strategy that probabilistically selects instances based on expected queue time.
Uses local queue state tracking (like ShortestQueueStrategy) but converts
expected times to selection probabilities instead of deterministically selecting
the shortest queue.

Features:
- Maintains local queue state with expected_ms and error_ms
- Uses PredictorClient for execution time prediction
- Converts queue expected times to selection probabilities
- Shorter queues have higher probability of being selected
"""

from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from uuid import UUID
from loguru import logger
from math import sqrt
import random
import time
import json
from datetime import datetime
from pathlib import Path
import numpy as np
from scipy import stats
from scipy import integrate


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


class ProbabilisticQueueStrategy(BaseStrategy):
    """
    Strategy that probabilistically selects instances based on expected queue time

    This strategy maintains local queue state (like ShortestQueueStrategy) and
    converts expected waiting times into selection probabilities. Shorter queues
    have higher probability of being selected, creating a probabilistic load
    balancing effect while avoiding the rigid determinism of always picking
    the shortest queue.

    Features:
    - Maintains local queue state tracking with expected_ms and error_ms
    - Uses PredictorClient for execution time prediction
    - Uses error propagation theory for queue state updates
    - Converts expected_ms to selection weights: weight = 1 / (expected_ms + epsilon)
    - Applies minimum weight floor to prevent completely ignoring busy instances
    """

    def __init__(
        self,
        taskinstances: List[TaskInstance],
        predictor_url: str = "http://localhost:8100",
        predictor_timeout: float = 10.0,
        min_weight: float = 0.01,
        epsilon: float = 1.0,
        error_recalc_threshold: float = 2.0,
        debug_log_path: Optional[str] = None,
        get_debug_enabled: Optional[Callable[[], bool]] = None
    ):
        """
        Initialize ProbabilisticQueue strategy with PredictorClient

        Args:
            taskinstances: List of available TaskInstances
            predictor_url: URL of the Predictor service
            predictor_timeout: Timeout for predictor requests in seconds
            min_weight: Minimum weight for any queue (default: 0.01)
            epsilon: Small constant added to expected_ms to avoid division by zero (default: 1.0ms)
            error_recalc_threshold: Error recalculation threshold (default: 2.0)
                When error_ms > threshold * expected_ms, trigger recalculation
            debug_log_path: Path to debug log file (default: "./probabilistic_queue_debug.jsonl")
            get_debug_enabled: Callable to check if debug logging is enabled
        """
        super().__init__(taskinstances)
        self.predictor_url = predictor_url
        self.predictor_timeout = predictor_timeout
        self.min_weight = max(0.0, min(1.0, min_weight))
        self.epsilon = max(0.1, epsilon)  # Ensure epsilon is at least 0.1ms
        self.error_recalc_threshold = error_recalc_threshold

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
        self.debug_log_path = debug_log_path or "./probabilistic_queue_debug.jsonl"
        self.get_debug_enabled = get_debug_enabled or (lambda: False)

        logger.info(
            f"Initialized ProbabilisticQueueStrategy with PredictorClient at {predictor_url}, "
            f"min_weight={min_weight}, epsilon={epsilon}ms"
        )

    def _write_debug_log(self, queue_states_snapshot: Dict[str, Dict[str, float]]):
        """Write debug log entry to JSON file"""
        try:
            if not self.get_debug_enabled():
                return

            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "strategy": "probabilistic",
                "queue_states": queue_states_snapshot
            }

            # Append to JSONL file
            Path(self.debug_log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.debug_log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

        except Exception as e:
            logger.warning(f"Failed to write debug log: {e}")
    
    def _calculate_shortest_queue_probabilities_optimized(self, queues):
        n_queues = len(queues)
        probabilities = np.zeros(n_queues)

        for i, q in enumerate(queues):
            A_i = q[0]
            E_i = q[1]

            # Handle edge case: if E_i is zero or very small, use epsilon
            if E_i < self.epsilon:
                E_i = self.epsilon

            # 使用标准化变量 z = (x - A_i) / E_i
            def integrand_standardized(z):
                # 标准正态分布的PDF
                pdf_std = stats.norm.pdf(z)

                # x = A_i + E_i * z
                x = A_i + E_i * z

                # 连乘项
                product = 1.0
                for j in range(n_queues):
                    if j != i:
                        A_j = queues[j][0]  # Fixed: should access queues[j], not q
                        E_j = queues[j][1]  # Fixed: should access queues[j], not q

                        # Handle edge case: if E_j is zero or very small, use epsilon
                        if E_j < self.epsilon:
                            E_j = self.epsilon

                        # P(l_j > x) = Gamma((A_j - x) / E_j)
                        standardized_value = (A_j - x) / E_j
                        tail_prob = stats.norm.cdf(standardized_value)
                        product *= tail_prob

                return pdf_std * product

            # 积分区间：[-1, 1] (标准化后)
            result, error = integrate.quad(integrand_standardized, -1, 1)
            probabilities[i] = result

        return probabilities

    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Probabilistically select instance based on expected queue time

        Uses locally maintained queue states instead of querying TaskInstance.
        Converts expected_ms to selection weights: weight = 1 / (expected_ms + epsilon)

        Args:
            candidates: List of candidate instances with queue info
            request: Selection request (not used in this strategy)

        Returns:
            Probabilistically selected instance with higher probability for shorter queues
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

        queue_info = [(q.expected_ms, q.error_ms) for ti, q in updated_candidates]
        
        weights = self._calculate_shortest_queue_probabilities_optimized(queue_info)

        # Log weights for debugging
        logger.debug(
            f"ProbabilisticQueueStrategy weights: " +
            ", ".join([
                f"{ti.uuid} (expected={qi.expected_ms:.1f}ms): {w:.4f}"
                for (ti, qi), w in zip(updated_candidates, weights)
            ])
        )

        # Probabilistically select based on weights
        selected = random.choices(updated_candidates, weights=weights, k=1)[0]

        logger.info(
            f"ProbabilisticQueueStrategy selected: instance {selected[0].uuid} "
            f"with expected_ms={selected[1].expected_ms:.2f}ms, error_ms={selected[1].error_ms:.2f}ms"
        )

        # Write debug log if enabled
        if self.get_debug_enabled():
            queue_states_snapshot = {}
            for (ti, queue_info), weight in zip(updated_candidates, weights):
                queue_states_snapshot[str(ti.uuid)] = {
                    "expected_ms": queue_info.expected_ms,
                    "error_ms": queue_info.error_ms,
                    "queue_size": queue_info.queue_size,
                    "weight": weight,
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
        the expectation and error to the target queue (same as ShortestQueueStrategy)
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

                # Check prediction status
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
                    logger.warning("No expect/error in prediction response")
                    return

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
