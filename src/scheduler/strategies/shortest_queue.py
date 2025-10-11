"""
Shortest Queue Strategy

Strategy that selects the instance with shortest expected completion time,
maintaining local queue state for accurate prediction.

This is the most complex strategy, featuring:
- Integration with Predictor (both API and lookup table modes)
- Local queue state tracking
- Error propagation using variance theory
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from uuid import UUID
from loguru import logger
from math import sqrt
import time

from .base import BaseStrategy, TaskInstance, TaskInstanceQueue, SelectionRequest
from ..models import EnqueueResponse


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
    - Maintains local queue state tracking
    - Supports both lookup predictor and API predictor modes
    - Uses error propagation theory for queue state updates
    """

    def __init__(
        self,
        taskinstances: List[TaskInstance],
        predictor_url: str = "http://localhost:8100",
        predictor_timeout: float = 10.0,
        use_lookup_predictor: bool = False,
        prediction_file: str = "/home/yanweiye/Project/swarmpilot/swarmpilot_taskinstance/pred.json"
    ):
        """
        Initialize ShortestQueue strategy with predictor integration

        Args:
            taskinstances: List of available TaskInstances
            predictor_url: URL of the Predictor service
            predictor_timeout: Timeout for predictor requests in seconds
            use_lookup_predictor: If True, use lookup table instead of Predictor API
            prediction_file: Path to prediction JSON file
        """
        super().__init__(taskinstances)
        self.predictor_url = predictor_url
        self.predictor_timeout = predictor_timeout
        self.use_lookup_predictor = use_lookup_predictor
        self.prediction_file = prediction_file

        # Track queue state for each TaskInstance
        self.queue_states: Dict[UUID, QueueState] = {}
        for ti in taskinstances:
            self.queue_states[ti.uuid] = QueueState()

        # Track predictions for each enqueued request
        self.request_predictions: Dict[Tuple[UUID, str], Tuple[float, float]] = {}

        # Initialize predictor based on mode
        if self.use_lookup_predictor:
            from ..predictor import LookupPredictor
            self.lookup_predictor = LookupPredictor(prediction_file)
            logger.info(f"Initialized ShortestQueueStrategy with lookup predictor from {prediction_file}")
            stats = self.lookup_predictor.get_stats()
            logger.info(f"Lookup predictor stats: {stats['successful_records']} successful records")
        else:
            self.lookup_predictor = None
            logger.info("Initialized ShortestQueueStrategy with API predictor")

        # Lazy-initialized API predictor clients
        self._predictor_clients: Dict[tuple, Any] = {}

    def _get_predictor_client(self, request: SelectionRequest):
        """Get or create a predictor client for the given request"""
        import sys
        sys.path.append('/home/yanweiye/Project/swarmpilot/swarmpilot_taskinstance/src')
        from predictor_api_wrapper import SchedulerPredictorClient

        metadata = request.metadata
        model_name = metadata.get('model_name', request.model_type)
        hardware = metadata.get('hardware') or metadata.get('gpu_model', 'unknown')
        software_name = metadata.get('software_name', 'vllm')
        software_version = metadata.get('software_version', '0.1.0')

        signature = (request.model_type, model_name, hardware, software_name, software_version)

        if signature not in self._predictor_clients:
            self._predictor_clients[signature] = SchedulerPredictorClient(
                model_type=request.model_type,
                model_name=model_name,
                hardware=hardware,
                software_name=software_name,
                software_version=software_version,
                base_url=self.predictor_url,
                timeout=self.predictor_timeout
            )

        return self._predictor_clients[signature]

    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Select the instance with shortest expected completion time and smallest error
        """
        # Get fresh queue predictions
        updated_candidates = []
        for ti, old_queue_info in candidates:
            try:
                client = ti.instance
                status = client.get_status()
                queue_size = status.queue_size

                expected_ms = 0.0
                error_ms = 0.0

                if queue_size > 0:
                    try:
                        prediction = client.predict_queue()
                        expected_ms = prediction.expected_ms
                        error_ms = prediction.error_ms
                    except Exception as e:
                        logger.debug(f"Failed to get fresh prediction for TaskInstance {ti.uuid}: {e}")
                        expected_ms = old_queue_info.expected_ms
                        error_ms = old_queue_info.error_ms

                updated_queue_info = TaskInstanceQueue(
                    expected_ms=expected_ms,
                    error_ms=error_ms,
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

        logger.debug(
            f"ShortestQueueStrategy selected: instance {selected[0].uuid} "
            f"with expected_ms={selected[1].expected_ms}, error_ms={selected[1].error_ms}"
        )

        return selected

    def update_queue(
        self,
        selected_instance: TaskInstance,
        request: SelectionRequest,
        enqueue_response: EnqueueResponse
    ):
        """
        Update queue state after task enqueue

        Uses real execution time if provided, otherwise gets prediction
        """
        try:
            # Check if real execution time is provided
            if 'server_time_cost' in request.metadata:
                task_expected = float(request.metadata['server_time_cost'])
                task_error = sqrt(task_expected * 0.05)
                logger.info(f"Using real execution time: {task_expected:.2f}ms")
            else:
                # Get prediction
                if self.use_lookup_predictor:
                    prediction_response = self.lookup_predictor.predict(
                        model_type=request.model_type,
                        metadata=request.metadata
                    )
                    if prediction_response is None:
                        logger.warning(f"No prediction found, skipping queue state update")
                        return
                    quantiles = self._extract_quantile_predictions(prediction_response)
                else:
                    # Use API predictor (simplified for now)
                    logger.warning("API predictor mode not fully implemented in refactored version")
                    return

                summary = self._compute_distribution_summary(quantiles)
                if not summary or 'expected_ms' not in summary:
                    logger.warning("Could not get valid prediction")
                    return

                task_expected = summary['expected_ms']
                task_error = summary['error_ms']

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
            logger.error(f"Failed to update queue state: {e}")

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
    def _extract_quantile_predictions(response: Dict[str, Any]) -> Dict[str, float]:
        """Extract quantile predictions from predictor response"""
        from collections.abc import Sequence

        quantiles = response.get("quantiles")
        predictions = response.get("quantile_predictions")

        if not isinstance(quantiles, Sequence) or isinstance(quantiles, (str, bytes)):
            return {}
        if not isinstance(predictions, Sequence) or isinstance(predictions, (str, bytes)):
            return {}

        quantile_map: Dict[str, float] = {}
        for index, quantile in enumerate(quantiles):
            if index >= len(predictions):
                break

            try:
                quantile_key = f"{float(quantile):.6g}"
            except (TypeError, ValueError):
                quantile_key = str(quantile)

            prediction_value = predictions[index]
            try:
                quantile_map[quantile_key] = float(prediction_value)
            except (TypeError, ValueError):
                continue

        return quantile_map

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
