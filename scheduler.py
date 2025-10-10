"""
SwarmPilot Scheduler (formerly GlobalQueue)

This is the refactored scheduler that works with TaskInstances instead of individual model ports.
"""

from pydantic import BaseModel
from loguru import logger
from typing import Dict, Any, List, Optional
from uuid import uuid4, UUID
import yaml

from task_instance_client_refactored import TaskInstanceClient
from strategy_refactored import (
    BaseStrategy,
    ShortestQueueStrategy,
    RoundRobinStrategy,
    WeightedStrategy,
    ProbabilisticQueueStrategy,
    TaskInstance,
    SelectionRequest
)


class SchedulerRequest(BaseModel):
    """Request message for scheduler"""
    model_type: str  # Type of model needed
    input_data: Dict[str, Any]
    metadata: Dict[str, Any] = {}
    request_id: Optional[str] = None


class SchedulerResponse(BaseModel):
    """Response from scheduler"""
    task_id: str
    instance_id: str
    instance_url: str
    model_type: str
    queue_size: int


class SwarmPilotScheduler:
    """
    Main scheduler class that routes tasks to appropriate TaskInstances

    This is the refactored version that:
    - Works with TaskInstances as the scheduling unit
    - No longer uses port-based identification
    - Supports multiple scheduling strategies
    """

    def __init__(self, strategy: Optional[BaseStrategy] = None):
        """
        Initialize Scheduler with a selection strategy

        Args:
            strategy: TaskInstance selection strategy. If None, uses ShortestQueueStrategy
        """
        self.taskinstances: List[TaskInstance] = []
        self._strategy = strategy
        self.last_routing_info: Optional[Dict[str, Any]] = None

    @property
    def strategy(self) -> BaseStrategy:
        """Get the current strategy, creating default if not set"""
        if self._strategy is None:
            self._strategy = ShortestQueueStrategy(self.taskinstances)
        return self._strategy

    @strategy.setter
    def strategy(self, strategy: BaseStrategy):
        """Set a new strategy"""
        self._strategy = strategy
        # Update strategy's taskinstances reference
        if self._strategy:
            self._strategy.taskinstances = self.taskinstances

    def set_strategy(self, strategy_name: str) -> None:
        """
        Set strategy by name

        Args:
            strategy_name: Name of strategy ("shortest_queue", "round_robin", "weighted", "probabilistic")
        """
        strategy_map = {
            "shortest_queue": ShortestQueueStrategy,
            "round_robin": RoundRobinStrategy,
            "weighted": WeightedStrategy,
            "probabilistic": ProbabilisticQueueStrategy
        }

        strategy_class = strategy_map.get(strategy_name.lower())
        if not strategy_class:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        self.strategy = strategy_class(self.taskinstances)
        logger.info(f"Set scheduling strategy to: {strategy_name}")

    def load_task_instances_from_config(self, config_path: str) -> None:
        """
        Load TaskInstances from configuration file

        Args:
            config_path: Path to YAML configuration file
        """
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)

        instances = data.get('instances', [])

        # Clear existing instances
        self.taskinstances.clear()

        # Load new instances
        for instance_config in instances:
            if isinstance(instance_config, dict):
                host = instance_config.get('host', 'localhost')
                port = instance_config.get('port', 8100)
                base_url = f"http://{host}:{port}"
            else:
                # Support old format: just URL string
                base_url = instance_config

            ti_uuid = uuid4()
            client = TaskInstanceClient(base_url)
            task_instance = TaskInstance(uuid=ti_uuid, instance=client)

            self.taskinstances.append(task_instance)
            logger.info(f"Loaded TaskInstance {ti_uuid} from {base_url}")

        # Update strategy's taskinstances reference
        if self._strategy:
            self._strategy.taskinstances = self.taskinstances

        logger.info(f"Loaded {len(self.taskinstances)} TaskInstance(s)")

    def add_task_instance(self, base_url: str) -> UUID:
        """
        Add a single TaskInstance

        Args:
            base_url: Base URL of the TaskInstance

        Returns:
            UUID of the added instance
        """
        ti_uuid = uuid4()
        client = TaskInstanceClient(base_url)
        task_instance = TaskInstance(uuid=ti_uuid, instance=client)

        self.taskinstances.append(task_instance)

        # Update strategy's taskinstances reference
        if self._strategy:
            self._strategy.taskinstances = self.taskinstances

        logger.info(f"Added TaskInstance {ti_uuid} at {base_url}")
        return ti_uuid

    def remove_task_instance(self, instance_uuid: UUID) -> bool:
        """
        Remove a TaskInstance

        Args:
            instance_uuid: UUID of the instance to remove

        Returns:
            True if removed, False if not found
        """
        for i, ti in enumerate(self.taskinstances):
            if ti.uuid == instance_uuid:
                self.taskinstances.pop(i)
                logger.info(f"Removed TaskInstance {instance_uuid}")
                return True

        logger.warning(f"TaskInstance {instance_uuid} not found")
        return False

    def schedule(self, request: SchedulerRequest) -> SchedulerResponse:
        """
        Schedule a task to the optimal TaskInstance

        Args:
            request: Scheduler request containing task information

        Returns:
            SchedulerResponse with routing information

        Raises:
            RuntimeError: If no suitable instance found or scheduling fails
        """
        if not self.taskinstances:
            raise RuntimeError("No TaskInstances configured")

        # Generate request ID if not provided
        if not request.request_id:
            request.request_id = str(uuid4())

        # Create selection request
        selection_req = SelectionRequest(
            model_type=request.model_type,
            input_data=request.input_data,
            metadata=request.metadata
        )

        # Use strategy to select optimal instance
        result = self.strategy.select(selection_req)
        selected_instance = result.selected_instance
        queue_info = result.queue_info

        # Enqueue task to selected instance
        try:
            enqueue_response = selected_instance.instance.enqueue_task(
                input_data=request.input_data,
                metadata=request.metadata
            )

            # Save routing information
            self.last_routing_info = {
                "request_id": request.request_id,
                "task_id": enqueue_response.task_id,
                "instance_uuid": str(selected_instance.uuid),
                "instance_url": selected_instance.instance.base_url,
                "model_type": queue_info.model_type,
                "expected_ms": queue_info.expected_ms,
                "queue_size_before": queue_info.queue_size
            }

            logger.info(
                f"Task {enqueue_response.task_id} scheduled to instance {selected_instance.uuid} "
                f"(model: {queue_info.model_type}, expected: {queue_info.expected_ms}ms)"
            )

            return SchedulerResponse(
                task_id=enqueue_response.task_id,
                instance_id=str(selected_instance.uuid),
                instance_url=selected_instance.instance.base_url,
                model_type=queue_info.model_type,
                queue_size=enqueue_response.queue_size
            )

        except Exception as e:
            logger.error(f"Failed to enqueue task to instance {selected_instance.uuid}: {e}")
            raise RuntimeError(f"Failed to schedule task: {e}")

    def get_last_routing_info(self) -> Dict[str, Any]:
        """Get last routing information"""
        if self.last_routing_info is None:
            raise RuntimeError("No routing information available")
        return self.last_routing_info

    def get_instance_statuses(self) -> List[Dict[str, Any]]:
        """
        Get status of all configured TaskInstances

        Returns:
            List of instance status dictionaries
        """
        statuses = []

        for ti in self.taskinstances:
            try:
                status = ti.instance.get_status()
                statuses.append({
                    "uuid": str(ti.uuid),
                    "url": ti.instance.base_url,
                    "instance_id": status.instance_id,
                    "model_type": status.model_type,
                    "replicas": status.replicas_running,
                    "queue_size": status.queue_size,
                    "status": status.status
                })
            except Exception as e:
                logger.warning(f"Failed to get status for instance {ti.uuid}: {e}")
                statuses.append({
                    "uuid": str(ti.uuid),
                    "url": ti.instance.base_url,
                    "status": "error",
                    "error": str(e)
                })

        return statuses

    def get_total_capacity(self) -> Dict[str, int]:
        """
        Get total capacity by model type across all instances

        Returns:
            Dictionary mapping model_type to total replica count
        """
        capacity = {}

        for ti in self.taskinstances:
            try:
                status = ti.instance.get_status()
                if status.model_type:
                    capacity[status.model_type] = capacity.get(status.model_type, 0) + status.replicas_running
            except Exception:
                pass

        return capacity