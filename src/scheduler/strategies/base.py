"""
Base Strategy Classes and Data Structures

This module provides the base classes and data structures for TaskInstance
selection strategies in the Scheduler system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from uuid import UUID
from loguru import logger

# Import from parent package using relative imports
from ..client import TaskInstanceClient
from ..models import EnqueueResponse


@dataclass
class TaskInstance:
    """TaskInstance wrapper with UUID and client"""
    uuid: UUID
    instance: TaskInstanceClient
    model_type: Optional[str] = None  # Cached model type
    instance_id: Optional[str] = None  # Cached instance_id


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
    model_type: str  # Model type to match
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

        This method filters TaskInstances using cached information (model_type, instance_id)
        that was populated during registration. It builds a list of candidates that match
        the requested model_type WITHOUT querying each instance.

        NOTE: This base implementation does NOT fetch queue predictions or check replicas_running.
        Subclasses that need queue prediction or runtime status should override this method
        or fetch predictions in their _select_from_candidates method.

        Args:
            request: Selection request containing model_type and other info

        Returns:
            List of (TaskInstance, TaskInstanceQueue) tuples that match the request

        Raises:
            RuntimeError: If no matching instances are found
        """
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]] = []

        # Iterate through all Task Instances using cached information
        for ti in self.taskinstances:
            try:
                # Filter by cached model type (no API call needed)
                if ti.model_type != request.model_type:
                    continue

                # Use cached instance_id (set during registration)
                # If instance_id is not cached, skip this instance
                if not ti.instance_id:
                    logger.warning(
                        f"TaskInstance {ti.uuid} has no cached instance_id, "
                        f"skipping (was it registered properly?)"
                    )
                    continue

                # Create basic queue info without prediction or queue_size
                # Subclasses can populate expected_ms/error_ms/queue_size if needed
                queue_info = TaskInstanceQueue(
                    expected_ms=0.0,
                    error_ms=0.0,
                    queue_size=0,  # Not tracked in filter phase
                    model_type=ti.model_type,
                    instance_id=ti.instance_id,
                    ti_uuid=ti.uuid
                )

                candidates.append((ti, queue_info))

            except Exception as e:
                logger.warning(f"Failed to process TaskInstance {ti.uuid}: {e}")
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

    @abstractmethod
    def update_queue(
        self,
        selected_instance: TaskInstance,
        request: SelectionRequest,
        task_id: str,
    ):
        """
        Update queue state after a task has been enqueued

        This method is called by the Scheduler after successfully enqueuing a task
        to a TaskInstance. It should update internal queue state tracking based on:
        1. Prediction of task execution time (from Predictor)
        2. Current queue state

        Args:
            selected_instance: The TaskInstance that was selected and received the task
            request: The original selection request containing task information
            enqueue_response: Response from the TaskInstance enqueue operation
        """
        pass

    def update_queue_on_completion(self, instance_uuid: UUID, task_id: str, execution_time: float):
        """
        Update queue state when a task completes (optional)

        This method is called when the Scheduler receives task completion notification.
        It updates the queue state by subtracting the predicted expected value (not the actual execution time).

        Args:
            instance_uuid: UUID of the TaskInstance where the task completed
            task_id: ID of the completed task
            execution_time: (Optional)Actual execution time in milliseconds (used for logging/metrics only)

        Note:
            Default implementation does nothing. Strategies that maintain queue state
            should override this method.
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
