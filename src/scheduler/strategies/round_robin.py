"""
Round Robin Strategy

Strategy that selects instances in a round-robin manner, distributing tasks
evenly across all available instances regardless of their current load.
"""

from typing import List
from loguru import logger

from .base import BaseStrategy, TaskInstance, TaskInstanceQueue, SelectionRequest
from ..models import EnqueueResponse


class RoundRobinStrategy(BaseStrategy):
    """
    Strategy that selects instances in a round-robin manner

    This strategy distributes tasks evenly across all available instances
    regardless of their current load.
    """

    def __init__(self, taskinstances: List[TaskInstance]):
        super().__init__(taskinstances)
        self.current_index = 0

    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Select the next instance in round-robin order
        """
        # Ensure current_index is within bounds
        index = self.current_index % len(candidates)
        selected = candidates[index]

        # Update index for next selection
        self.current_index = (self.current_index + 1) % len(candidates)

        logger.debug(
            f"RoundRobinStrategy selected: instance {selected[0].uuid} "
            f"(index: {index}/{len(candidates)})"
        )

        return selected

    def update_queue(
        self,
        selected_instance: TaskInstance,
        request: SelectionRequest,
        enqueue_response: EnqueueResponse
    ):
        """
        RoundRobinStrategy does not maintain queue state
        """
        pass
