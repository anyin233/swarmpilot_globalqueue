"""
SwarmPilot Scheduler

A flexible task scheduling system for distributing workloads across multiple TaskInstances.

Main Components:
- SwarmPilotScheduler: Core scheduler class
- TaskTracker: Task state tracking
- TaskInstanceClient: Client for TaskInstance API
- Strategies: Various scheduling strategies

Example:
    from src.scheduler import SwarmPilotScheduler
    from src.scheduler.models import SchedulerRequest

    scheduler = SwarmPilotScheduler()
    scheduler.load_task_instances_from_config("config.yaml")

    request = SchedulerRequest(
        model_type="test_model",
        input_data={"prompt": "Hello"},
        metadata={}
    )

    response = scheduler.schedule(request)
    print(f"Task {response.task_id} scheduled")
"""

from .core import SwarmPilotScheduler
from .task_tracker import TaskTracker, TaskInfo
from .client import TaskInstanceClient
from .predictor import LookupPredictor
from .predictor_client import PredictorClient
from .models import (
    # Enums
    InstanceStatus,
    TaskStatus,
    # Core Models
    SchedulerRequest,
    SchedulerResponse,
    # API Models
    TIRegisterRequest,
    TIRegisterResponse,
    TIRemoveRequest,
    TIRemoveResponse,
    QueueSubmitRequest,
    QueueSubmitResponse,
    QueueInfoItem,
    QueueInfoResponse,
    TaskQueryRequest,
    TaskQueryResponse,
    # Predictor Models
    PredictorRequest,
    PredictorResponse,
    PredictorHealthResponse,
    PredictorModelsResponse,
)

# Import strategies for convenience
from .strategies import (
    BaseStrategy,
    ShortestQueueStrategy,
    RoundRobinStrategy,
    WeightedStrategy,
    ProbabilisticQueueStrategy,
    TaskInstance,
    SelectionRequest,
    SelectionResult
)

__version__ = "2.0.0"
__all__ = [
    # Core Classes
    "SwarmPilotScheduler",
    "TaskTracker",
    "TaskInfo",
    "TaskInstanceClient",
    "LookupPredictor",
    "PredictorClient",
    # Enums
    "InstanceStatus",
    "TaskStatus",
    # Models
    "SchedulerRequest",
    "SchedulerResponse",
    "TIRegisterRequest",
    "TIRegisterResponse",
    "TIRemoveRequest",
    "TIRemoveResponse",
    "QueueSubmitRequest",
    "QueueSubmitResponse",
    "QueueInfoItem",
    "QueueInfoResponse",
    "TaskQueryRequest",
    "TaskQueryResponse",
    # Predictor Models
    "PredictorRequest",
    "PredictorResponse",
    "PredictorHealthResponse",
    "PredictorModelsResponse",
    # Strategies
    "BaseStrategy",
    "ShortestQueueStrategy",
    "RoundRobinStrategy",
    "WeightedStrategy",
    "ProbabilisticQueueStrategy",
    "TaskInstance",
    "SelectionRequest",
    "SelectionResult",
]
