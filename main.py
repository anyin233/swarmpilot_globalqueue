from pydantic import BaseModel
from loguru import logger
from typing import Dict, Any, List, Optional
from uuid import uuid4, UUID
from task_instance_client import TaskInstanceClient, Task
import yaml

from strategy import (
    BaseStrategy,
    ShortestQueueStrategy,
    TaskInstance,
    ModelMsgQueue,
    SelectionRequest,
)


class GlobalRequestMessage(BaseModel):
    model_id: str
    input_data: Dict[str, Any] # Input data of current request, optional now, but required in future.
    input_features: Dict[str, Any]  # Store the model request information
    uuid: UUID


class SwarmPilotGlobalMsgQueue:
    def __init__(self, strategy: Optional[BaseStrategy] = None):
        """
        Initialize GlobalQueue with a selection strategy

        Args:
            strategy: TaskInstance selection strategy. If None, uses ShortestQueueStrategy by default
        """
        self.taskinstances: List[TaskInstance] = []  # Store all task instances
        self.last_routing_info: Optional[Dict[str, Any]] = None  # Last routing information
        self._strategy = strategy  # Will be set after taskinstances are loaded

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

    def load_task_instance_from_config(self, path: str):
        """Load Task Instance from configuration file"""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        instances = data['instances']

        # Support list format configuration
        if isinstance(instances, list):
            for instance_config in instances:
                base_url = f"http://{instance_config['host']}:{instance_config['port']}"
                ti_uuid = uuid4()
                client = TaskInstanceClient(base_url)
                self.taskinstances.append(TaskInstance(uuid=ti_uuid, instance=client))
                logger.info(f"Loaded Task Instance {ti_uuid} from {base_url}")
        else:
            # Compatible with old dictionary format
            base_url = f"http://{instances['host']}:{instances['port']}"
            ti_uuid = uuid4()
            client = TaskInstanceClient(base_url)
            self.taskinstances.append(TaskInstance(uuid=ti_uuid, instance=client))
            logger.info(f"Loaded Task Instance {ti_uuid} from {base_url}")

        # Update strategy's taskinstances reference if strategy already exists
        if self._strategy is not None:
            self._strategy.taskinstances = self.taskinstances

    def enqueue(self, task: GlobalRequestMessage):
        """
        Send task to optimal queue using the configured strategy

        Args:
            task: GlobalRequestMessage containing task information

        Returns:
            EnqueueResponse from TaskInstance

        Raises:
            RuntimeError: If no suitable queue found or enqueue fails
        """
        # Create selection request
        request = SelectionRequest(
            model_id=task.model_id,
            input_data=task.input_data,
            input_features=task.input_features
        )

        # Use strategy to select optimal queue
        result = self.strategy.select(request)
        selected_q = result.selected_queue
        ti_client = result.task_instance.instance
        ti_host = result.task_instance.instance.base_url

        # Send task to selected queue
        task_obj = Task(
            input_data=task.input_features,
            metadata=task.input_features.get('metadata', {})
        )

        response = ti_client.enqueue_task(port=selected_q.port, task=task_obj)

        # Parse TaskInstance host and port from base_url
        # base_url format: "http://host:port" or "https://host:port"
        import re
        url_match = re.match(r'https?://([^:]+):(\d+)', ti_host)
        if url_match:
            ti_hostname = url_match.group(1)
            ti_port = int(url_match.group(2))
        else:
            # Fallback if URL format is unexpected
            ti_hostname = ti_host
            ti_port = 8100  # Default TaskInstance port

        # Save routing information
        self.last_routing_info = {
            "model_name": selected_q.model_name,
            "target_host": ti_hostname,  # TaskInstance host
            "target_port": ti_port,  # TaskInstance port
            "model_port": selected_q.port,  # Model port
            "ti_uuid": str(result.task_instance.uuid)
        }

        logger.info(
            f"Task {response.task_id} enqueued to {selected_q.model_name}:{selected_q.port} "
            f"at TaskInstance {ti_hostname}:{ti_port} (expected: {selected_q.expected_ms}ms, queue_size: {response.queue_size})"
        )

        return response

    def get_last_routing_info(self) -> Dict[str, Any]:
        """Get last routing information"""
        if self.last_routing_info is None:
            raise RuntimeError("No routing information available")
        return self.last_routing_info
