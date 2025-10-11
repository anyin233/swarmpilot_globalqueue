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
    SchedulerRequest
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


@app.post("/ti/register", response_model=TIRegisterResponse)
async def register_task_instance(request: TIRegisterRequest):
    """
    注册一个 Task Instance 到调度器

    Args:
        request: 包含 host 和 port 的注册请求

    Returns:
        注册结果，包含分配的 ti_uuid
    """
    try:
        base_url = f"http://{request.host}:{request.port}"
        ti_uuid = scheduler.add_task_instance(base_url)

        return TIRegisterResponse(
            status="success",
            message=f"TaskInstance registered successfully",
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
    从调度器移除一个 Task Instance

    Args:
        request: 包含 ti_uuid 的移除请求

    Returns:
        移除结果
    """
    try:
        from uuid import UUID
        ti_uuid = UUID(request.ti_uuid)

        removed = scheduler.remove_task_instance(ti_uuid)

        if not removed:
            return TIRemoveResponse(
                status="error",
                message=f"TaskInstance {request.ti_uuid} not found",
                ti_uuid=request.ti_uuid
            )

        return TIRemoveResponse(
            status="success",
            message=f"TaskInstance removed successfully",
            ti_uuid=request.ti_uuid
        )
    except ValueError:
        return TIRemoveResponse(
            status="error",
            message="Invalid UUID format",
            ti_uuid=request.ti_uuid
        )
    except Exception as e:
        logger.error(f"Failed to remove TaskInstance: {e}")
        return TIRemoveResponse(
            status="error",
            message=str(e),
            ti_uuid=request.ti_uuid
        )


@app.post("/queue/submit", response_model=QueueSubmitResponse)
async def submit_task(request: QueueSubmitRequest):
    """
    提交任务到调度器

    Args:
        request: 任务提交请求

    Returns:
        调度结果，包含 task_id 和 scheduled_ti
    """
    try:
        # 创建调度请求
        scheduler_req = SchedulerRequest(
            model_type=request.model_name,
            input_data=request.task_input,
            metadata=request.metadata
        )

        # 执行调度
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
    获取所有队列的信息

    Args:
        model_name: 可选，过滤特定模型的队列

    Returns:
        队列信息列表
    """
    try:
        queues = []

        # 获取所有实例状态
        statuses = scheduler.get_instance_statuses()

        for status in statuses:
            # 如果指定了 model_name，只返回匹配的
            if model_name and status.get("model_type") != model_name:
                continue

            # 跳过错误状态的实例
            if status.get("status") == "error":
                continue

            queue_info = QueueInfoItem(
                model_name=status.get("model_type", "unknown"),
                ti_uuid=status["uuid"],
                waiting_time_expect=0.0,  # TODO: 从策略获取
                waiting_time_error=0.0    # TODO: 从策略获取
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
async def query_task(task_id: str = Query(..., description="任务ID")):
    """
    查询任务状态

    Args:
        task_id: 任务唯一标识符

    Returns:
        任务状态信息
    """
    try:
        # 从 TaskTracker 获取任务信息
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
    接收任务完成通知

    Args:
        notification: 任务完成通知

    Returns:
        确认响应
    """
    try:
        # 查找实例 UUID
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

        # 处理完成
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
    """初始化调度器"""
    logger.info("Starting SwarmPilot Scheduler v2.0...")

    # 加载默认配置
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
