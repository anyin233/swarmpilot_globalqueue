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
        self.last_routing_info: Optional[Dict[str, Any]] = None  # 最近一次路由信息

    def load_task_instance_from_config(self, path: str):
        """从配置文件加载 Task Instance"""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        instances = data['instances']

        # 支持列表格式的配置
        if isinstance(instances, list):
            for instance_config in instances:
                base_url = f"http://{instance_config['host']}:{instance_config['port']}"
                ti_uuid = uuid4()
                client = TaskInstanceClient(base_url)
                self.taskinstances.append(TaskInstance(uuid=ti_uuid, instance=client))
                logger.info(f"Loaded Task Instance {ti_uuid} from {base_url}")
        else:
            # 兼容旧的字典格式
            base_url = f"http://{instances['host']}:{instances['port']}"
            ti_uuid = uuid4()
            client = TaskInstanceClient(base_url)
            self.taskinstances.append(TaskInstance(uuid=ti_uuid, instance=client))
            logger.info(f"Loaded Task Instance {ti_uuid} from {base_url}")

    def update_queues(self):
        """更新所有优先队列的状态"""
        # 清空所有队列
        self.queues.clear()

        # 遍历所有 Task Instance
        for ti in self.taskinstances:
            client = ti.instance
            # 获取该 Task Instance 上所有模型
            models = client.list_models().models

            for model_info in models:
                model_name = model_info.model
                port = model_info.port

                # 尝试获取队列状态
                try:
                    queue_status = client.get_queue_status(port=port)
                    queue_size = queue_status.queue_size

                    # 如果队列有任务，获取预测信息
                    if queue_size > 0:
                        prediction = client.predict_queue(port=port)
                        expected_ms = prediction.expected_ms
                        error_ms = prediction.error_ms
                    else:
                        # 如果队列为空，使用默认值
                        expected_ms = 0.0
                        error_ms = 0.0

                except Exception as e:
                    # 如果队列不存在或其他错误，使用默认值
                    logger.debug(f"Queue for {model_name}:{port} not initialized yet: {e}")
                    queue_size = 0
                    expected_ms = 0.0
                    error_ms = 0.0

                # 创建队列对象
                queue_obj = ModelMsgQueue(
                    expected_ms=expected_ms,
                    error_ms=error_ms,
                    length=queue_size,
                    model_name=model_name,
                    port=port,
                    ti_uuid=ti.uuid
                )

                # 确保该模型的优先队列存在
                if model_name not in self.queues:
                    self.queues[model_name] = PriorityQueue()

                # 将队列信息加入优先队列
                self.queues[model_name].put(queue_obj)

        logger.info(f"Updated queues for {len(self.queues)} models")

    def enqueue(self, task: GlobalRequestMessage):
        """将任务发送到最优的队列"""
        model_id = task.model_id

        # 检查是否存在该模型的队列
        if model_id not in self.queues:
            raise RuntimeError(f"No queue for model {model_id}")

        cur_q = self.queues[model_id]

        if cur_q.empty():
            raise RuntimeError(f"No available Task Instance for model {model_id}")

        # 从优先队列中获取预期时间最短的队列
        selected_q = cur_q.get()

        # 找到对应的 Task Instance 客户端
        ti_client = None
        ti_host = None
        for ti in self.taskinstances:
            if ti.uuid == selected_q.ti_uuid:
                ti_client = ti.instance
                ti_host = ti.instance.base_url
                break

        if ti_client is None:
            raise RuntimeError(f"Task Instance {selected_q.ti_uuid} not found")

        # 将任务发送到选定的队列
        task_obj = Task(
            input_data=task.input_features,
            metadata=task.input_features.get('metadata', {})
        )

        response = ti_client.enqueue_task(port=selected_q.port, task=task_obj)

        # 保存路由信息
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

        # 更新该队列的信息并放回优先队列
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
        """获取最近一次路由信息"""
        if self.last_routing_info is None:
            raise RuntimeError("No routing information available")
        return self.last_routing_info
