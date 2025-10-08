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
    """Task enqueue request, compatible with TaskInstance format"""
    input_data: Dict[str, Any] = Field(..., description="Task input data")
    task_type: Optional[str] = Field(None, description="Task type (ocr, llm, etc.)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Task metadata, including model info and features")


class TaskEnqueueResponse(BaseModel):
    """Task enqueue response"""
    task_id: str
    model_name: str
    target_host: str
    target_port: int
    queue_size: int
    message: str


class TaskRoutingInfo(BaseModel):
    """Task routing information"""
    task_id: str
    model_name: str
    target_host: str
    target_port: int
    timestamp: str
    queue_size: int


class TaskInstanceInfo(BaseModel):
    """TaskInstance information"""
    uuid: str
    host: str
    models: List[Dict[str, Any]]
    status: str


class GlobalQueueInfo(BaseModel):
    """GlobalQueue information"""
    total_task_instances: int
    task_instances: List[TaskInstanceInfo]
    total_models: int
    active_queues: int


@app.on_event("startup")
async def startup_event():
    """Initialize GlobalQueue on startup"""
    global global_queue
    global_queue = SwarmPilotGlobalMsgQueue()
    logger.info("GlobalQueue API started")


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "ok", "service": "GlobalQueue"}


@app.post("/queue/enqueue", response_model=TaskEnqueueResponse)
async def enqueue_task(request: TaskEnqueueRequest = Body(...)):
    """
    Accept task and route to optimal TaskInstance

    Args:
        request: Task request containing input_data, task_type, metadata

    Returns:
        Task enqueue response with task_id, target model info, etc.
    """
    if global_queue is None:
        raise HTTPException(status_code=503, detail="GlobalQueue not initialized")

    # Extract model_id from metadata
    model_id = request.metadata.get("model_id")
    if not model_id:
        raise HTTPException(
            status_code=400,
            detail="Missing 'model_id' in metadata"
        )

    # Construct GlobalRequestMessage
    try:
        from uuid import uuid4
        task_uuid = uuid4()

        global_msg = GlobalRequestMessage(
            model_id=model_id,
            input_data=request.input_data,
            input_features=request.metadata,
            uuid=task_uuid
        )

        # Call GlobalQueue's enqueue method
        response = global_queue.enqueue(global_msg)

        # Get routing information
        routing_info = global_queue.get_last_routing_info()

        # Record routing log
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
    Query task routing target information

    Args:
        task_id: Task ID

    Returns:
        Task routing info including target model name, IP, port
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
    Get GlobalQueue status information

    Returns:
        Information about all connected TaskInstances and their models
    """
    if global_queue is None:
        raise HTTPException(status_code=503, detail="GlobalQueue not initialized")

    task_instances = []
    total_models = 0

    for ti in global_queue.taskinstances:
        try:
            # Get model list from TaskInstance
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
    Load TaskInstance list from configuration file

    Args:
        config_path: YAML configuration file path

    Returns:
        Loading result
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
    Update status information for all queues

    Returns:
        Update result
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
