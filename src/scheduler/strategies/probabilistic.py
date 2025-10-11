"""
Probabilistic Queue Strategy

Strategy that probabilistically selects instances based on queue length.
Shorter queues have higher probability of being selected.
"""

from typing import List
from loguru import logger
import random

from .base import BaseStrategy, TaskInstance, TaskInstanceQueue, SelectionRequest
from ..models import EnqueueResponse


class ProbabilisticQueueStrategy(BaseStrategy):
    """
    Strategy that probabilistically selects instances based on queue length

    This strategy uses queue lengths from the predict interface to calculate
    selection probabilities. Shorter queues have higher probability of being
    selected, creating a probabilistic load balancing effect.

    The weight for each instance is calculated as: 1 / (queue_size + 1)
    This ensures:
    - Empty queues (size=0) have weight 1.0
    - Longer queues have progressively lower weights
    - No division by zero
    """

    def __init__(self, taskinstances: List[TaskInstance], min_weight: float = 0.1):
        """
        Initialize probabilistic queue strategy

        Args:
            taskinstances: List of available TaskInstances
            min_weight: Minimum weight for any queue (prevents completely ignoring busy instances)
        """
        super().__init__(taskinstances)
        self.min_weight = max(0.0, min(1.0, min_weight))

    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Probabilistically select instance based on inverse queue length

        This method:
        1. Gets fresh queue predictions for all candidates
        2. Calculates weights inversely proportional to queue size
        3. Uses random.choices to select based on these weights

        Args:
            candidates: List of candidate instances with queue info
            request: Selection request (not used in this strategy)

        Returns:
            Randomly selected instance with probability based on queue length
        """
        # Get fresh queue predictions for all candidates
        updated_candidates = []
        for ti, old_queue_info in candidates:
            try:
                client = ti.instance
                status = client.get_status()
                queue_size = status.queue_size

                # Default values
                expected_ms = 0.0
                error_ms = 0.0

                if queue_size > 0:
                    try:
                        prediction = client.predict_queue()
                        expected_ms = prediction.expected_ms
                        error_ms = prediction.error_ms
                    except Exception as e:
                        logger.debug(f"Failed to get fresh prediction for TaskInstance {ti.uuid}: {e}")
                        # Use old values if fresh query fails
                        expected_ms = old_queue_info.expected_ms
                        error_ms = old_queue_info.error_ms

                # Create updated queue info
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
                # Keep the old info if update fails
                updated_candidates.append((ti, old_queue_info))

        # Calculate weights based on inverse queue length
        weights = []
        for ti, queue_info in updated_candidates:
            # Weight = 1 / (queue_size + 1)
            # Add 1 to avoid division by zero and ensure empty queues have finite weight
            weight = 1.0 / (queue_info.queue_size + 1)
            # Apply minimum weight floor
            weight = max(weight, self.min_weight)
            weights.append(weight)

        # Log weights for debugging
        logger.debug(
            f"ProbabilisticQueueStrategy weights: " +
            ", ".join([
                f"{ti.uuid} (q={qi.queue_size}): {w:.3f}"
                for (ti, qi), w in zip(updated_candidates, weights)
            ])
        )

        # Probabilistically select based on weights
        selected = random.choices(updated_candidates, weights=weights, k=1)[0]

        logger.debug(
            f"ProbabilisticQueueStrategy selected: instance {selected[0].uuid} "
            f"(queue_size={selected[1].queue_size}, expected={selected[1].expected_ms}ms)"
        )

        return selected

    def update_queue(
        self,
        selected_instance: TaskInstance,
        request: SelectionRequest,
        enqueue_response: EnqueueResponse
    ):
        """
        ProbabilisticQueueStrategy does not maintain queue state
        """
        pass
