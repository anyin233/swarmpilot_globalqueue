"""
Task Instance Selection Strategies

This module provides different strategies for selecting the optimal TaskInstance
and queue for incoming tasks in the GlobalQueue system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from uuid import UUID
from loguru import logger

from task_instance_client import TaskInstanceClient, Task


@dataclass
class TaskInstance:
    """TaskInstance wrapper with UUID and client"""
    uuid: UUID
    instance: TaskInstanceClient


@dataclass
class ModelMsgQueue:
    """Model message queue information"""
    expected_ms: float
    error_ms: float
    length: int
    model_name: str
    port: int
    ti_uuid: UUID

    def __lt__(self, other):
        """Comparison for priority queue (shorter expected_ms has higher priority)"""
        return self.expected_ms < other.expected_ms


@dataclass
class SelectionRequest:
    """Request information for queue selection"""
    model_id: str
    input_data: Dict[str, Any]
    input_features: Dict[str, Any]


@dataclass
class SelectionResult:
    """Result of queue selection"""
    selected_queue: ModelMsgQueue
    task_instance: TaskInstance


class BaseStrategy(ABC):
    """
    Base class for TaskInstance selection strategies

    A strategy is responsible for:
    1. Filtering available queues based on the request
    2. Selecting the optimal queue from filtered candidates
    """

    def __init__(self, taskinstances: List[TaskInstance]):
        """
        Initialize strategy with available TaskInstances

        Args:
            taskinstances: List of available TaskInstance objects
        """
        self.taskinstances = taskinstances

    def filter_queues(self, request: SelectionRequest) -> List[ModelMsgQueue]:
        """
        Filter available queues based on request requirements

        This method queries all TaskInstances and builds a list of candidate queues
        that match the requested model_id.

        Args:
            request: Selection request containing model_id and other info

        Returns:
            List of ModelMsgQueue objects that match the request

        Raises:
            RuntimeError: If no matching queues are found
        """
        candidate_queues: List[ModelMsgQueue] = []

        # Iterate through all Task Instances
        for ti in self.taskinstances:
            client = ti.instance
            try:
                # Get all models on this Task Instance
                models = client.list_models().models

                for model_info in models:
                    model_name = model_info.model
                    port = model_info.port

                    # Filter by model_id (model_name should match model_id)
                    if model_name != request.model_id:
                        continue

                    # Try to get queue status
                    try:
                        queue_status = client.get_queue_status(port=port)
                        queue_size = queue_status.queue_size

                        # If queue has tasks, get prediction information
                        if queue_size > 0:
                            prediction = client.predict_queue(port=port)
                            expected_ms = prediction.expected_ms
                            error_ms = prediction.error_ms
                        else:
                            # If queue is empty, use default values
                            expected_ms = 0.0
                            error_ms = 0.0

                    except Exception as e:
                        # If queue doesn't exist or other error, use default values
                        logger.debug(f"Queue for {model_name}:{port} not initialized yet: {e}")
                        queue_size = 0
                        expected_ms = 0.0
                        error_ms = 0.0

                    # Create queue object and add to candidates
                    queue_obj = ModelMsgQueue(
                        expected_ms=expected_ms,
                        error_ms=error_ms,
                        length=queue_size,
                        model_name=model_name,
                        port=port,
                        ti_uuid=ti.uuid
                    )
                    candidate_queues.append(queue_obj)

            except Exception as e:
                logger.warning(f"Failed to query TaskInstance {ti.uuid}: {e}")
                continue

        if not candidate_queues:
            raise RuntimeError(f"No available queues for model {request.model_id}")

        logger.debug(f"Filtered {len(candidate_queues)} candidate queue(s) for model {request.model_id}")
        return candidate_queues

    @abstractmethod
    def _select_from_candidates(self, candidates: List[ModelMsgQueue], request: SelectionRequest) -> ModelMsgQueue:
        """
        Select the optimal queue from filtered candidates

        This is the core selection logic that must be implemented by subclasses.

        Args:
            candidates: List of filtered candidate queues
            request: Selection request with additional context

        Returns:
            Selected ModelMsgQueue object
        """
        pass

    def select(self, request: SelectionRequest) -> SelectionResult:
        """
        Main entry point: select the optimal queue for the request

        This method:
        1. Filters available queues based on request
        2. Selects the best queue using strategy-specific logic
        3. Returns the selected queue and corresponding TaskInstance

        Args:
            request: Selection request containing model_id and features

        Returns:
            SelectionResult with selected queue and TaskInstance

        Raises:
            RuntimeError: If no suitable queue found or TaskInstance lookup fails
        """
        # Step 1: Filter queues based on request
        candidates = self.filter_queues(request)

        # Step 2: Select optimal queue using strategy logic
        selected_queue = self._select_from_candidates(candidates, request)

        # Step 3: Find the corresponding TaskInstance
        task_instance = None
        for ti in self.taskinstances:
            if ti.uuid == selected_queue.ti_uuid:
                task_instance = ti
                break

        if task_instance is None:
            raise RuntimeError(f"TaskInstance {selected_queue.ti_uuid} not found")

        logger.info(
            f"Selected queue: {selected_queue.model_name}:{selected_queue.port} "
            f"at TaskInstance {task_instance.uuid} "
            f"(expected: {selected_queue.expected_ms}ms, queue_size: {selected_queue.length})"
        )

        return SelectionResult(
            selected_queue=selected_queue,
            task_instance=task_instance
        )


class ShortestQueueStrategy(BaseStrategy):
    """
    Strategy that selects the queue with shortest expected completion time

    This strategy prioritizes queues with the lowest expected_ms value,
    which typically means the queue with the least workload.
    """

    def _select_from_candidates(self, candidates: List[ModelMsgQueue], request: SelectionRequest) -> ModelMsgQueue:
        """
        Select the queue with the shortest expected completion time

        Args:
            candidates: List of candidate queues
            request: Selection request (not used in this strategy)

        Returns:
            Queue with minimum expected_ms
        """
        # Sort by expected_ms and select the one with shortest time
        selected = min(candidates, key=lambda q: q.expected_ms)

        logger.debug(
            f"ShortestQueueStrategy selected: {selected.model_name}:{selected.port} "
            f"with expected_ms={selected.expected_ms}"
        )

        return selected


class RoundRobinStrategy(BaseStrategy):
    """
    Strategy that selects the queue in a round-robin manner

    This strategy selects the queue in a round-robin manner,
    which means the queue with the shortest expected completion time.
    """
    def __init__(self, taskinstances: List[TaskInstance]):
        super().__init__(taskinstances)
        self.current_index = 0

    def _select_from_candidates(self, candidates: List[ModelMsgQueue], request: SelectionRequest) -> ModelMsgQueue:
        """
        Select the queue in a round-robin manner
        """
        # Ensure current_index is within bounds of current candidates list
        index = self.current_index % len(candidates)
        selected = candidates[index]
        self.current_index = (self.current_index + 1) % len(candidates)
        return selected