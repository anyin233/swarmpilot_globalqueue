"""
Task Instance Selection Strategies (Refactored for port-less architecture)

This module provides different strategies for selecting the optimal TaskInstance
for incoming tasks in the Scheduler system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from uuid import UUID
from loguru import logger
import random

from task_instance_client_refactored import TaskInstanceClient


@dataclass
class TaskInstance:
    """TaskInstance wrapper with UUID and client"""
    uuid: UUID
    instance: TaskInstanceClient
    model_type: Optional[str] = None  # Cached model type


@dataclass
class TaskInstanceQueue:
    """Task instance queue information"""
    expected_ms: float
    error_ms: float
    queue_size: int
    model_type: str
    instance_id: str
    ti_uuid: UUID

    def __lt__(self, other):
        """Comparison for priority queue (shorter expected_ms has higher priority)"""
        return self.expected_ms < other.expected_ms


@dataclass
class SelectionRequest:
    """Request information for queue selection"""
    model_type: str  # Changed from model_id to model_type
    input_data: Dict[str, Any]
    metadata: Dict[str, Any]


@dataclass
class SelectionResult:
    """Result of queue selection"""
    selected_instance: TaskInstance
    queue_info: TaskInstanceQueue


class BaseStrategy(ABC):
    """
    Base class for TaskInstance selection strategies

    A strategy is responsible for:
    1. Filtering available instances based on the request
    2. Selecting the optimal instance from filtered candidates
    """

    def __init__(self, taskinstances: List[TaskInstance]):
        """
        Initialize strategy with available TaskInstances

        Args:
            taskinstances: List of available TaskInstance objects
        """
        self.taskinstances = taskinstances

    def filter_instances(self, request: SelectionRequest) -> List[tuple[TaskInstance, TaskInstanceQueue]]:
        """
        Filter available instances based on request requirements

        This method queries all TaskInstances and builds a list of candidates
        that match the requested model_type.

        Args:
            request: Selection request containing model_type and other info

        Returns:
            List of (TaskInstance, TaskInstanceQueue) tuples that match the request

        Raises:
            RuntimeError: If no matching instances are found
        """
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]] = []

        # Iterate through all Task Instances
        for ti in self.taskinstances:
            client = ti.instance
            try:
                # Get instance status
                status = client.get_status()

                # Cache model type
                ti.model_type = status.model_type

                # Filter by model type
                if status.model_type != request.model_type:
                    continue

                # Skip if no models are running
                if status.replicas_running == 0:
                    logger.debug(f"TaskInstance {ti.uuid} has no running replicas, skipping")
                    continue

                # Get queue prediction
                queue_size = status.queue_size
                expected_ms = 0.0
                error_ms = 0.0

                if queue_size > 0:
                    try:
                        prediction = client.predict_queue()
                        expected_ms = prediction.expected_ms
                        error_ms = prediction.error_ms
                    except Exception as e:
                        logger.debug(f"Failed to get prediction for TaskInstance {ti.uuid}: {e}")

                # Create queue info
                queue_info = TaskInstanceQueue(
                    expected_ms=expected_ms,
                    error_ms=error_ms,
                    queue_size=queue_size,
                    model_type=status.model_type,
                    instance_id=status.instance_id,
                    ti_uuid=ti.uuid
                )

                candidates.append((ti, queue_info))

            except Exception as e:
                logger.warning(f"Failed to query TaskInstance {ti.uuid}: {e}")
                continue

        if not candidates:
            raise RuntimeError(f"No available instances for model type {request.model_type}")

        logger.debug(f"Filtered {len(candidates)} candidate instance(s) for model type {request.model_type}")
        return candidates

    @abstractmethod
    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Select the optimal instance from filtered candidates

        This is the core selection logic that must be implemented by subclasses.

        Args:
            candidates: List of filtered candidate instances with queue info
            request: Selection request with additional context

        Returns:
            Selected (TaskInstance, TaskInstanceQueue) tuple
        """
        pass

    def select(self, request: SelectionRequest) -> SelectionResult:
        """
        Main entry point: select the optimal instance for the request

        This method:
        1. Filters available instances based on request
        2. Selects the best instance using strategy-specific logic
        3. Returns the selected instance and queue information

        Args:
            request: Selection request containing model_type and metadata

        Returns:
            SelectionResult with selected instance and queue info

        Raises:
            RuntimeError: If no suitable instance found
        """
        # Step 1: Filter instances based on request
        candidates = self.filter_instances(request)

        # Step 2: Select optimal instance using strategy logic
        selected_instance, queue_info = self._select_from_candidates(candidates, request)

        logger.info(
            f"Selected instance: {selected_instance.uuid} "
            f"(expected: {queue_info.expected_ms}ms, queue_size: {queue_info.queue_size})"
        )

        return SelectionResult(
            selected_instance=selected_instance,
            queue_info=queue_info
        )


class ShortestQueueStrategy(BaseStrategy):
    """
    Strategy that selects the instance with shortest expected completion time and smallest error

    This strategy first queries all target queues to get current expected execution time
    and error, then selects the instance with both the lowest expected_ms value and
    smallest error_ms, which typically means the instance with the least workload
    and most predictable performance.
    """

    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Select the instance with the shortest expected completion time and smallest error

        Before selection, this method:
        1. Queries all target queues for current expected time and error
        2. Selects the queue with minimum expected time
        3. Among queues with similar expected times, prefers the one with smallest error

        Args:
            candidates: List of candidate instances with queue info
            request: Selection request (not used in this strategy)

        Returns:
            Instance with minimum expected_ms and minimum error_ms
        """
        # First, get fresh queue predictions for all candidates
        updated_candidates = []
        for ti, old_queue_info in candidates:
            try:
                # Get fresh queue prediction
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
                        logger.info(f"Got Predition: A = {expected_ms} E = {error_ms}")
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

        # Select instance with minimum expected_ms and minimum error_ms
        # Use a composite key that prioritizes expected_ms first, then error_ms
        selected = min(updated_candidates, key=lambda x: (x[1].expected_ms, x[1].error_ms))

        logger.debug(
            f"ShortestQueueStrategy selected: instance {selected[0].uuid} "
            f"with expected_ms={selected[1].expected_ms}, error_ms={selected[1].error_ms}"
        )

        return selected


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