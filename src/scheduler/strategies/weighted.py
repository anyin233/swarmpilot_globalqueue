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

        # Track task count for each TaskInstance (for tie-breaking)
        from typing import Dict
        from uuid import UUID
        self.task_counts: Dict[UUID, int] = {}
        for ti in taskinstances:
            self.task_counts[ti.uuid] = 0

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
            task_count = self.task_counts.get(instance.uuid, 0)
            scores.append((score, task_count, str(instance.uuid), instance, queue_info))

        # Select instance with minimum score, using task_count and UUID for tie-breaking
        # This ensures fair distribution when scores are equal
        selected = min(scores, key=lambda x: (x[0], x[1], x[2]))

        logger.debug(
            f"WeightedStrategy selected: instance {selected[3].uuid} "
            f"with score={selected[0]:.2f} (expected={selected[4].expected_ms}, "
            f"error={selected[4].error_ms}), task_count={selected[1]}"
        )

        return selected[3], selected[4]

    def update_queue(
        self,
        selected_instance: TaskInstance,
        request: SelectionRequest,
        enqueue_response: EnqueueResponse
    ):
        """
        Update task count for the selected instance
        """
        if selected_instance.uuid in self.task_counts:
            self.task_counts[selected_instance.uuid] += 1

    def update_queue_on_completion(self, instance_uuid, task_id: str, execution_time: float):
        """
        Decrease task count when task completes
        """
        if instance_uuid in self.task_counts:
            self.task_counts[instance_uuid] = max(0, self.task_counts[instance_uuid] - 1)
