"""
Scheduler FastAPI Application

Implements all API endpoints defined in Scheduler.md
"""

from fastapi import FastAPI, HTTPException, Query
from typing import Optional
from loguru import logger
import os

from .core import SwarmPilotScheduler
from .models import (
    TIRegisterRequest, TIRegisterResponse,
    TIRemoveRequest, TIRemoveResponse,
    QueueSubmitRequest, QueueSubmitResponse,
    QueueInfoResponse, QueueInfoItem,
    TaskQueryResponse,
    TaskCompletionNotification,
    SchedulerRequest,
    SetStrategyRequest, SetStrategyResponse,
    PredictModeRequest, PredictModeResponse
)

# Initialize scheduler
scheduler = SwarmPilotScheduler()

# FastAPI app
app = FastAPI(
    title="SwarmPilot Scheduler",
    description="Task scheduling service (v2.0 - Refactored)",
    version="2.0.0"
)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "scheduler", "version": "2.0.0"}


@app.post("/scheduler/set", response_model=SetStrategyResponse)
async def set_scheduling_strategy(request: SetStrategyRequest):
    """
    Set the scheduling strategy

    Args:
        request: Strategy setting request containing strategy name

    Returns:
        Result of strategy setting operation
    """
    try:
        # Validate strategy name
        valid_strategies = ["shortest_queue", "round_robin", "weighted", "probabilistic"]
        if request.name not in valid_strategies:
            return SetStrategyResponse(
                status="error",
                message=f"Invalid strategy name '{request.name}'. Valid strategies: {', '.join(valid_strategies)}"
            )

        # Set strategy
        scheduler.set_strategy(request.name)

        return SetStrategyResponse(
            status="success",
            message="OK"
        )

    except Exception as e:
        logger.error(f"Failed to set strategy: {e}")
        return SetStrategyResponse(
            status="error",
            message=str(e)
        )


@app.post("/scheduler/predict_mode", response_model=PredictModeResponse)
async def set_predict_mode(request: PredictModeRequest):
    """
    Set the predictor working mode

    Args:
        request: Predictor mode setting request

    Returns:
        Result of mode setting operation
    """
    try:
        # Validate mode
        valid_modes = ["default", "lookup_table"]
        if request.mode not in valid_modes:
            return PredictModeResponse(
                status="error",
                message=f"Invalid mode '{request.mode}'. Valid modes: {', '.join(valid_modes)}"
            )

        # TODO: Implement predictor mode switching
        # This requires either:
        # 1. Adding a predict_mode property to the scheduler
        # 2. Passing mode to predictor service calls
        # 3. Configuring predictor service to use different modes

        logger.warning("Predictor mode switching is not yet fully implemented")

        return PredictModeResponse(
            status="success",
            message="OK (mode switching not fully implemented yet)"
        )

    except Exception as e:
        logger.error(f"Failed to set predictor mode: {e}")
        return PredictModeResponse(
            status="error",
            message=str(e)
        )


@app.post("/ti/register", response_model=TIRegisterResponse)
async def register_task_instance(request: TIRegisterRequest):
    """
    Register a Task Instance to the scheduler

    Args:
        request: Registration request containing host, port, and model_name

    Returns:
        Registration result with assigned ti_uuid
    """
    try:
        base_url = f"http://{request.host}:{request.port}"
        ti_uuid = scheduler.add_task_instance(base_url, model_name=request.model_name)

        return TIRegisterResponse(
            status="success",
            message=f"TaskInstance registered successfully for model {request.model_name}",
            ti_uuid=str(ti_uuid)
        )
    except Exception as e:
        logger.error(f"Failed to register TaskInstance: {e}")
        return TIRegisterResponse(
            status="error",
            message=str(e),
            ti_uuid=""
        )


@app.post("/ti/remove", response_model=TIRemoveResponse)
async def remove_task_instance(request: TIRemoveRequest):
    """
    Remove a Task Instance from the scheduler

    Args:
        request: Removal request containing host and port

    Returns:
        Removal result
    """
    try:
        # Remove TaskInstance by host and port
        removed_uuid = scheduler.remove_task_instance_by_address(
            host=request.host,
            port=request.port
        )

        if removed_uuid is None:
            return TIRemoveResponse(
                status="error",
                message=f"TaskInstance at {request.host}:{request.port} not found",
                host=request.host,
                port=request.port,
                ti_uuid=None
            )

        return TIRemoveResponse(
            status="success",
            message=f"TaskInstance removed successfully",
            host=request.host,
            port=request.port,
            ti_uuid=str(removed_uuid)
        )
    except Exception as e:
        logger.error(f"Failed to remove TaskInstance: {e}")
        return TIRemoveResponse(
            status="error",
            message=str(e),
            host=request.host,
            port=request.port,
            ti_uuid=None
        )


@app.post("/queue/submit", response_model=QueueSubmitResponse)
async def submit_task(request: QueueSubmitRequest):
    """
    Submit task to the scheduler

    Args:
        request: Task submission request

    Returns:
        Scheduling result with task_id and scheduled_ti
    """
    try:
        # Create scheduler request
        scheduler_req = SchedulerRequest(
            model_type=request.model_name,
            input_data=request.task_input,
            metadata=request.metadata
        )

        # Execute scheduling
        response = scheduler.schedule(scheduler_req)

        return QueueSubmitResponse(
            status="success",
            task_id=response.task_id,
            scheduled_ti=response.instance_id
        )

    except RuntimeError as e:
        logger.error(f"Scheduling failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during scheduling: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/queue/info", response_model=QueueInfoResponse)
async def get_queue_info(model_name: Optional[str] = Query(None)):
    """
    Get information about all queues

    Args:
        model_name: Optional, filter queues for specific model

    Returns:
        List of queue information
    """
    try:
        queues = []

        # Get all instance statuses
        statuses = scheduler.get_instance_statuses()

        for status in statuses:
            # If model_name is specified, only return matching ones
            if model_name and status.get("model_type") != model_name:
                continue

            # Skip instances with error status
            if status.get("status") == "error":
                continue

            queue_info = QueueInfoItem(
                model_name=status.get("model_type", "unknown"),
                ti_uuid=status["uuid"],
                waiting_time_expect=0.0,  # TODO: Get from strategy
                waiting_time_error=0.0    # TODO: Get from strategy
            )
            queues.append(queue_info)

        return QueueInfoResponse(
            status="success",
            queues=queues
        )

    except Exception as e:
        logger.error(f"Failed to get queue info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/task/query", response_model=TaskQueryResponse)
async def query_task(task_id: str = Query(..., description="Task ID")):
    """
    Query task status

    Args:
        task_id: Task unique identifier

    Returns:
        Task status information
    """
    try:
        # Get task information from TaskTracker
        task_info = scheduler.task_tracker.get_task_info(task_id)

        if not task_info:
            raise HTTPException(
                status_code=404,
                detail=f"Task {task_id} not found"
            )

        return TaskQueryResponse(
            task_id=task_info.task_id,
            task_status=task_info.task_status,
            scheduled_ti=str(task_info.scheduled_ti),
            submit_time=task_info.submit_time,
            result=task_info.result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to query task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/notify/task_complete")
async def notify_task_completion(notification: TaskCompletionNotification):
    """
    Receive task completion notification

    Args:
        notification: Task completion notification

    Returns:
        Confirmation response
    """
    try:
        # Find instance UUID
        instance_uuid = None
        for ti in scheduler.taskinstances:
            status = ti.instance.get_status()
            if status.instance_id == notification.instance_id:
                instance_uuid = ti.uuid
                break

        if instance_uuid is None:
            logger.warning(
                f"Received completion for unknown instance: {notification.instance_id}"
            )
            return {
                "status": "warning",
                "message": f"Instance {notification.instance_id} not found"
            }

        # Process completion
        total_time = scheduler.handle_task_completion(
            task_id=notification.task_id,
            instance_uuid=instance_uuid,
            execution_time=notification.execution_time
        )

        response = {
            "status": "success",
            "message": f"Task {notification.task_id} completion processed"
        }

        if total_time:
            response["total_time_ms"] = total_time

        return response

    except Exception as e:
        logger.error(f"Failed to process completion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("startup")
async def startup_event():
    """Initialize scheduler"""
    logger.info("Starting SwarmPilot Scheduler v2.0...")

    # Load default configuration
    default_config = os.environ.get("SCHEDULER_CONFIG_PATH")
    if default_config and os.path.exists(default_config):
        try:
            scheduler.load_task_instances_from_config(default_config)
            logger.info(f"Loaded config from {default_config}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8102)
