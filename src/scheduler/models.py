"""
Scheduler Data Models

This module contains all Pydantic data models used throughout the scheduler system.
Organized by functional areas:
- Task Instance models
- Queue models
- Task models
- API request/response models
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from enum import Enum
from uuid import UUID


# ========== Enums ==========

class InstanceStatus(str, Enum):
    """Instance status enumeration"""
    IDLE = "idle"
    RUNNING = "running"


class TaskStatus(str, Enum):
    """Task status enumeration"""
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"


# ========== Task Instance Client Models ==========

class StartModelsRequest(BaseModel):
    """Request to start homogeneous models"""
    model_type: str = Field(..., description="Model type to deploy")
    count: int = Field(default=1, description="Number of replicas")
    config: Dict[str, Any] = Field(default_factory=dict)
    num_gpus_per_model: int = Field(default=0)


class StartModelsResponse(BaseModel):
    """Response after starting models"""
    detail: str
    model_type: str
    replicas_started: int
    total_replicas: int


class StopModelsRequest(BaseModel):
    """Request to stop models"""
    count: Optional[int] = Field(default=None)


class StopModelsResponse(BaseModel):
    """Response after stopping models"""
    detail: str
    stopped_replicas: List[str]
    remaining_replicas: int


class InstanceStatusResponse(BaseModel):
    """TaskInstance status"""
    instance_id: str
    model_type: Optional[str]
    replicas_running: int
    queue_size: int
    status: str


class QueueStatusResponse(BaseModel):
    """Queue status"""
    queue_size: int
    model_type: Optional[str]
    expected_ms: Optional[float]
    error_ms: Optional[float]


class EnqueueRequest(BaseModel):
    """Enqueue request"""
    input_data: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class EnqueueResponse(BaseModel):
    """Enqueue response"""
    task_id: str
    queue_size: int
    enqueue_time: float


class PredictResponse(BaseModel):
    """Queue prediction"""
    expected_ms: float
    error_ms: float
    queue_size: int


class TaskResult(BaseModel):
    """Task execution result"""
    task_id: str
    result: Optional[Dict[str, Any]]
    status: str
    error: Optional[str]
    enqueue_time: float
    completion_time: float
    wait_time: float
    execution_time: float
    total_time: float


# ========== Scheduler Core Models ==========

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


# ========== API Models (Scheduler.md specification) ==========

class TIRegisterRequest(BaseModel):
    """
    /ti/register - 注册 Task Instance

    参数设计来自 Scheduler.md
    """
    host: str = Field(..., description="Task Instance的主机地址")
    port: int = Field(..., description="Task Instance的端口")


class TIRegisterResponse(BaseModel):
    """
    /ti/register - 注册响应

    返回格式来自 Scheduler.md
    """
    status: str = Field(..., description="success 或 error")
    message: str = Field(..., description="描述信息")
    ti_uuid: str = Field(..., description="注册的Task Instance UUID")


class TIRemoveRequest(BaseModel):
    """
    /ti/remove - 移除 Task Instance

    参数设计来自 Scheduler.md
    """
    ti_uuid: str = Field(..., description="要移除的Task Instance的唯一标识符")


class TIRemoveResponse(BaseModel):
    """
    /ti/remove - 移除响应

    返回格式来自 Scheduler.md
    """
    status: str = Field(..., description="success 或 error")
    message: str = Field(..., description="描述信息")
    ti_uuid: str = Field(..., description="移除的Task Instance UUID")


class QueueSubmitRequest(BaseModel):
    """
    /queue/submit - 提交任务到调度器

    参数设计来自 Scheduler.md
    """
    model_name: str = Field(..., description="目标模型名称")
    task_input: Dict[str, Any] = Field(..., description="提交给Task Instance的任务信息")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="提交给Predictor用于预测模型执行时间分布的元数据")


class QueueSubmitResponse(BaseModel):
    """
    /queue/submit - 提交响应

    返回格式来自 Scheduler.md
    """
    status: str = Field(..., description="success 或 error")
    task_id: str = Field(..., description="提交的任务ID")
    scheduled_ti: str = Field(..., description="被调度到的Task Instance UUID")


class QueueInfoItem(BaseModel):
    """
    单个队列信息

    用于 /queue/info 响应
    """
    model_name: str = Field(..., description="模型名称")
    ti_uuid: str = Field(..., description="Task Instance UUID")
    waiting_time_expect: float = Field(..., description="预计等待时间的期望")
    waiting_time_error: float = Field(..., description="预计等待时间的误差")


class QueueInfoRequest(BaseModel):
    """
    /queue/info - 获取队列信息请求

    参数设计来自 Scheduler.md
    """
    model_name: Optional[str] = Field(None, description="(可选) 指定模型名称，若不指定则返回所有模型的信息")


class QueueInfoResponse(BaseModel):
    """
    /queue/info - 获取队列信息响应

    返回格式来自 Scheduler.md
    """
    status: str = Field(..., description="success 或 error")
    queues: List[QueueInfoItem] = Field(..., description="队列信息列表")


class TaskQueryRequest(BaseModel):
    """
    /task/query - 查询任务信息请求

    参数设计来自 Scheduler.md
    """
    task_id: str = Field(..., description="任务唯一标识符")


class TaskQueryResponse(BaseModel):
    """
    /task/query - 查询任务信息响应

    返回格式来自 Scheduler.md
    """
    task_id: str = Field(..., description="任务ID")
    task_status: TaskStatus = Field(..., description="任务状态: queued, scheduled, completed")
    scheduled_ti: str = Field(..., description="被调度到的Task Instance UUID")
    submit_time: float = Field(..., description="提交时间戳")
    result: Optional[Any] = Field(None, description="任务结果(如果已完成)")


# ========== Legacy API Models (for compatibility) ==========

class SetStrategyRequest(BaseModel):
    """Request to set scheduling strategy"""
    strategy: str = Field(..., description="Strategy name: 'shortest_queue', 'round_robin', 'weighted', or 'probabilistic'")


class LoadInstancesRequest(BaseModel):
    """Request to load TaskInstances from config"""
    config_path: str = Field(..., description="Path to TaskInstance configuration file")


class AddInstanceRequest(BaseModel):
    """Request to add a single TaskInstance"""
    url: str = Field(..., description="TaskInstance URL (e.g., 'http://localhost:8100')")


class RemoveInstanceRequest(BaseModel):
    """Request to remove a TaskInstance"""
    instance_uuid: str = Field(..., description="UUID of the TaskInstance to remove")


class InstanceStatusInfo(BaseModel):
    """Status of a TaskInstance"""
    uuid: str
    url: str
    instance_id: Optional[str] = None
    model_type: Optional[str] = None
    replicas: Optional[int] = None
    queue_size: Optional[int] = None
    status: str
    error: Optional[str] = None


class SchedulerInfo(BaseModel):
    """Overall scheduler information"""
    total_instances: int
    strategy: str
    instances: List[InstanceStatusInfo]
    capacity_by_type: Dict[str, int]


class TaskCompletionNotification(BaseModel):
    """Notification from TaskInstance when a task completes"""
    task_id: str = Field(..., description="ID of the completed task")
    instance_id: str = Field(..., description="ID of the TaskInstance that completed the task")
    execution_time: float = Field(..., description="Actual execution time in milliseconds")
