"""
Weighted Strategy

Strategy that considers both queue length and error margin when selecting instances.
"""

from typing import List
from loguru import logger

from .base import BaseStrategy, TaskInstance, TaskInstanceQueue, SelectionRequest
from ..models import EnqueueResponse


class WeightedStrategy(BaseStrategy):
    """
    Strategy that considers both queue length and error margin

    This strategy calculates a weighted score based on expected time
    and uncertainty (error margin) to make more robust selections.

    This strategy fetches queue predictions from TaskInstances during filtering.
    """

    def __init__(self, taskinstances: List[TaskInstance], error_weight: float = 0.5):
        """
        Initialize weighted strategy

        Args:
            taskinstances: List of available TaskInstances
            error_weight: Weight for error margin (0-1), higher means more conservative
        """
        super().__init__(taskinstances)
        self.error_weight = max(0.0, min(1.0, error_weight))

    def filter_instances(self, request: SelectionRequest) -> List[tuple[TaskInstance, TaskInstanceQueue]]:
        """
        Override filter_instances to include queue prediction for weighted selection

        This method extends the base filter_instances by fetching queue predictions
        from TaskInstances, which are needed for weighted scoring.
        """
        # Get basic filtered candidates from base class
        candidates = super().filter_instances(request)

        # Enhance candidates with queue predictions
        enhanced_candidates = []
        for ti, queue_info in candidates:
            try:
                # Get queue prediction if queue is not empty
                expected_ms = 0.0
                error_ms = 0.0

                if queue_info.queue_size > 0:
                    try:
                        client = ti.instance
                        prediction = client.predict_queue()
                        expected_ms = prediction.expected_ms
                        error_ms = prediction.error_ms
                        logger.debug(
                            f"WeightedStrategy prediction for {ti.uuid}: "
                            f"expected={expected_ms:.2f}ms, error={error_ms:.2f}ms"
                        )
                    except Exception as e:
                        logger.debug(f"Failed to get prediction for TaskInstance {ti.uuid}: {e}")

                # Create enhanced queue info with prediction
                enhanced_queue_info = TaskInstanceQueue(
                    expected_ms=expected_ms,
                    error_ms=error_ms,
                    queue_size=queue_info.queue_size,
                    model_type=queue_info.model_type,
                    instance_id=queue_info.instance_id,
                    ti_uuid=ti.uuid
                )

                enhanced_candidates.append((ti, enhanced_queue_info))

            except Exception as e:
                logger.warning(f"Failed to enhance queue info for TaskInstance {ti.uuid}: {e}")
                # Keep original if enhancement fails
                enhanced_candidates.append((ti, queue_info))

        return enhanced_candidates

    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Select instance based on weighted score of expected time and error
        """
        # Calculate weighted scores
        scores = []
        for instance, queue_info in candidates:
            # Score = expected_ms + (error_weight * error_ms)
            # Higher error_weight means we're more conservative about uncertainty
            score = queue_info.expected_ms + (self.error_weight * queue_info.error_ms)
            scores.append((score, instance, queue_info))

        # Select instance with minimum score
        selected = min(scores, key=lambda x: x[0])

        logger.debug(
            f"WeightedStrategy selected: instance {selected[1].uuid} "
            f"with score={selected[0]:.2f} (expected={selected[2].expected_ms}, "
            f"error={selected[2].error_ms})"
        )

        return selected[1], selected[2]

    def update_queue(
        self,
        selected_instance: TaskInstance,
        request: SelectionRequest,
        enqueue_response: EnqueueResponse
    ):
        """
        WeightedStrategy does not maintain queue state
        """
        pass
