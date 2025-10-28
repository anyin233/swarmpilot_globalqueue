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

import queue
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
try:
    from . import quantile_convolution as qc
except ImportError:
    # Fallback for testing environments
    import sys
    sys.path.insert(0, '/home/yanweiye/Project/swarmpilot/swarmpilot_globalqueue/src/scheduler/strategies')
    import quantile_convolution as qc


from .base import BaseStrategy, TaskInstance, TaskInstanceQueue, SelectionRequest
from ..models import EnqueueResponse
from ..predictor_client import PredictorClient

random.seed(42)

@dataclass
class TaskPrediction:
    """Single task prediction information cache"""
    task_id: str
    quantiles: List[float]
    
def sample_from_quantile_distribution(quantiles, values, n_samples=1000, seed=None):
    """
    Sample from a quantile distribution

    Parameters:
    -----------
    quantiles : array
        Quantile points
    values : array
        Corresponding values
    n_samples : int
        Number of samples
    seed : int, optional
        Random seed

    Returns:
    --------
    array : Sampled values
    """
    if seed is not None:
        np.random.seed(seed)

    # Generate uniformly distributed random quantiles
    random_quantiles = np.random.uniform(0, 1, n_samples)

    # Use linear interpolation to sample from the quantile distribution
    samples = np.interp(random_quantiles, quantiles, values)

    return samples

class QuantileProb:
    """Utility class for quantile distribution"""
    def __init__(self, quantiles: List[float], values: List[float] = None):
        self.quantiles = quantiles
        if values is None:
            self.values = [0.0] * len(self.quantiles)
        else:
            self.values = values

        
    def add(self, values: List[float]) -> None:
        assert len(values) == len(self.quantiles), "Number of quantile value not aligned with this one"
        # Assume input distribution is independ with this one
        # Sample -> Add -> Done
        samples_self = sample_from_quantile_distribution(self.quantiles, self.values)
        samples_other = sample_from_quantile_distribution(self.quantiles, values)
        
        sum_samples = samples_self + samples_other
        self.values = np.quantile(sum_samples, self.quantiles)
    
    def sub(self, values: List[float]):
        """
        Fixed subtraction method for quantile distributions.
        For independent random variables X and Y:
        X - Y = X + (-Y)

        The quantiles of -Y are related to Y by:
        Q_{-Y}(p) = -Q_Y(1-p)

        This means:
        - The p-th quantile of -Y equals the negative of the (1-p)-th quantile of Y
        """
        assert len(values) == len(self.quantiles), "Number of quantile value not aligned with this one"

        # Create the quantiles for -Y
        # For -Y: Q_{-Y}(p) = -Q_Y(1-p)
        neg_values = []
        neg_quantiles = []

        # Build the negative distribution's quantiles
        for p in self.quantiles:
            # For probability p, we need Q_{-Y}(p) = -Q_Y(1-p)
            # Find the value at probability 1-p in the original distribution
            neg_quantiles.append(p)

            # Find the corresponding 1-p in the original quantiles
            target_p = 1.0 - p

            # Interpolate to find Q_Y(1-p)
            if target_p in self.quantiles:
                # Exact match
                idx = self.quantiles.index(target_p)
                neg_values.append(-values[idx])
            else:
                # Need to interpolate
                # Find where target_p would be in the quantiles
                if target_p <= self.quantiles[0]:
                    # Extrapolate from the left tail
                    neg_values.append(-values[0])
                elif target_p >= self.quantiles[-1]:
                    # Extrapolate from the right tail
                    neg_values.append(-values[-1])
                else:
                    # Interpolate between two points
                    neg_val = -np.interp(target_p, self.quantiles, values)
                    neg_values.append(neg_val)

        # Now perform X + (-Y) using the convolution
        self.add(neg_values)

    def random_choice(self) -> float:
        """
        从当前的分位数分布中随机选取一个点
        使用逆变换采样（Inverse Transform Sampling）
        """
        # 生成均匀随机数 U ~ Uniform(0, 1)
        u = random.random()

        # 使用线性插值在quantiles中找到对应的值
        # np.interp(x, xp, fp): 在xp中找x的位置，返回对应fp的插值
        sampled_value = np.interp(u, self.quantiles, self.values)

        return sampled_value
        
@dataclass
class QueueState:
    """Local queue state tracking for scheduler-side prediction"""
    expected_ms: float = 0.0
    error_ms: float = 0.0
    dist: QuantileProb = None
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
        quantiles: List[float] = [0.25, 0.5, 0.75, 0.99],
        error_recalc_threshold: float = 2.0,
        debug_log_path: Optional[str] = None,
        get_debug_enabled: Optional[Callable[[], bool]] = None,
        fake_data_bypass: bool = False,
        fake_data_path: Optional[str] = None
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
            fake_data_bypass: Enable fake data bypass mode
            fake_data_path: Path to fake data directory
        """
        super().__init__(taskinstances)
        self.predictor_url = predictor_url
        self.predictor_timeout = predictor_timeout
        self.min_weight = max(0.0, min(1.0, min_weight))
        self.epsilon = max(0.1, epsilon)  # Ensure epsilon is at least 0.1ms
        self.error_recalc_threshold = error_recalc_threshold

        # PredictorClient instance (initialize first to check for fake data mode)
        self.predictor_client = PredictorClient(
            base_url=predictor_url,
            timeout=predictor_timeout,
            fake_data_bypass=fake_data_bypass,
            fake_data_path=fake_data_path
        )

        # If fake data mode is enabled, use fake percentiles from predictor
        if fake_data_bypass:
            fake_percentiles = self.predictor_client.get_fake_percentiles()
            if fake_percentiles:
                quantiles = fake_percentiles
                logger.info(
                    f"Fake data mode enabled: using predictor's fake percentiles: {quantiles}"
                )
            else:
                logger.warning(
                    f"Fake data mode enabled but no fake percentiles found, "
                    f"using provided quantiles: {quantiles}"
                )

        # Store quantiles for later use
        self.quantiles = quantiles

        # Track queue state for each TaskInstance
        self.queue_states: Dict[UUID, QueueState] = {}
        for ti in taskinstances:
            self.queue_states[ti.uuid] = QueueState()
            self.queue_states[ti.uuid].dist = QuantileProb(quantiles)

        # Debug logging configuration
        self.debug_log_path = debug_log_path or "./probabilistic_queue_debug.jsonl"
        self.get_debug_enabled = get_debug_enabled or (lambda: False)

        logger.info(
            f"Initialized ProbabilisticQueueStrategy with PredictorClient at {predictor_url}, "
            f"min_weight={min_weight}, epsilon={epsilon}ms, "
            f"quantiles={self.quantiles}, fake_data_mode={fake_data_bypass}"
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
    

    def _random_sample_based_shortest_queue_selection(self, dists: List[QuantileProb]):
        candidcates = []
        
        for i, dist in enumerate(dists):
            u = random.random()
            candidcates.append((dist.random_choice(), i))
        
        choice = sorted(candidcates, key=lambda x: x[0])
        
        return choice[0]

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
        candidcate_dists = []
        for ti, old_queue_info in candidates:
            try:
                # Get queue state from local tracking
                queue_state = self.queue_states.get(ti.uuid)
                if queue_state is None:
                    logger.warning(f"No queue state for TaskInstance {ti.uuid}, initializing")
                    queue_state = QueueState()
                    self.queue_states[ti.uuid] = queue_state

                # Use locally tracked queue size (task_count)
                # No need to query TaskInstance for real-time queue_size
                queue_size = queue_state.task_count

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
                candidcate_dists.append(queue_state.dist)

            except Exception as e:
                logger.warning(f"Failed to update queue info for TaskInstance {ti.uuid}: {e}")
                updated_candidates.append((ti, old_queue_info))
                candidcate_dists.append(queue_state.dist)

        
        # weights = self._calculate_shortest_queue_probabilities_optimized(candidcate_dists)

        # # Log weights for debugging
        # logger.debug(
        #     f"ProbabilisticQueueStrategy weights: " +
        #     ", ".join([
        #         f"{ti.uuid} (expected={qi.expected_ms:.1f}ms): {w:.4f}"
        #         for (ti, qi), w in zip(updated_candidates, weights)
        #     ])
        # )

        # # Probabilistically select based on weights
        # selected = random.choices(updated_candidates, weights=weights, k=1)[0]
        _, selected_index = self._random_sample_based_shortest_queue_selection(candidcate_dists)
        selected = updated_candidates[selected_index]

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
        task_id: str,
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
                # Create simple quantile approximation from expected time
                # Assume uniform distribution around expected value
                quantiles = [
                    task_expected * 0.75,  # 25th percentile
                    task_expected,         # 50th percentile (median)
                    task_expected * 1.25,  # 75th percentile
                    task_expected * 1.5    # 99th percentile
                ]
            else:
                # Use PredictorClient to get prediction
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
                    quantiles = prediction_response.results.quantile_predictions
                    
                else:
                    logger.warning("No quantile in prediction response")
                    return

            # Cache task prediction information for error recalculation
            queue_state = self.queue_states[selected_instance.uuid]

            queue_state.pending_tasks[task_id] = TaskPrediction(
                task_id=task_id,
                quantiles=quantiles,
            )

            # Update queue state using error propagation


            queue_state.dist.add(quantiles)
            queue_state.task_count += 1
            queue_state.last_update_time = time.time()

            logger.debug(
                f"Updated queue state for instance {selected_instance.uuid}: "
                f"quantiles={queue_state.dist.values}, tasks={queue_state.task_count}"
            )

        except Exception as e:
            logger.error(f"Failed to update queue state: {e}", exc_info=True)

    def clear_pending_tasks(self):
        """
        Clear all pending tasks from cache.
        This should be called when clearing all tasks from the system.
        """
        for queue_state in self.queue_states.values():
            queue_state.pending_tasks.clear()
            # Reset queue state to initial values
            queue_state.expected_ms = 0.0
            queue_state.error_ms = 0.0
            queue_state.task_count = 0

        logger.info(f"Cleared pending_tasks cache for all {len(self.queue_states)} instances")

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
        old_dist = queue_state.dist

        # Step 1: Remove completed task from cache (for recalculation)
        if task_id in queue_state.pending_tasks:
            tp = queue_state.pending_tasks.pop(task_id)
        else:
            tp = TaskPrediction(task_id, [0] * len(old_dist.quantiles), 0)
            logger.warning(
                f"Task {task_id} not found in pending_tasks cache for instance {instance_uuid}"
            )

        # Step 2: Subtract actual execution time (maintain current behavior)
        queue_state.dist.sub(tp.quantiles)
        queue_state.task_count = max(0, queue_state.task_count - 1)

        queue_state.last_update_time = time.time()
