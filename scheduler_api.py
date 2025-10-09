"""
Scheduler FastAPI Service

This is the refactored API for the scheduler (formerly GlobalQueue).
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from loguru import logger
import os

from scheduler import SwarmPilotScheduler, SchedulerRequest, SchedulerResponse

# Initialize scheduler
scheduler = SwarmPilotScheduler()

# FastAPI app
app = FastAPI(
    title="SwarmPilot Scheduler",
    description="Task scheduling service for SwarmPilot (refactored from GlobalQueue)",
    version="2.0.0"
)


# ========== API Models ==========

class ScheduleTaskRequest(BaseModel):
    """Request to schedule a task"""
    model_type: str = Field(..., description="Type of model needed (e.g., 'tx_det_dummy')")
    input_data: Dict[str, Any] = Field(..., description="Input data for the task")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")


class SetStrategyRequest(BaseModel):
    """Request to set scheduling strategy"""
    strategy: str = Field(..., description="Strategy name: 'shortest_queue', 'round_robin', or 'weighted'")


class LoadInstancesRequest(BaseModel):
    """Request to load TaskInstances from config"""
    config_path: str = Field(..., description="Path to TaskInstance configuration file")


class AddInstanceRequest(BaseModel):
    """Request to add a single TaskInstance"""
    url: str = Field(..., description="TaskInstance URL (e.g., 'http://localhost:8100')")


class RemoveInstanceRequest(BaseModel):
    """Request to remove a TaskInstance"""
    instance_uuid: str = Field(..., description="UUID of the TaskInstance to remove")


class InstanceStatus(BaseModel):
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
    instances: List[InstanceStatus]
    capacity_by_type: Dict[str, int]


# ========== API Endpoints ==========

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "scheduler"}


@app.post("/schedule", response_model=SchedulerResponse)
async def schedule_task(request: ScheduleTaskRequest) -> SchedulerResponse:
    """
    Schedule a task to the optimal TaskInstance

    This endpoint:
    1. Accepts a task request with model type and input data
    2. Uses the configured strategy to select the best TaskInstance
    3. Enqueues the task to the selected instance
    4. Returns routing information
    """
    try:
        scheduler_req = SchedulerRequest(
            model_type=request.model_type,
            input_data=request.input_data,
            metadata=request.metadata or {}
        )

        response = scheduler.schedule(scheduler_req)
        return response

    except RuntimeError as e:
        logger.error(f"Scheduling failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during scheduling: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/routing/last")
async def get_last_routing() -> Dict[str, Any]:
    """Get information about the last routing decision"""
    try:
        return scheduler.get_last_routing_info()
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/strategy")
async def set_strategy(request: SetStrategyRequest) -> Dict[str, str]:
    """
    Set the scheduling strategy

    Available strategies:
    - shortest_queue: Select instance with shortest expected completion time
    - round_robin: Distribute tasks evenly across instances
    - weighted: Consider both queue length and prediction uncertainty
    """
    try:
        scheduler.set_strategy(request.strategy)
        return {
            "status": "success",
            "strategy": request.strategy,
            "message": f"Strategy set to {request.strategy}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/strategy")
async def get_strategy() -> Dict[str, str]:
    """Get the current scheduling strategy"""
    strategy_name = scheduler.strategy.__class__.__name__

    # Map class names to strategy names
    name_map = {
        "ShortestQueueStrategy": "shortest_queue",
        "RoundRobinStrategy": "round_robin",
        "WeightedStrategy": "weighted"
    }

    return {
        "strategy": name_map.get(strategy_name, strategy_name),
        "class": strategy_name
    }


@app.post("/instances/load")
async def load_instances(request: LoadInstancesRequest) -> Dict[str, Any]:
    """Load TaskInstances from a configuration file"""
    try:
        # Resolve path
        config_path = os.path.expanduser(request.config_path)
        if not os.path.isabs(config_path):
            config_path = os.path.abspath(config_path)

        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail=f"Config file not found: {config_path}")

        scheduler.load_task_instances_from_config(config_path)

        return {
            "status": "success",
            "loaded": len(scheduler.taskinstances),
            "config_path": config_path
        }
    except Exception as e:
        logger.error(f"Failed to load instances: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/instances/add")
async def add_instance(request: AddInstanceRequest) -> Dict[str, str]:
    """Add a single TaskInstance"""
    try:
        instance_uuid = scheduler.add_task_instance(request.url)
        return {
            "status": "success",
            "instance_uuid": str(instance_uuid),
            "url": request.url
        }
    except Exception as e:
        logger.error(f"Failed to add instance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/instances/remove")
async def remove_instance(request: RemoveInstanceRequest) -> Dict[str, Any]:
    """Remove a TaskInstance"""
    try:
        from uuid import UUID
        instance_uuid = UUID(request.instance_uuid)

        removed = scheduler.remove_task_instance(instance_uuid)
        if not removed:
            raise HTTPException(status_code=404, detail="Instance not found")

        return {
            "status": "success",
            "removed": request.instance_uuid
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    except Exception as e:
        logger.error(f"Failed to remove instance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/instances")
async def list_instances() -> List[InstanceStatus]:
    """List all configured TaskInstances and their status"""
    statuses = scheduler.get_instance_statuses()
    return [InstanceStatus(**status) for status in statuses]


@app.get("/info", response_model=SchedulerInfo)
async def get_scheduler_info() -> SchedulerInfo:
    """Get overall scheduler information"""
    instances = scheduler.get_instance_statuses()
    capacity = scheduler.get_total_capacity()

    strategy_name = scheduler.strategy.__class__.__name__
    name_map = {
        "ShortestQueueStrategy": "shortest_queue",
        "RoundRobinStrategy": "round_robin",
        "WeightedStrategy": "weighted"
    }

    return SchedulerInfo(
        total_instances=len(scheduler.taskinstances),
        strategy=name_map.get(strategy_name, strategy_name),
        instances=[InstanceStatus(**inst) for inst in instances],
        capacity_by_type=capacity
    )


@app.on_event("startup")
async def startup_event():
    """Initialize scheduler on startup"""
    logger.info("Starting SwarmPilot Scheduler...")

    # Load default configuration if available
    default_config = os.environ.get("SCHEDULER_CONFIG_PATH")
    if default_config and os.path.exists(default_config):
        try:
            scheduler.load_task_instances_from_config(default_config)
            logger.info(f"Loaded default configuration from {default_config}")
        except Exception as e:
            logger.error(f"Failed to load default configuration: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8102)