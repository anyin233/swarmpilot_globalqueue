"""
Scheduler FastAPI Application

Implements all API endpoints defined in Scheduler.md
"""

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from typing import Optional, Set, Dict
from loguru import logger
import os
import json
import asyncio

from .core import SwarmPilotScheduler
from .models import (
    TIRegisterRequest, TIRegisterResponse,
    TIRemoveRequest, TIRemoveResponse,
    QueueSubmitRequest, QueueSubmitResponse,
    QueueBatchSubmitRequest, QueueBatchSubmitResponse, BatchTaskResult,
    QueueInfoResponse, QueueInfoItem,
    TaskQueryResponse,
    TaskCompletionNotification,
    ResultSubmitRequest, ResultSubmitResponse,
    SchedulerRequest,
    SetStrategyRequest, SetStrategyResponse,
    PredictModeRequest, PredictModeResponse,
    FetchResultRequest, FetchResultResponse,
    TaskStatus,
    TaskInfoItem, AllTasksResponse,
    ClearTasksResponse,
    SettingsSetRequest, SettingsSetResponse,
    SettingsGetRequest, SettingsGetResponse
)
from .task_tracker import TaskInfo

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pyinstrument import Profiler
from pyinstrument.renderers.html import HTMLRenderer
from pyinstrument.renderers.speedscope import SpeedscopeRenderer



# Configuration storage
# Note: Lock-free scheduler is now the default for maximum performance
settings_storage: dict = {
    "predictor_strategy_debug": False,
    "fake_data_enabled": False,
    "fake_data_path": None,
    "async_scheduling_enabled": False,
    "async_max_queue_size": 50000,  # Larger queue for ultra-high QPS (default: 50000)
    "async_retry_attempts": 3,  # Retry attempts (default: 3)
    "async_retry_delay_ms": 50,  # Faster retry for lock-free (default: 50)
    "async_num_workers": 8,  # More workers for lock-free (default: 8)
    "async_batch_size": 20,  # Larger batch for lock-free (default: 20)
    "use_lockfree": True,  # Use lock-free implementation by default
    "probabilistic_quantiles": [0.25, 0.5, 0.75, 0.99]  # Quantiles for probabilistic strategy
}

# Helper function to check if debug is enabled
def get_debug_enabled() -> bool:
    """Get debug enabled status from settings storage"""
    return settings_storage.get("predictor_strategy_debug", False)

# Helper functions to get fake data settings
def get_fake_data_enabled() -> bool:
    """Get fake data enabled status from settings storage"""
    return settings_storage.get("fake_data_enabled", False)

def get_fake_data_path() -> Optional[str]:
    """Get fake data path from settings storage"""
    return settings_storage.get("fake_data_path")

def get_use_lockfree() -> bool:
    """Get lock-free implementation flag"""
    return settings_storage.get("use_lockfree", True)

def get_probabilistic_quantiles() -> list:
    """Get probabilistic strategy quantiles"""
    return settings_storage.get("probabilistic_quantiles", [0.25, 0.5, 0.75, 0.99])

# Initialize scheduler with callbacks (default to lock-free)
scheduler = SwarmPilotScheduler(
    get_debug_enabled=get_debug_enabled,
    get_fake_data_enabled=get_fake_data_enabled,
    get_fake_data_path=get_fake_data_path,
    get_probabilistic_quantiles=get_probabilistic_quantiles,
    use_lockfree=get_use_lockfree()
)

# FastAPI app
app = FastAPI(
    title="SwarmPilot Scheduler",
    description="Task scheduling service (v2.0 - Refactored)",
    version="2.0.0"
)

# Global flag for profiling (will be set from command line argument)
_profiling_enabled = False

def enable_profiler_middleware():
    """
    Register profiling middleware for the FastAPI app.
    Must be called before the app starts serving requests.
    """
    @app.middleware("http")
    async def profile_request(request: Request, call_next: Callable):
        """Profile the current request

        Taken from https://pyinstrument.readthedocs.io/en/latest/guide.html#profile-a-web-request-in-fastapi
        with small improvements.

        """
        # we map a profile type to a file extension, as well as a pyinstrument profile renderer
        profile_type_to_ext = {"html": "html", "speedscope": "speedscope.json"}
        profile_type_to_renderer = {
            "html": HTMLRenderer,
            "speedscope": SpeedscopeRenderer,
        }

        # if the `profile=true` HTTP query argument is passed, we profile the request
        if request.query_params.get("profile", False):

            # The default profile format is speedscope
            profile_type = request.query_params.get("profile_format", "speedscope")

            # we profile the request along with all additional middlewares, by interrupting
            # the program every 1ms1 and records the entire stack at that point
            with Profiler(interval=0.001, async_mode="enabled") as profiler:
                response = await call_next(request)

            # we dump the profiling into a file
            extension = profile_type_to_ext[profile_type]
            renderer = profile_type_to_renderer[profile_type]()
            with open(f"profile.{extension}", "w") as out:
                out.write(profiler.output(renderer=renderer))
            return response

        # Proceed without profiling
        return await call_next(request)

# WebSocket connection manager for task events
class TaskEventManager:
    """Manages WebSocket connections for task event notifications"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection"""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"New WebSocket client connected. Total clients: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast_task_completion(self, task_info: dict) -> int:
        """
        Broadcast task completion event to all connected clients

        Args:
            task_info: Dictionary containing task completion information

        Returns:
            Number of clients successfully notified
        """
        if not self.active_connections:
            logger.warning(
                f"No active WebSocket clients to broadcast task completion for "
                f"task {task_info.get('task_id', 'unknown')}. Event will be lost!"
            )
            return 0

        # Prepare event message
        event_message = {
            "event": "task_completed",
            "data": task_info
        }

        # Send to all connected clients
        disconnected = set()
        success_count = 0

        for connection in self.active_connections.copy():
            try:
                await connection.send_json(event_message)
                success_count += 1
                logger.debug(
                    f"Successfully sent task completion event for task "
                    f"{task_info.get('task_id', 'unknown')} to client"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to send event for task {task_info.get('task_id', 'unknown')} "
                    f"to client: {e}"
                )
                disconnected.add(connection)

        # Clean up disconnected clients
        if disconnected:
            async with self._lock:
                self.active_connections -= disconnected
            logger.info(f"Removed {len(disconnected)} disconnected clients")

        logger.info(
            f"Broadcasted task {task_info.get('task_id', 'unknown')} completion "
            f"to {success_count}/{len(self.active_connections) + len(disconnected)} clients"
        )

        return success_count

# Global event manager instance
task_event_manager = TaskEventManager()


# WebSocket connection manager for result submission
class ResultSubmissionManager:
    """Manages persistent WebSocket connections from TaskInstances for result submission and task dispatch"""

    def __init__(self, max_connections: int = 10000):
        """
        Initialize ResultSubmissionManager

        Args:
            max_connections: Maximum number of concurrent connections (default: 10000)
        """
        # Map instance_id to WebSocket connection
        self.connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()
        self.max_connections = max_connections

        # Statistics
        self.total_registrations = 0
        self.total_unregistrations = 0
        self.rejected_connections = 0
        self.total_tasks_dispatched = 0
        self.total_dispatch_failures = 0

    async def register_instance(self, instance_id: str, websocket: WebSocket, already_accepted: bool = False):
        """
        Register a TaskInstance WebSocket connection

        Args:
            instance_id: Instance identifier
            websocket: WebSocket connection
            already_accepted: Whether websocket.accept() has already been called

        Raises:
            RuntimeError: If max connections limit is reached
        """
        async with self._lock:
            # Check connection limit
            if len(self.connections) >= self.max_connections and instance_id not in self.connections:
                self.rejected_connections += 1
                raise RuntimeError(f"Maximum connections ({self.max_connections}) reached")

            # Close existing connection if any
            if instance_id in self.connections:
                old_ws = self.connections[instance_id]
                try:
                    await old_ws.close(code=1000, reason="Replaced by new connection")
                    logger.debug(f"Closed old connection for {instance_id}")
                except Exception as e:
                    logger.debug(f"Error closing old connection: {e}")

            # Accept connection if not already done
            if not already_accepted:
                await websocket.accept()

            self.connections[instance_id] = websocket
            self.total_registrations += 1

        logger.info(
            f"TaskInstance {instance_id} registered for WebSocket. "
            f"Active: {len(self.connections)}/{self.max_connections}"
        )

    async def unregister_instance(self, instance_id: str):
        """Unregister a TaskInstance WebSocket connection"""
        async with self._lock:
            if instance_id in self.connections:
                del self.connections[instance_id]
                self.total_unregistrations += 1
        logger.info(f"TaskInstance {instance_id} unregistered. Active: {len(self.connections)}")

    async def send_ack(self, instance_id: str, task_id: str, success: bool, message: str = ""):
        """
        Send acknowledgment back to TaskInstance

        Note: Does not hold lock while sending to avoid blocking other operations
        """
        # Get connection without holding lock
        async with self._lock:
            websocket = self.connections.get(instance_id)

        if websocket:
            try:
                # Send with timeout
                await asyncio.wait_for(
                    websocket.send_json({
                        "type": "ack",
                        "task_id": task_id,
                        "success": success,
                        "message": message
                    }),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout sending ack to {instance_id} for task {task_id}")
            except Exception as e:
                logger.warning(f"Failed to send ack to {instance_id}: {e}")
                # Mark connection for cleanup
                await self.unregister_instance(instance_id)

    async def cleanup_dead_connections(self):
        """Remove connections that are no longer active"""
        dead_connections = []

        async with self._lock:
            for instance_id, ws in list(self.connections.items()):
                try:
                    # Check if connection is still alive
                    if ws.client_state.name != "CONNECTED":
                        dead_connections.append(instance_id)
                except Exception:
                    dead_connections.append(instance_id)

            # Remove dead connections
            for instance_id in dead_connections:
                if instance_id in self.connections:
                    del self.connections[instance_id]

        if dead_connections:
            logger.info(f"Cleaned up {len(dead_connections)} dead WebSocket connections")

        return len(dead_connections)

    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.connections)

    def get_statistics(self) -> Dict[str, int]:
        """Get connection statistics"""
        return {
            "active_connections": len(self.connections),
            "max_connections": self.max_connections,
            "total_registrations": self.total_registrations,
            "total_unregistrations": self.total_unregistrations,
            "rejected_connections": self.rejected_connections,
            "total_tasks_dispatched": self.total_tasks_dispatched,
            "total_dispatch_failures": self.total_dispatch_failures
        }

    async def dispatch_task(
        self,
        instance_id: str,
        task_id: str,
        model_name: str,
        task_input: Dict[str, Any],
        metadata: Dict[str, Any] = None,
        timeout: float = 5.0
    ) -> bool:
        """
        Dispatch a task to TaskInstance via WebSocket

        Args:
            instance_id: Target instance identifier
            task_id: Unique task identifier
            model_name: Model name for the task
            task_input: Task input data
            metadata: Optional task metadata
            timeout: Timeout for task dispatch (default: 5.0s)

        Returns:
            True if dispatch successful, False otherwise
        """
        # Get connection without holding lock
        async with self._lock:
            websocket = self.connections.get(instance_id)

        if not websocket:
            logger.warning(f"No WebSocket connection for instance {instance_id}")
            self.total_dispatch_failures += 1
            return False

        try:
            # Send task message with timeout
            await asyncio.wait_for(
                websocket.send_json({
                    "type": "task",
                    "task_id": task_id,
                    "model_name": model_name,
                    "task_input": task_input,
                    "metadata": metadata or {}
                }),
                timeout=timeout
            )
            self.total_tasks_dispatched += 1
            logger.debug(f"Dispatched task {task_id} to instance {instance_id} via WebSocket")
            return True

        except asyncio.TimeoutError:
            logger.warning(f"Timeout dispatching task {task_id} to instance {instance_id}")
            self.total_dispatch_failures += 1
            return False
        except Exception as e:
            logger.warning(f"Failed to dispatch task {task_id} to instance {instance_id}: {e}")
            self.total_dispatch_failures += 1
            # Mark connection for cleanup
            await self.unregister_instance(instance_id)
            return False

    def has_connection(self, instance_id: str) -> bool:
        """Check if instance has active WebSocket connection"""
        return instance_id in self.connections


# Global result submission manager instance
result_submission_manager = ResultSubmissionManager()

# Inject result submission manager into scheduler for WebSocket task dispatch
scheduler.result_submission_manager = result_submission_manager


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "scheduler", "version": "2.0.0"}


@app.get("/websocket/stats")
async def websocket_stats():
    """Get WebSocket connection statistics"""
    return {
        "result_submission": result_submission_manager.get_statistics(),
        "task_events": {
            "active_connections": len(task_event_manager.active_connections)
        }
    }


@app.post("/settings/set", response_model=SettingsSetResponse)
async def set_setting(request: SettingsSetRequest):
    """
    Set a configuration parameter

    Args:
        request: Settings set request containing key and value

    Returns:
        Result of setting operation
    """
    try:
        # Validate known configuration keys
        known_keys = [
            "predictor_strategy_debug",
            "fake_data_enabled",
            "fake_data_path",
            "async_scheduling_enabled",
            "async_max_queue_size",
            "async_retry_attempts",
            "async_retry_delay_ms",
            "async_num_workers",
            "async_batch_size",
            "use_lockfree",
            "probabilistic_quantiles"
        ]
        if request.key not in known_keys:
            return SettingsSetResponse(
                status="error",
                message=f"Unknown configuration key '{request.key}'. Known keys: {', '.join(known_keys)}",
                key=request.key,
                value=request.value
            )

        # Type validation for specific keys
        if request.key == "predictor_strategy_debug":
            if not isinstance(request.value, bool):
                return SettingsSetResponse(
                    status="error",
                    message=f"Configuration key '{request.key}' requires a boolean value",
                    key=request.key,
                    value=request.value
                )
        elif request.key == "fake_data_enabled":
            if not isinstance(request.value, bool):
                return SettingsSetResponse(
                    status="error",
                    message=f"Configuration key '{request.key}' requires a boolean value",
                    key=request.key,
                    value=request.value
                )
        elif request.key == "fake_data_path":
            if request.value is not None and not isinstance(request.value, str):
                return SettingsSetResponse(
                    status="error",
                    message=f"Configuration key '{request.key}' requires a string value or null",
                    key=request.key,
                    value=request.value
                )
        elif request.key == "use_lockfree":
            if not isinstance(request.value, bool):
                return SettingsSetResponse(
                    status="error",
                    message=f"Configuration key '{request.key}' requires a boolean value",
                    key=request.key,
                    value=request.value
                )
        elif request.key == "probabilistic_quantiles":
            if not isinstance(request.value, list):
                return SettingsSetResponse(
                    status="error",
                    message=f"Configuration key '{request.key}' requires a list value",
                    key=request.key,
                    value=request.value
                )
            # Validate list contents
            if not all(isinstance(x, (int, float)) for x in request.value):
                return SettingsSetResponse(
                    status="error",
                    message=f"Configuration key '{request.key}' requires a list of numbers",
                    key=request.key,
                    value=request.value
                )
            # Validate quantiles are between 0 and 1
            if not all(0 <= x <= 1 for x in request.value):
                return SettingsSetResponse(
                    status="error",
                    message=f"Configuration key '{request.key}' requires quantiles between 0 and 1",
                    key=request.key,
                    value=request.value
                )
            # Validate list is sorted
            if request.value != sorted(request.value):
                return SettingsSetResponse(
                    status="error",
                    message=f"Configuration key '{request.key}' requires quantiles to be sorted in ascending order",
                    key=request.key,
                    value=request.value
                )

        # Store the setting
        settings_storage[request.key] = request.value

        # Special handling: reinitialize strategy when certain settings change
        if request.key in ["fake_data_enabled", "fake_data_path", "probabilistic_quantiles"]:
            try:
                current_strategy_name = scheduler.get_current_strategy_name()
                if current_strategy_name:
                    # Only reinitialize if the strategy is probabilistic when quantiles change
                    if request.key == "probabilistic_quantiles" and current_strategy_name != "probabilistic":
                        logger.info(f"Quantiles updated but current strategy is {current_strategy_name}, skipping reinitialization")
                    else:
                        logger.info(f"Reinitializing {current_strategy_name} strategy with new settings")
                        scheduler.set_strategy(current_strategy_name)
            except Exception as e:
                logger.warning(f"Failed to reinitialize strategy after settings change: {e}")

        logger.info(f"Configuration updated: {request.key} = {request.value}")

        return SettingsSetResponse(
            status="success",
            message=f"Configuration '{request.key}' set successfully",
            key=request.key,
            value=request.value
        )

    except Exception as e:
        logger.error(f"Failed to set configuration: {e}")
        return SettingsSetResponse(
            status="error",
            message=str(e),
            key=request.key,
            value=request.value
        )


@app.post("/settings/get", response_model=SettingsGetResponse)
async def get_setting(request: SettingsGetRequest):
    """
    Get a configuration parameter

    Args:
        request: Settings get request containing key

    Returns:
        Configuration value if exists
    """
    try:
        key = request.key
        exists = key in settings_storage

        if not exists:
            return SettingsGetResponse(
                status="success",
                message=f"Configuration key '{key}' not found",
                key=key,
                value=None,
                exists=False
            )

        value = settings_storage[key]

        return SettingsGetResponse(
            status="success",
            message="OK",
            key=key,
            value=value,
            exists=True
        )

    except Exception as e:
        logger.error(f"Failed to get configuration: {e}")
        return SettingsGetResponse(
            status="error",
            message=str(e),
            key=request.key,
            value=None,
            exists=False
        )


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
        # Create scheduler request with optional task_id
        scheduler_req = SchedulerRequest(
            model_type=request.model_name,
            input_data=request.task_input,
            metadata=request.metadata,
            task_id=request.task_id  # Pass through task_id if provided
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


@app.post("/queue/submit_batch", response_model=QueueBatchSubmitResponse)
async def submit_batch_tasks(request: QueueBatchSubmitRequest):
    """
    Submit multiple tasks in batch to the scheduler

    This endpoint allows submitting many tasks at once for the same model.
    Each task is scheduled independently, and results are returned for all tasks.

    Args:
        request: Batch task submission request containing model_name and list of tasks

    Returns:
        Batch submission response with individual results for each task
    """
    try:
        total_tasks = len(request.tasks)
        results = []
        successful_count = 0
        failed_count = 0

        logger.info(f"Batch submission started: {total_tasks} tasks for model {request.model_name}")

        # Process each task in the batch
        for index, task_item in enumerate(request.tasks):
            try:
                # Create scheduler request for this task
                scheduler_req = SchedulerRequest(
                    model_type=request.model_name,
                    input_data=task_item.task_input,
                    metadata=task_item.metadata
                )

                # Execute scheduling
                response = scheduler.schedule(scheduler_req)

                # Record success
                results.append(BatchTaskResult(
                    index=index,
                    status="success",
                    task_id=response.task_id,
                    scheduled_ti=response.instance_id,
                    error=None
                ))
                successful_count += 1

            except RuntimeError as e:
                # Scheduling failed for this specific task
                logger.warning(f"Task {index} in batch failed to schedule: {e}")
                results.append(BatchTaskResult(
                    index=index,
                    status="error",
                    task_id=None,
                    scheduled_ti=None,
                    error=f"Scheduling failed: {str(e)}"
                ))
                failed_count += 1

            except Exception as e:
                # Unexpected error for this specific task
                logger.error(f"Task {index} in batch encountered unexpected error: {e}")
                results.append(BatchTaskResult(
                    index=index,
                    status="error",
                    task_id=None,
                    scheduled_ti=None,
                    error=f"Internal error: {str(e)}"
                ))
                failed_count += 1

        # Determine overall status
        if failed_count == 0:
            overall_status = "success"
            message = f"All {total_tasks} tasks submitted successfully"
        elif successful_count == 0:
            overall_status = "error"
            message = f"All {total_tasks} tasks failed to submit"
        else:
            overall_status = "partial"
            message = f"{successful_count} tasks succeeded, {failed_count} tasks failed"

        logger.info(f"Batch submission completed: {message}")

        return QueueBatchSubmitResponse(
            status=overall_status,
            message=message,
            total_tasks=total_tasks,
            successful_tasks=successful_count,
            failed_tasks=failed_count,
            results=results
        )

    except Exception as e:
        logger.error(f"Batch submission failed with critical error: {e}")
        raise HTTPException(status_code=500, detail=f"Batch submission failed: {str(e)}")


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


@app.post("/result/submit", response_model=ResultSubmitResponse)
async def submit_result(request: ResultSubmitRequest):
    """
    Receive task result submission from TaskInstance

    This endpoint is called by TaskInstance when a task completes.
    It processes the result and updates task tracking.

    Args:
        request: Result submission request containing task_id, result, and execution metrics

    Returns:
        Confirmation response
    """
    try:
        # Find instance UUID using cached mapping (optimized for high load)
        instance_uuid = scheduler.get_uuid_by_instance_id(request.instance_id)

        if instance_uuid is None:
            logger.warning(
                f"Received result for unknown instance: {request.instance_id}"
            )
            return ResultSubmitResponse(
                status="error",
                message=f"Instance {request.instance_id} not found"
            )

        # Process task completion
        total_time = scheduler.handle_task_completion(
            task_id=request.task_id,
            instance_uuid=instance_uuid,
            execution_time=request.execution_time
        )

        # Optional: Store result in TaskTracker
        print(request.result)
        scheduler.task_tracker.mark_completed(request.task_id, request.result)

        # Broadcast task completion event to WebSocket clients
        task_info_obj = scheduler.task_tracker.get_task_info(request.task_id)
        if task_info_obj:
            # Deep copy task data BEFORE broadcasting to avoid race condition
            # This ensures data remains valid even if broadcast is delayed
            task_event_data = {
                'task_id': task_info_obj.task_id,
                'task_status': task_info_obj.task_status.value,
                'scheduled_ti': str(task_info_obj.scheduled_ti),
                'submit_time': task_info_obj.submit_time,
                'model_name': task_info_obj.model_name,
                'result': task_info_obj.result,
                'completion_time': task_info_obj.completion_time,
                'replica_id': request.replica_id  # Include replica_id from the submission request
            }

            # Broadcast to all connected test clients
            num_clients = await task_event_manager.broadcast_task_completion(task_event_data)
            logger.debug(
                f"[HTTP] Broadcasted completion event for task {request.task_id} "
                f"to {num_clients} client(s)"
            )

            # Remove task from local tracking after successful notification
            scheduler.task_tracker.remove_task(request.task_id)
            logger.debug(f"[TaskTracker] Removed completed task {request.task_id}")

        logger.info(
            f"Received result for task {request.task_id} from instance {request.instance_id}"
        )

        message = f"Result for task {request.task_id} received"
        if total_time:
            message += f" (total time: {total_time:.2f}ms)"

        return ResultSubmitResponse(
            status="success",
            message=message
        )

    except Exception as e:
        logger.error(f"Failed to process result submission: {e}")
        return ResultSubmitResponse(
            status="error",
            message=str(e)
        )


@app.post("/notify/task_complete")
async def notify_task_completion(notification: TaskCompletionNotification):
    """
    Receive task completion notification (legacy endpoint)

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

@app.post("/result/fetch")
async def fetch_result(request: FetchResultRequest):
    task_id = request.task_id
    
    task_info = scheduler.task_tracker.get_task_info(task_id)
    
    if task_info.task_status == TaskStatus.COMPLETED:
        return FetchResultResponse(result=task_info.result)
    

@app.get("/result/fetch_all_completed")
async def fetch_all_completed_result():
    logger.info("Got fetch all request")
    res = scheduler.task_tracker.get_tasks_by_status(TaskStatus.COMPLETED)
    logger.info("Lookup finished")
    return res


@app.get("/task/all_tasks", response_model=AllTasksResponse)
async def get_all_tasks():
    """
    Get all tasks tracked by the scheduler

    Returns:
        All task information from Task Tracker
    """
    try:
        # Get all tasks from TaskTracker
        all_tasks = scheduler.task_tracker.get_all_tasks()

        # Convert TaskInfo objects to TaskInfoItem models
        task_items = []
        for task_id, task_info in all_tasks.items():
            task_item = TaskInfoItem(
                task_id=task_info.task_id,
                task_status=task_info.task_status,
                scheduled_ti=str(task_info.scheduled_ti),
                submit_time=task_info.submit_time,
                model_name=task_info.model_name,
                result=task_info.result,
                completion_time=task_info.completion_time
            )
            task_items.append(task_item)

        return AllTasksResponse(
            status="success",
            total_tasks=len(task_items),
            tasks=task_items
        )

    except Exception as e:
        logger.error(f"Failed to get all tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/task/clear", response_model=ClearTasksResponse)
async def clear_all_tasks():
    """
    Clear all tasks from the tracker and scheduler queues

    This endpoint performs a comprehensive cleanup:
    1. Clears all tasks from TaskTracker (queued, scheduled, completed)
    2. Clears pending tasks cache in scheduling strategy
    3. Clears all model scheduler queues (if async scheduling is enabled)

    This is useful for resetting the system between experiments or test runs.

    Returns:
        Number of tasks cleared and status message
    """
    try:
        # Clear all tasks from task tracker
        tracker_cleared = scheduler.task_tracker.clear_all()
        logger.info(f"Cleared {tracker_cleared} tasks from tracker")

        # Clear strategy's pending tasks cache if it has the method
        strategy_cleared = 0
        if hasattr(scheduler.strategy, 'clear_pending_tasks'):
            scheduler.strategy.clear_pending_tasks()
            logger.info("Cleared pending tasks cache in scheduling strategy")

        # Clear model scheduler queues if async scheduling is enabled
        queue_cleared = 0
        if scheduler.async_scheduler_manager and scheduler.async_scheduler_manager.is_enabled():
            queue_cleared = scheduler.async_scheduler_manager.clear_all_queues()
            logger.info(f"Cleared {queue_cleared} tasks from model scheduler queues")

        total_cleared = tracker_cleared + queue_cleared

        return ClearTasksResponse(
            status="success",
            message=f"Cleared {total_cleared} tasks (tracker: {tracker_cleared}, queues: {queue_cleared})",
            cleared_count=total_cleared
        )

    except Exception as e:
        logger.error(f"Failed to clear tasks: {e}")
        return ClearTasksResponse(
            status="error",
            message=f"Failed to clear tasks: {str(e)}",
            cleared_count=0
        )




@app.post("/scheduler/async/enable")
async def enable_async_scheduling():
    """
    Enable asynchronous scheduling
    
    Returns:
        Status message
    """
    try:
        if scheduler.is_async_scheduling_enabled():
            return {
                "status": "success",
                "message": "Async scheduling is already enabled"
            }
        
        max_queue_size = settings_storage.get("async_max_queue_size", 10000)
        retry_attempts = settings_storage.get("async_retry_attempts", 3)
        retry_delay_ms = settings_storage.get("async_retry_delay_ms", 100)
        num_workers = settings_storage.get("async_num_workers", 4)
        batch_size = settings_storage.get("async_batch_size", 10)

        scheduler.enable_async_scheduling(
            max_queue_size=max_queue_size,
            retry_attempts=retry_attempts,
            retry_delay_ms=retry_delay_ms,
            num_workers=num_workers,
            batch_size=batch_size
        )

        settings_storage["async_scheduling_enabled"] = True

        return {
            "status": "success",
            "message": "Optimized async scheduling enabled",
            "config": {
                "max_queue_size": max_queue_size,
                "retry_attempts": retry_attempts,
                "retry_delay_ms": retry_delay_ms,
                "num_workers": num_workers,
                "batch_size": batch_size
            }
        }
    except Exception as e:
        logger.error(f"Failed to enable async scheduling: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scheduler/async/disable")
async def disable_async_scheduling():
    """
    Disable asynchronous scheduling
    
    Returns:
        Status message
    """
    try:
        if not scheduler.is_async_scheduling_enabled():
            return {
                "status": "success",
                "message": "Async scheduling is already disabled"
            }
        
        scheduler.disable_async_scheduling()
        settings_storage["async_scheduling_enabled"] = False
        
        return {
            "status": "success",
            "message": "Async scheduling disabled"
        }
    except Exception as e:
        logger.error(f"Failed to disable async scheduling: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scheduler/async/statistics")
async def get_async_statistics():
    """
    Get asynchronous scheduling statistics
    
    Returns:
        Statistics for all model schedulers
    """
    try:
        return scheduler.get_async_statistics()
    except Exception as e:
        logger.error(f"Failed to get async statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scheduler/async/pending")
async def get_pending_counts(model_type: Optional[str] = Query(None)):
    """
    Get pending task counts
    
    Args:
        model_type: Optional model type filter
        
    Returns:
        Pending task count
    """
    try:
        count = scheduler.get_pending_count(model_type)
        return {
            "status": "success",
            "model_type": model_type,
            "pending_count": count
        }
    except Exception as e:
        logger.error(f"Failed to get pending counts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/queue/submit_async", response_model=QueueSubmitResponse)
async def submit_task_async(request: QueueSubmitRequest):
    """
    Submit task for asynchronous scheduling

    This endpoint immediately returns a task_id without blocking.
    The task will be scheduled in the background.

    Args:
        request: Task submission request

    Returns:
        Task ID (scheduled_ti will be "pending")
    """
    try:
        if not scheduler.is_async_scheduling_enabled():
            raise HTTPException(
                status_code=503,
                detail="Async scheduling is not enabled. Use POST /scheduler/async/enable first."
            )

        # Create scheduler request
        scheduler_req = SchedulerRequest(
            model_type=request.model_name,
            input_data=request.task_input,
            metadata=request.metadata
        )

        # Submit for async scheduling
        task_id = scheduler.schedule_async(scheduler_req)

        return QueueSubmitResponse(
            status="success",
            task_id=task_id,
            scheduled_ti="pending"  # Indicates async scheduling
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit async task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Profiling Endpoints
# ============================================================================

@app.post("/scheduler/profiling/enable")
async def enable_profiling(model_type: Optional[str] = Query(None)):
    """
    Enable detailed timing profiling for scheduler

    Args:
        model_type: Optional model type to enable profiling for (None = all models)

    Returns:
        Status message
    """
    try:
        if not scheduler.is_async_scheduling_enabled():
            raise HTTPException(
                status_code=503,
                detail="Async scheduling must be enabled first"
            )

        scheduler.enable_profiling(model_type)

        return {
            "status": "success",
            "message": f"Profiling enabled for {'all models' if not model_type else model_type}",
            "model_type": model_type
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to enable profiling: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scheduler/profiling/disable")
async def disable_profiling(model_type: Optional[str] = Query(None)):
    """
    Disable profiling for scheduler

    Args:
        model_type: Optional model type to disable profiling for (None = all models)

    Returns:
        Status message
    """
    try:
        if not scheduler.is_async_scheduling_enabled():
            raise HTTPException(
                status_code=503,
                detail="Async scheduling must be enabled first"
            )

        scheduler.disable_profiling(model_type)

        return {
            "status": "success",
            "message": f"Profiling disabled for {'all models' if not model_type else model_type}",
            "model_type": model_type
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disable profiling: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scheduler/profiling/profiles")
async def get_profiling_data(model_type: Optional[str] = Query(None)):
    """
    Get collected timing profiles

    Args:
        model_type: Optional model type filter (None = all models)

    Returns:
        Timing profiles with detailed breakdown
    """
    try:
        if not scheduler.is_async_scheduling_enabled():
            raise HTTPException(
                status_code=503,
                detail="Async scheduling must be enabled first"
            )

        profiles_dict = scheduler.get_timing_profiles(model_type)

        # Convert profiles to serializable format
        result = {}
        for mt, profiles in profiles_dict.items():
            result[mt] = {
                "count": len(profiles),
                "profiles": [
                    {
                        "task_id": p.task_id,
                        "model_type": p.model_type,
                        "enqueue_time": p.enqueue_time,
                        "start_time": p.start_time,
                        "end_time": p.end_time,
                        "queue_wait_time": p.queue_wait_time,
                        "strategy_select_time": p.strategy_select_time,
                        "enqueue_api_time": p.enqueue_api_time,
                        "tracker_register_time": p.tracker_register_time,
                        "queue_update_time": p.queue_update_time,
                        "total_time": p.total_time,
                        "success": p.success,
                        "error_message": p.error_message,
                        "retry_count": p.retry_count
                    }
                    for p in profiles
                ]
            }

        return {
            "status": "success",
            "model_type": model_type,
            "data": result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get profiling data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scheduler/profiling/save")
async def save_profiling_data(output_dir: str = Query("/tmp/scheduler_profiles")):
    """
    Save timing profiles to JSON files

    Args:
        output_dir: Directory to save profile files

    Returns:
        Status message with file paths
    """
    try:
        if not scheduler.is_async_scheduling_enabled():
            raise HTTPException(
                status_code=503,
                detail="Async scheduling must be enabled first"
            )

        scheduler.save_timing_profiles(output_dir)

        return {
            "status": "success",
            "message": f"Timing profiles saved to {output_dir}",
            "output_dir": output_dir
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save profiling data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/result_submit")
async def websocket_result_submit(websocket: WebSocket):
    """
    Bidirectional WebSocket endpoint for TaskInstance communication

    This provides a persistent, low-latency connection for both task dispatch
    and result submission, avoiding HTTP connection overhead.

    Protocol:
        1. TaskInstance connects and sends registration message:
           {"type": "register", "instance_id": "ti-8000"}

        2. Scheduler sends tasks to TaskInstance:
           {
               "type": "task",
               "task_id": "task-123",
               "model_name": "gpt-3.5",
               "task_input": {...},
               "metadata": {...}
           }

        3. TaskInstance acknowledges task receipt:
           {"type": "task_ack", "task_id": "task-123", "success": true/false, "message": "..."}

        4. TaskInstance sends results as they complete:
           {
               "type": "result",
               "task_id": "task-123",
               "instance_id": "ti-8000",
               "execution_time": 150.5,
               "result": {...},
               "metadata": {...}
           }

        5. Scheduler responds with acknowledgment:
           {"type": "ack", "task_id": "task-123", "success": true, "message": "..."}
    """
    instance_id = None
    try:
        # Accept the WebSocket connection first
        await websocket.accept()

        # Wait for registration message with timeout
        try:
            registration_data = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            await websocket.close(code=1008, reason="Registration timeout")
            logger.warning("WebSocket registration timeout")
            return

        if registration_data.get("type") != "register":
            await websocket.close(code=1008, reason="First message must be registration")
            return

        instance_id = registration_data.get("instance_id")
        if not instance_id:
            await websocket.close(code=1008, reason="instance_id required")
            return

        # Register the connection with limit checking (already_accepted=True)
        try:
            await result_submission_manager.register_instance(instance_id, websocket, already_accepted=True)
        except RuntimeError as e:
            # Max connections reached
            await websocket.close(code=1008, reason=str(e))
            logger.warning(f"Connection rejected for {instance_id}: {e}")
            return

        # Send registration confirmation
        await websocket.send_json({
            "type": "registered",
            "instance_id": instance_id,
            "message": "Registration successful"
        })

        # Helper function to process a single result
        async def process_single_result(msg):
            """Process a single result message."""
            try:
                # Extract result data
                task_id = msg.get("task_id")
                execution_time = msg.get("execution_time")
                result_data = msg.get("result")
                metadata = msg.get("metadata", {})
                replica_id = msg.get("replica_id")  # Extract replica_id from message

                if not all([task_id, execution_time is not None, result_data is not None]):
                    await result_submission_manager.send_ack(
                        instance_id, task_id or "unknown",
                        False, "Missing required fields"
                    )
                    return

                # Find instance UUID using cached mapping
                instance_uuid = scheduler.get_uuid_by_instance_id(instance_id)

                if instance_uuid is None:
                    await result_submission_manager.send_ack(
                        instance_id, task_id,
                        False, f"Instance {instance_id} not found"
                    )
                    return

                # Process task completion
                total_time = scheduler.handle_task_completion(
                    task_id=task_id,
                    instance_uuid=instance_uuid,
                    execution_time=execution_time
                )

                # Store result in TaskTracker
                scheduler.task_tracker.mark_completed(task_id, result_data)

                # Broadcast task completion event to WebSocket clients
                task_info_obj = scheduler.task_tracker.get_task_info(task_id)
                if task_info_obj:
                    # Deep copy task data BEFORE broadcasting to avoid race condition
                    # This ensures data remains valid even if broadcast is delayed
                    task_event_data = {
                        'task_id': task_info_obj.task_id,
                        'task_status': task_info_obj.task_status.value,
                        'scheduled_ti': str(task_info_obj.scheduled_ti),
                        'submit_time': task_info_obj.submit_time,
                        'model_name': task_info_obj.model_name,
                        'result': task_info_obj.result,
                        'completion_time': task_info_obj.completion_time,
                        'replica_id': replica_id  # Include replica_id from the WebSocket message
                    }

                    # Broadcast to all connected test clients
                    num_clients = await task_event_manager.broadcast_task_completion(task_event_data)
                    logger.debug(
                        f"[WebSocket] Broadcasted completion event for task {task_id} "
                        f"to {num_clients} client(s)"
                    )

                    # Remove task from tracker after successful broadcast
                    scheduler.task_tracker.remove_task(task_id)
                    logger.debug(f"[TaskTracker] Removed completed task {task_id}")

                # Send acknowledgment
                await result_submission_manager.send_ack(
                    instance_id, task_id, True,
                    f"Result received (total_time: {total_time:.3f}ms)"
                )

                logger.info(f"[WebSocket] Received result for task {task_id} from {instance_id}")

            except Exception as e:
                logger.error(f"Error processing result: {e}", exc_info=True)
                await result_submission_manager.send_ack(
                    instance_id, msg.get("task_id", "unknown"),
                    False, f"Processing error: {str(e)}"
                )

        # Main message processing loop
        while True:
            try:
                message = await websocket.receive_json()

                msg_type = message.get("type")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue

                elif msg_type == "task_ack":
                    # TaskInstance acknowledges task receipt
                    task_id = message.get("task_id")
                    success = message.get("success", False)
                    ack_message = message.get("message", "")

                    if success:
                        logger.info(f"[WebSocket] Task {task_id} acknowledged by {instance_id}: {ack_message}")
                    else:
                        logger.warning(f"[WebSocket] Task {task_id} rejected by {instance_id}: {ack_message}")
                    continue

                # Handle batch messages
                elif msg_type == "batch":
                    messages = message.get("messages", [])
                    logger.debug(f"[WebSocket] Processing batch of {len(messages)} messages from {instance_id}")

                    for msg in messages:
                        # Process each message in the batch
                        await process_single_result(msg)
                    continue

                elif msg_type == "result":
                    # Process single result submission
                    await process_single_result(message)

                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}"
                    })
                    continue

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket receive error: {e}")
                break

    except WebSocketDisconnect:
        logger.info(f"TaskInstance {instance_id} disconnected during registration")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        if instance_id:
            await result_submission_manager.unregister_instance(instance_id)


@app.websocket("/ws/task_events")
async def websocket_task_events(websocket: WebSocket):
    """
    WebSocket endpoint for real-time task completion events

    Clients connect to this endpoint to receive immediate notifications
    when tasks complete, eliminating the need for polling.

    Event format:
        {
            "event": "task_completed",
            "data": {
                "task_id": str,
                "task_status": str,
                "scheduled_ti": str,
                "submit_time": float,
                "model_name": str,
                "result": dict,
                "completion_time": float
            }
        }
    """
    await task_event_manager.connect(websocket)
    try:
        # Keep connection alive and listen for client messages (e.g., ping/pong)
        while True:
            # Wait for any message from client (mostly for keepalive)
            try:
                data = await websocket.receive_text()
                # Echo back to confirm connection is alive
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await task_event_manager.disconnect(websocket)


async def cleanup_websocket_connections():
    """Periodic task to clean up dead WebSocket connections"""
    while True:
        try:
            await asyncio.sleep(60)  # Run every 60 seconds
            cleaned = await result_submission_manager.cleanup_dead_connections()
            if cleaned > 0:
                logger.info(f"Periodic cleanup: removed {cleaned} dead connections")
        except Exception as e:
            logger.error(f"Error in periodic cleanup task: {e}")


@app.on_event("startup")
async def startup_event():
    """Initialize scheduler"""
    logger.info("Starting SwarmPilot Scheduler v2.0...")

    # Log whether using lock-free implementation
    if settings_storage.get("use_lockfree", True):
        logger.info("Using LOCK-FREE implementation for maximum performance")
    else:
        logger.info("Using original implementation")

    # Start background cleanup task for WebSocket connections
    asyncio.create_task(cleanup_websocket_connections())
    logger.info("Started WebSocket connection cleanup task")

    # Load default configuration
    default_config = os.environ.get("SCHEDULER_CONFIG_PATH")
    if default_config and os.path.exists(default_config):
        try:
            scheduler.load_task_instances_from_config(default_config)
            logger.info(f"Loaded config from {default_config}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

    # Auto-enable async scheduling if configured
    if settings_storage.get("async_scheduling_enabled", False):
        try:
            logger.info("Auto-enabling async scheduling from configuration...")
            scheduler.enable_async_scheduling(
                max_queue_size=settings_storage.get("async_max_queue_size", 50000),
                retry_attempts=settings_storage.get("async_retry_attempts", 3),
                retry_delay_ms=settings_storage.get("async_retry_delay_ms", 50),
                num_workers=settings_storage.get("async_num_workers", 8),
                batch_size=settings_storage.get("async_batch_size", 20)
            )
            logger.info("Async scheduling enabled successfully")
        except Exception as e:
            logger.error(f"Failed to enable async scheduling: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down SwarmPilot Scheduler...")
    
    # Disable async scheduling if enabled
    if scheduler.is_async_scheduling_enabled():
        logger.info("Disabling async scheduling...")
        scheduler.disable_async_scheduling()
    
    logger.info("SwarmPilot Scheduler shutdown complete")


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="SwarmPilot Scheduler API Server")
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("SCHEDULER_HOST", "0.0.0.0"),
        help="Host to bind the server (default: 0.0.0.0, env: SCHEDULER_HOST)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SCHEDULER_PORT", "8200")),
        help="Port to bind the server (default: 8200, env: SCHEDULER_PORT)"
    )
    parser.add_argument(
        "--enable-profile",
        action="store_true",
        default=False,
        help="Enable profiling middleware, when enabled, profile=true will be available for all HTTP endpoints."
    )
    parser.add_argument(
        "--enable-taskinstance-profile",
        action="store_true",
        default=False,
        help="Enable profiling on all registered TaskInstances. When enabled, TaskInstances will automatically profile every 10th request and save results in speedscope format."
    )

    args = parser.parse_args()

    # Enable profiler middleware if requested
    if args.enable_profile:
        logger.info("Profiling middleware enabled - use ?profile=true on any endpoint")
        enable_profiler_middleware()
    else:
        logger.info("Profiling middleware disabled")

    # Log TaskInstance profiling setting
    if args.enable_taskinstance_profile:
        logger.info("TaskInstance profiling enabled")
        logger.info("  IMPORTANT: TaskInstances must be started with --enable-profile flag")
        logger.info("  TaskInstances will automatically profile every 10th request")
        logger.info("  Profile files will be saved to: taskinstance_profile_{port}/")
    else:
        logger.info("TaskInstance profiling disabled")

    logger.info(f"Starting SwarmPilot Scheduler on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
