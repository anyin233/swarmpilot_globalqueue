from queue import PriorityQueue
from pydantic import BaseModel
from loguru import logger
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from uuid import uuid4, UUID
from task_instance_client import TaskInstanceClient, Task
import yaml


class GlobalRequestMessage(BaseModel):
    model_id: str
    input_data: Dict[str, Any] # Input data of current request, optional now, but required in future.
    input_features: Dict[str, Any]  # Store the model request information
    uuid: UUID


@dataclass
class TaskInstance:
    uuid: UUID
    instance: TaskInstanceClient


@dataclass(order=True)
class ModelMsgQueue:
    expected_ms: float
    error_ms: float = field(compare=False)
    length: int = field(compare=False)
    # Model Information
    model_name: str = field(compare=False)
    port: int = field(compare=False)
    # Task Instance Information
    ti_uuid: UUID = field(compare=False)


class SwarmPilotGlobalMsgQueue:
    def __init__(self):
        self.queues: Dict[str, PriorityQueue] = {}  # For each model, there will be a Priority Queue
        self.taskinstances: List[TaskInstance] = []  # Store all task instances
        self.last_routing_info: Optional[Dict[str, Any]] = None  # Last routing information

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

    def update_queues(self):
        """Update status of all priority queues"""
        # Clear all queues
        self.queues.clear()

        # Iterate through all Task Instances
        for ti in self.taskinstances:
            client = ti.instance
            # Get all models on this Task Instance
            models = client.list_models().models

            for model_info in models:
                model_name = model_info.model
                port = model_info.port

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

                # Create queue object
                queue_obj = ModelMsgQueue(
                    expected_ms=expected_ms,
                    error_ms=error_ms,
                    length=queue_size,
                    model_name=model_name,
                    port=port,
                    ti_uuid=ti.uuid
                )

                # Ensure priority queue exists for this model
                if model_name not in self.queues:
                    self.queues[model_name] = PriorityQueue()

                # Add queue info to priority queue
                self.queues[model_name].put(queue_obj)

        logger.info(f"Updated queues for {len(self.queues)} models")

    def enqueue(self, task: GlobalRequestMessage):
        """Send task to optimal queue"""
        model_id = task.model_id

        # Check if queue exists for this model
        if model_id not in self.queues:
            raise RuntimeError(f"No queue for model {model_id}")

        cur_q = self.queues[model_id]

        if cur_q.empty():
            raise RuntimeError(f"No available Task Instance for model {model_id}")

        # Get queue with shortest expected time from priority queue
        selected_q = cur_q.get()

        # Find corresponding Task Instance client
        ti_client = None
        ti_host = None
        for ti in self.taskinstances:
            if ti.uuid == selected_q.ti_uuid:
                ti_client = ti.instance
                ti_host = ti.instance.base_url
                break

        if ti_client is None:
            raise RuntimeError(f"Task Instance {selected_q.ti_uuid} not found")

        # Send task to selected queue
        task_obj = Task(
            input_data=task.input_features,
            metadata=task.input_features.get('metadata', {})
        )

        response = ti_client.enqueue_task(port=selected_q.port, task=task_obj)

        # Save routing information
        self.last_routing_info = {
            "model_name": selected_q.model_name,
            "target_host": ti_host,
            "target_port": selected_q.port,
            "ti_uuid": str(selected_q.ti_uuid)
        }

        logger.info(
            f"Task {response.task_id} enqueued to {selected_q.model_name}:{selected_q.port} "
            f"at {ti_host} (expected: {selected_q.expected_ms}ms, queue_size: {response.queue_size})"
        )

        # Update queue information and put back to priority queue
        updated_prediction = ti_client.predict_queue(port=selected_q.port)
        updated_q = ModelMsgQueue(
            expected_ms=updated_prediction.expected_ms,
            error_ms=updated_prediction.error_ms,
            length=updated_prediction.queue_size,
            model_name=selected_q.model_name,
            port=selected_q.port,
            ti_uuid=selected_q.ti_uuid
        )
        cur_q.put(updated_q)

        return response

    def get_last_routing_info(self) -> Dict[str, Any]:
        """Get last routing information"""
        if self.last_routing_info is None:
            raise RuntimeError("No routing information available")
        return self.last_routing_info
