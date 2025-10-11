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
