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
    /ti/register - Register Task Instance

    Parameter design from Scheduler.md
    """
    host: str = Field(..., description="Task Instance host address")
    port: int = Field(..., description="Task Instance port")
    model_name: str = Field(..., description="Model name running on this Task Instance, used for queue filtering during scheduling")


class TIRegisterResponse(BaseModel):
    """
    /ti/register - Registration response

    Return format from Scheduler.md
    """
    status: str = Field(..., description="success or error")
    message: str = Field(..., description="Description message")
    ti_uuid: str = Field(..., description="Registered Task Instance UUID")


class TIRemoveRequest(BaseModel):
    """
    /ti/remove - Remove Task Instance

    Parameter design from Scheduler.md
    """
    host: str = Field(..., description="Host address of the Task Instance to remove")
    port: int = Field(..., description="Port of the Task Instance to remove")


class TIRemoveResponse(BaseModel):
    """
    /ti/remove - Removal response

    Return format from Scheduler.md
    """
    status: str = Field(..., description="success or error")
    message: str = Field(..., description="Description message")
    host: str = Field(..., description="Host address of removed Task Instance")
    port: int = Field(..., description="Port of removed Task Instance")
    ti_uuid: Optional[str] = Field(None, description="UUID of removed Task Instance (if found)")


class QueueSubmitRequest(BaseModel):
    """
    /queue/submit - Submit task to scheduler

    Parameter design from Scheduler.md
    """
    model_name: str = Field(..., description="Target model name")
    task_input: Dict[str, Any] = Field(..., description="Task information submitted to Task Instance")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata submitted to Predictor for predicting model execution time distribution")


class QueueSubmitResponse(BaseModel):
    """
    /queue/submit - Submission response

    Return format from Scheduler.md
    """
    status: str = Field(..., description="success or error")
    task_id: str = Field(..., description="Submitted task ID")
    scheduled_ti: str = Field(..., description="UUID of Task Instance scheduled to")


class QueueInfoItem(BaseModel):
    """
    Single queue information

    Used for /queue/info response
    """
    model_name: str = Field(..., description="Model name")
    ti_uuid: str = Field(..., description="Task Instance UUID")
    waiting_time_expect: float = Field(..., description="Expected waiting time (mean)")
    waiting_time_error: float = Field(..., description="Waiting time error (standard deviation)")


class QueueInfoRequest(BaseModel):
    """
    /queue/info - Get queue information request

    Parameter design from Scheduler.md
    """
    model_name: Optional[str] = Field(None, description="(Optional) Specify model name, if not specified returns information for all models")


class QueueInfoResponse(BaseModel):
    """
    /queue/info - Get queue information response

    Return format from Scheduler.md
    """
    status: str = Field(..., description="success or error")
    queues: List[QueueInfoItem] = Field(..., description="List of queue information")


class TaskQueryRequest(BaseModel):
    """
    /task/query - Query task information request

    Parameter design from Scheduler.md
    """
    task_id: str = Field(..., description="Task unique identifier")


class TaskQueryResponse(BaseModel):
    """
    /task/query - Query task information response

    Return format from Scheduler.md
    """
    task_id: str = Field(..., description="Task ID")
    task_status: TaskStatus = Field(..., description="Task status: queued, scheduled, completed")
    scheduled_ti: str = Field(..., description="UUID of Task Instance scheduled to")
    submit_time: float = Field(..., description="Submission timestamp")
    result: Optional[Any] = Field(None, description="Task result (if completed)")


# ========== Legacy API Models (for compatibility) ==========

class SetStrategyRequest(BaseModel):
    """
    /scheduler/set - Set scheduling strategy request

    Parameter design from Scheduler.md
    """
    name: str = Field(..., description="Scheduling strategy name: 'shortest_queue', 'round_robin', 'weighted', or 'probabilistic'")


class SetStrategyResponse(BaseModel):
    """
    /scheduler/set - Set scheduling strategy response

    Return format from Scheduler.md
    """
    status: str = Field(..., description="'success' indicates strategy set successfully, 'error' indicates failure")
    message: str = Field(..., description="'OK' if status is success; specific error reason if status is error")


class PredictModeRequest(BaseModel):
    """
    /scheduler/predict_mode - Set predictor mode request

    Parameter design from Scheduler.md
    """
    mode: str = Field(..., description="Prediction mode: 'default' for standard prediction model, 'lookup_table' for pre-computed lookup table")


class PredictModeResponse(BaseModel):
    """
    /scheduler/predict_mode - Set predictor mode response

    Return format from Scheduler.md
    """
    status: str = Field(..., description="'success' indicates mode switch successful, 'error' indicates failure")
    message: str = Field(..., description="'OK' if status is success; specific error reason if status is error")


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


# ========== Predictor Service Models ==========

class PredictorRequest(BaseModel):
    """
    Request to Predictor service for execution time prediction

    The Predictor service analyzes the model type and metadata to predict
    the expected execution time distribution for a task.
    """
    model_type: str = Field(..., description="Model type identifier (e.g., 'gpt-3.5-turbo', 'llama-7b')")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="""Task metadata for prediction, may include:
        - model_name: Specific model variant
        - hardware: Hardware identifier (e.g., 'A100', 'V100')
        - software_name: Framework name (e.g., 'vllm', 'pytorch')
        - software_version: Framework version
        - input_tokens: Estimated input token count
        - output_tokens: Estimated output token count
        - batch_size: Batch size if applicable
        - Any other domain-specific features
        """
    )


class PredictorResponse(BaseModel):
    """
    Response from Predictor service with execution time prediction

    Provides quantile-based predictions for execution time distribution.
    """
    status: str = Field(..., description="'success' or 'error'")
    message: Optional[str] = Field(None, description="Error message if status is 'error'")

    # Prediction results (only present when status == 'success')
    model_type: Optional[str] = Field(None, description="Model type that was predicted")
    quantiles: Optional[List[float]] = Field(
        None,
        description="List of quantile values (e.g., [0.1, 0.25, 0.5, 0.75, 0.9])"
    )
    quantile_predictions: Optional[List[float]] = Field(
        None,
        description="Predicted execution times in milliseconds for each quantile"
    )

    # Additional metadata
    prediction_method: Optional[str] = Field(
        None,
        description="Method used for prediction (e.g., 'lookup', 'model', 'fallback')"
    )
    confidence: Optional[float] = Field(
        None,
        description="Confidence score for the prediction (0-1)"
    )


class PredictorHealthResponse(BaseModel):
    """Health check response from Predictor service"""
    status: str = Field(..., description="'healthy' or 'unhealthy'")
    service: str = Field(default="predictor", description="Service identifier")
    version: Optional[str] = Field(None, description="Service version")
    total_models: Optional[int] = Field(None, description="Number of models available for prediction")


class PredictorModelInfo(BaseModel):
    """Information about a model available in Predictor"""
    model_type: str = Field(..., description="Model type identifier")
    model_name: Optional[str] = Field(None, description="Human-readable model name")
    total_predictions: int = Field(..., description="Number of prediction records available")
    hardware_types: List[str] = Field(default_factory=list, description="List of hardware types supported")
    software_versions: List[str] = Field(default_factory=list, description="List of software versions supported")


class PredictorModelsResponse(BaseModel):
    """Response listing all available models in Predictor"""
    status: str = Field(..., description="'success' or 'error'")
    models: List[PredictorModelInfo] = Field(default_factory=list, description="List of available models")
