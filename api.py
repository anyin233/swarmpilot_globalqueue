from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from uuid import UUID
from loguru import logger
from datetime import datetime

from main import SwarmPilotGlobalMsgQueue, GlobalRequestMessage

app = FastAPI(title="SwarmPilot GlobalQueue API", version="0.1.0")

# Global queue instance
global_queue: Optional[SwarmPilotGlobalMsgQueue] = None

# Task routing log: task_id -> routing info
task_routing_log: Dict[str, Dict[str, Any]] = {}


class TaskEnqueueRequest(BaseModel):
    """任务入队请求，与 TaskInstance 格式兼容"""
    input_data: Dict[str, Any] = Field(..., description="任务输入数据")
    task_type: Optional[str] = Field(None, description="任务类型（ocr, llm等）")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="任务元数据，包含模型信息和特征")


class TaskEnqueueResponse(BaseModel):
    """任务入队响应"""
    task_id: str
    model_name: str
    target_host: str
    target_port: int
    queue_size: int
    message: str


class TaskRoutingInfo(BaseModel):
    """任务路由信息"""
    task_id: str
    model_name: str
    target_host: str
    target_port: int
    timestamp: str
    queue_size: int


class TaskInstanceInfo(BaseModel):
    """TaskInstance 信息"""
    uuid: str
    host: str
    models: List[Dict[str, Any]]
    status: str


class GlobalQueueInfo(BaseModel):
    """GlobalQueue 信息"""
    total_task_instances: int
    task_instances: List[TaskInstanceInfo]
    total_models: int
    active_queues: int


@app.on_event("startup")
async def startup_event():
    """启动时初始化 GlobalQueue"""
    global global_queue
    global_queue = SwarmPilotGlobalMsgQueue()
    logger.info("GlobalQueue API started")


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "GlobalQueue"}


@app.post("/queue/enqueue", response_model=TaskEnqueueResponse)
async def enqueue_task(request: TaskEnqueueRequest = Body(...)):
    """
    接收任务并转发到最优的 TaskInstance

    Args:
        request: 任务请求，包含 input_data, task_type, metadata

    Returns:
        任务入队响应，包含 task_id, 目标模型信息等
    """
    if global_queue is None:
        raise HTTPException(status_code=503, detail="GlobalQueue not initialized")

    # 从 metadata 中提取 model_id
    model_id = request.metadata.get("model_id")
    if not model_id:
        raise HTTPException(
            status_code=400,
            detail="Missing 'model_id' in metadata"
        )

    # 构造 GlobalRequestMessage
    try:
        from uuid import uuid4
        task_uuid = uuid4()

        global_msg = GlobalRequestMessage(
            model_id=model_id,
            input_data=request.input_data,
            input_features=request.metadata,
            uuid=task_uuid
        )

        # 调用 GlobalQueue 的 enqueue 方法
        response = global_queue.enqueue(global_msg)

        # 获取路由信息
        routing_info = global_queue.get_last_routing_info()

        # 记录路由日志
        task_routing_log[str(response.task_id)] = {
            "task_id": str(response.task_id),
            "model_name": routing_info["model_name"],
            "target_host": routing_info["target_host"],
            "target_port": routing_info["target_port"],
            "timestamp": datetime.utcnow().isoformat(),
            "queue_size": response.queue_size
        }

        logger.info(
            f"Task {response.task_id} enqueued to {routing_info['model_name']} "
            f"at {routing_info['target_host']}:{routing_info['target_port']}"
        )

        return TaskEnqueueResponse(
            task_id=str(response.task_id),
            model_name=routing_info["model_name"],
            target_host=routing_info["target_host"],
            target_port=routing_info["target_port"],
            queue_size=response.queue_size,
            message="Task enqueued successfully"
        )

    except Exception as e:
        logger.error(f"Failed to enqueue task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enqueue task: {str(e)}")


@app.get("/queue/query-target", response_model=TaskRoutingInfo)
async def query_task_target(task_id: str):
    """
    查询任务的转发目标信息

    Args:
        task_id: 任务ID

    Returns:
        任务路由信息，包含目标模型名称、IP、端口
    """
    if task_id not in task_routing_log:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found in routing log"
        )

    routing_info = task_routing_log[task_id]
    return TaskRoutingInfo(**routing_info)


@app.get("/info", response_model=GlobalQueueInfo)
async def get_info():
    """
    获取 GlobalQueue 的状态信息

    Returns:
        包含所有连接的 TaskInstance 及其模型信息
    """
    if global_queue is None:
        raise HTTPException(status_code=503, detail="GlobalQueue not initialized")

    task_instances = []
    total_models = 0

    for ti in global_queue.taskinstances:
        try:
            # 获取 TaskInstance 的模型列表
            models_response = ti.instance.list_models()
            models = [
                {
                    "model": m.model,
                    "port": m.port,
                    "status": m.status
                }
                for m in models_response.models
            ]

            task_instances.append(
                TaskInstanceInfo(
                    uuid=str(ti.uuid),
                    host=ti.instance.base_url,
                    models=models,
                    status="active"
                )
            )
            total_models += len(models)

        except Exception as e:
            logger.error(f"Failed to get info from TaskInstance {ti.uuid}: {e}")
            task_instances.append(
                TaskInstanceInfo(
                    uuid=str(ti.uuid),
                    host=ti.instance.base_url,
                    models=[],
                    status="error"
                )
            )

    return GlobalQueueInfo(
        total_task_instances=len(task_instances),
        task_instances=task_instances,
        total_models=total_models,
        active_queues=len(global_queue.queues)
    )


@app.post("/config/load-task-instances")
async def load_task_instances(config_path: str = Body(..., embed=True)):
    """
    从配置文件加载 TaskInstance 列表

    Args:
        config_path: YAML 配置文件路径

    Returns:
        加载结果
    """
    if global_queue is None:
        raise HTTPException(status_code=503, detail="GlobalQueue not initialized")

    try:
        global_queue.load_task_instance_from_config(config_path)
        logger.info(f"Loaded TaskInstances from {config_path}")
        return {
            "message": f"Loaded {len(global_queue.taskinstances)} TaskInstance(s)",
            "count": len(global_queue.taskinstances)
        }
    except Exception as e:
        logger.error(f"Failed to load TaskInstances: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load TaskInstances: {str(e)}"
        )


@app.post("/queue/update")
async def update_queues():
    """
    更新所有队列的状态信息

    Returns:
        更新结果
    """
    if global_queue is None:
        raise HTTPException(status_code=503, detail="GlobalQueue not initialized")

    try:
        global_queue.update_queues()
        logger.info(f"Updated {len(global_queue.queues)} queue(s)")
        return {
            "message": "Queues updated successfully",
            "queues_count": len(global_queue.queues)
        }
    except Exception as e:
        logger.error(f"Failed to update queues: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update queues: {str(e)}"
        )
