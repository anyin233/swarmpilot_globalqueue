"""
SwarmPilot Scheduler Core

Main scheduler class that routes tasks to appropriate TaskInstances.
Integrates with TaskTracker for task state management.
"""

from loguru import logger
from typing import Dict, Any, List, Optional, Callable, Tuple
from uuid import uuid4, UUID
import yaml
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, Future
import threading
from queue import Queue, Empty
from dataclasses import dataclass

from .client import TaskInstanceClient
from .task_tracker import TaskTracker
from .models import SchedulerRequest, SchedulerResponse
from .strategies import (
    BaseStrategy,
    ShortestQueueStrategy,
    RoundRobinStrategy,
    WeightedStrategy,
    ProbabilisticQueueStrategy,
    TaskInstance,
    SelectionRequest
)
import pyinstrument
from .model_scheduler import ModelSchedulerManager
from .lockfree_scheduler_manager import LockFreeSchedulerManager
from .lockfree_task_tracker import LockFreeTaskTracker
from .utils import is_valid_uuid


@dataclass
class QueueUpdateTask:
    """Represents a queue update task to be processed asynchronously"""
    task_type: str  # 'schedule' or 'completion'
    task_id: str
    timestamp: float
    # For schedule updates
    selected_instance: Optional[TaskInstance] = None
    request: Optional[SelectionRequest] = None
    # For completion updates
    instance_uuid: Optional[UUID] = None
    execution_time: Optional[float] = None


class SwarmPilotScheduler:
    """
    Main scheduler class that routes tasks to appropriate TaskInstances

    Features:
    - Multiple scheduling strategies
    - Task state tracking via TaskTracker
    - Timing statistics
    - Dynamic instance management
    """

    def __init__(
        self,
        strategy: Optional[BaseStrategy] = None,
        get_debug_enabled: Optional[Callable[[], bool]] = None,
        get_fake_data_enabled: Optional[Callable[[], bool]] = None,
        get_fake_data_path: Optional[Callable[[], Optional[str]]] = None,
        get_probabilistic_quantiles: Optional[Callable[[], list]] = None,
        use_lockfree: bool = True  # Default to lock-free implementation
    ):
        """
        Initialize Scheduler

        Args:
            strategy: TaskInstance selection strategy (defaults to ShortestQueue)
            get_debug_enabled: Callable to check if debug logging is enabled
            get_fake_data_enabled: Callable to check if fake data mode is enabled
            get_fake_data_path: Callable to get fake data path
            get_probabilistic_quantiles: Callable to get probabilistic strategy quantiles
            use_lockfree: Whether to use lock-free implementation (default: True)
        """
        self.taskinstances: List[TaskInstance] = []
        self._strategy = strategy
        self.use_lockfree = use_lockfree

        # Use lock-free or original task tracker based on configuration
        if use_lockfree:
            self.task_tracker = LockFreeTaskTracker(
                max_history=100000,
                cleanup_interval=60
            )
            logger.info("Using lock-free task tracker implementation")
        else:
            self.task_tracker = TaskTracker()
            logger.info("Using original task tracker implementation")

        self.last_routing_info: Optional[Dict[str, Any]] = None
        self.get_debug_enabled = get_debug_enabled or (lambda: False)
        self.get_fake_data_enabled = get_fake_data_enabled or (lambda: False)
        self.get_fake_data_path = get_fake_data_path or (lambda: None)
        self.get_probabilistic_quantiles = get_probabilistic_quantiles or (lambda: [0.25, 0.5, 0.75, 0.99])
        self._current_strategy_name: Optional[str] = None

        # Track request arrival times for timing calculation
        self.request_times: Dict[str, tuple[float, str]] = {}

        # Track timing statistics
        self.timing_statistics: List[tuple[str, float, float]] = []

        # Asynchronous scheduling manager (will be lock-free or original based on config)
        self.async_scheduler_manager: Optional[ModelSchedulerManager] = None

        # Cache for instance_id to UUID mapping to avoid expensive lookups
        # Format: {instance_id: uuid}
        self._instance_id_to_uuid: Dict[str, UUID] = {}

        # Background queue for processing queue updates
        self._queue_update_queue: Queue[Optional[QueueUpdateTask]] = Queue()
        self._queue_update_thread: Optional[threading.Thread] = None
        self._queue_update_shutdown = threading.Event()

        # Start background queue update worker
        self._start_queue_update_worker()

        # Reference to result submission manager (will be injected from api.py)
        self.result_submission_manager = None

        # Thread pool for parallel task dispatch and queue updates
        self.executor = ThreadPoolExecutor(max_workers=4)

    @property
    def strategy(self) -> BaseStrategy:
        """Get the current strategy, creating default if not set"""
        if self._strategy is None:
            self._strategy = ShortestQueueStrategy(
                self.taskinstances,
                predictor_url="http://localhost:8100",
                predictor_timeout=10.0,
                get_debug_enabled=self.get_debug_enabled
            )
        return self._strategy

    @strategy.setter
    def strategy(self, strategy: BaseStrategy):
        """Set a new strategy"""
        self._strategy = strategy
        if self._strategy:
            self._strategy.taskinstances = self.taskinstances

    def set_strategy(self, strategy_name: str) -> None:
        """Set strategy by name"""
        strategy_map = {
            "shortest_queue": ShortestQueueStrategy,
            "round_robin": RoundRobinStrategy,
            "weighted": WeightedStrategy,
            "probabilistic": ProbabilisticQueueStrategy
        }

        strategy_class = strategy_map.get(strategy_name.lower())
        if not strategy_class:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        # Get fake data settings
        fake_data_enabled = self.get_fake_data_enabled()
        fake_data_path = self.get_fake_data_path()

        if strategy_class == ShortestQueueStrategy:
            self.strategy = strategy_class(
                self.taskinstances,
                predictor_url="http://localhost:8100",
                predictor_timeout=10.0,
                get_debug_enabled=self.get_debug_enabled,
                fake_data_bypass=fake_data_enabled,
                fake_data_path=fake_data_path
            )
        elif strategy_class == ProbabilisticQueueStrategy:
            quantiles = self.get_probabilistic_quantiles()
            logger.info(
                f"Initializing ProbabilisticQueueStrategy: "
                f"config_quantiles={quantiles}, fake_data={fake_data_enabled}"
            )
            if fake_data_enabled:
                logger.info(
                    f"Fake data mode enabled - strategy will use predictor's fake percentiles "
                    f"if available, otherwise fall back to config_quantiles"
                )
            self.strategy = strategy_class(
                self.taskinstances,
                predictor_url="http://localhost:8100",
                predictor_timeout=10.0,
                quantiles=quantiles,
                get_debug_enabled=self.get_debug_enabled,
                fake_data_bypass=fake_data_enabled,
                fake_data_path=fake_data_path
            )
        else:
            self.strategy = strategy_class(self.taskinstances)

        self._current_strategy_name = strategy_name
        logger.info(f"Set scheduling strategy to: {strategy_name} (fake_data_enabled={fake_data_enabled}, fake_data_path={fake_data_path})")

    def get_current_strategy_name(self) -> Optional[str]:
        """Get current strategy name"""
        return self._current_strategy_name

    def enable_async_scheduling(
        self,
        max_queue_size: int = 10000,
        retry_attempts: int = 3,
        retry_delay_ms: int = 100,
        num_workers: int = 4,
        batch_size: int = 10
    ):
        """
        Enable asynchronous scheduling (optimized high-throughput version)

        Args:
            max_queue_size: Maximum pending queue size per model (default: 10000)
            retry_attempts: Number of retry attempts for failed scheduling (default: 3)
            retry_delay_ms: Delay between retries in milliseconds (default: 100)
            num_workers: Number of worker threads per model (default: 4)
            batch_size: Batch size for processing (default: 10)

        Performance:
            - Default config (4 workers, batch 10): 400-600 QPS
            - High QPS config (8 workers, batch 20): 1000+ QPS
            - Lock-free config (8 workers, batch 20): 10000+ QPS
        """
        if self.async_scheduler_manager is not None:
            logger.warning("Async scheduling already enabled")
            return

        # Choose implementation based on use_lockfree flag
        if self.use_lockfree:
            # Use lock-free scheduler manager for ultra-high performance
            self.async_scheduler_manager = LockFreeSchedulerManager(
                task_tracker=self.task_tracker,  # Already using lock-free tracker if use_lockfree=True
                max_queue_size=max_queue_size,
                retry_attempts=retry_attempts,
                retry_delay_ms=retry_delay_ms,
                num_workers=num_workers,
                batch_size=batch_size
            )
            logger.info(f"Using lock-free async scheduler (workers={num_workers}, batch={batch_size})")
        else:
            # Use original optimized scheduler
            self.async_scheduler_manager = ModelSchedulerManager(
                strategy=self.strategy,
                task_tracker=self.task_tracker,
                taskinstances=self.taskinstances,
                max_queue_size=max_queue_size,
                retry_attempts=retry_attempts,
                retry_delay_ms=retry_delay_ms,
                num_workers=num_workers,
                batch_size=batch_size
            )
            logger.info(f"Using original async scheduler (workers={num_workers}, batch={batch_size})")

        # Enable the scheduler manager
        if self.use_lockfree:
            # Lock-free manager needs to be started
            self.async_scheduler_manager.start()
        else:
            # Original manager uses enable()
            self.async_scheduler_manager.enable()
    
    def disable_async_scheduling(self):
        """Disable asynchronous scheduling"""
        if self.async_scheduler_manager is None:
            return

        # Call appropriate disable method based on implementation
        if self.use_lockfree:
            self.async_scheduler_manager.stop()
        else:
            self.async_scheduler_manager.disable()

        self.async_scheduler_manager = None
        logger.info("Async scheduling disabled")
    
    def is_async_scheduling_enabled(self) -> bool:
        """Check if async scheduling is enabled"""
        if self.async_scheduler_manager is None:
            return False

        # Check based on implementation
        if self.use_lockfree:
            # Lock-free manager is enabled if it's running
            return self.async_scheduler_manager._running
        else:
            # Original manager has is_enabled() method
            return self.async_scheduler_manager.is_enabled()
    
    def schedule_async(self, request: SchedulerRequest) -> str:
        """
        Schedule a task asynchronously
        
        Args:
            request: Scheduler request
            
        Returns:
            task_id: Generated task ID (task will be scheduled in background)
        """
        if not self.is_async_scheduling_enabled():
            raise RuntimeError("Async scheduling is not enabled")
        
        # Submit to async scheduler manager
        task_id = self.async_scheduler_manager.submit_task(request)
        
        logger.info(f"Task {task_id} submitted for async scheduling (model: {request.model_type})")
        return task_id
    
    def get_async_statistics(self) -> Dict[str, Any]:
        """Get async scheduling statistics"""
        if self.async_scheduler_manager is None:
            return {"enabled": False}
        
        return self.async_scheduler_manager.get_statistics()
    
    def get_pending_count(self, model_type: Optional[str] = None) -> int:
        """
        Get pending task count in async queues

        Args:
            model_type: Specific model type, or None for total

        Returns:
            Number of pending tasks
        """
        if self.async_scheduler_manager is None:
            return 0

        return self.async_scheduler_manager.get_pending_count(model_type)

    def enable_profiling(self, model_type: Optional[str] = None):
        """
        Enable detailed timing profiling

        Args:
            model_type: Model type to enable profiling for, or None for all
        """
        if self.async_scheduler_manager is None:
            raise RuntimeError("Async scheduling is not enabled")

        self.async_scheduler_manager.enable_profiling(model_type)
        logger.info(f"Profiling enabled for {'all models' if not model_type else model_type}")

    def disable_profiling(self, model_type: Optional[str] = None):
        """
        Disable profiling

        Args:
            model_type: Model type to disable profiling for, or None for all
        """
        if self.async_scheduler_manager is None:
            raise RuntimeError("Async scheduling is not enabled")

        self.async_scheduler_manager.disable_profiling(model_type)
        logger.info(f"Profiling disabled for {'all models' if not model_type else model_type}")

    def get_timing_profiles(self, model_type: Optional[str] = None):
        """
        Get collected timing profiles

        Args:
            model_type: Model type filter, or None for all

        Returns:
            Dictionary mapping model_type to list of timing profiles
        """
        if self.async_scheduler_manager is None:
            return {}

        return self.async_scheduler_manager.get_timing_profiles(model_type)

    def save_timing_profiles(self, output_dir: str):
        """
        Save timing profiles to JSON files

        Args:
            output_dir: Directory to save profile files
        """
        if self.async_scheduler_manager is None:
            raise RuntimeError("Async scheduling is not enabled")

        self.async_scheduler_manager.save_all_timing_profiles(output_dir)
        logger.info(f"Timing profiles saved to {output_dir}")

    def load_task_instances_from_config(self, config_path: str) -> None:
        """Load TaskInstances from configuration file"""
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)

        instances = data.get('instances', [])
        self.taskinstances.clear()

        for instance_config in instances:
            if isinstance(instance_config, dict):
                host = instance_config.get('host', 'localhost')
                port = instance_config.get('port', 8100)
                base_url = f"http://{host}:{port}"
                model_name = instance_config.get('model_name')  # Optional model_name from config
            else:
                base_url = instance_config
                model_name = None

            ti_uuid = uuid4()
            client = TaskInstanceClient(base_url)

            # Fetch status once during loading to cache model_type and instance_id
            instance_id_cached = None
            actual_model_type = model_name  # Use config model_name as fallback

            try:
                status = client.get_status()
                if status.instance_id:
                    instance_id_cached = status.instance_id
                    self._instance_id_to_uuid[status.instance_id] = ti_uuid
                    logger.debug(f"Cached instance_id mapping: {status.instance_id} -> {ti_uuid}")

                # Use actual model_type from status if available
                if status.model_type:
                    actual_model_type = status.model_type
                    logger.debug(f"Cached model_type: {status.model_type}")
            except Exception as e:
                logger.warning(f"Could not get instance info for caching during config loading: {e}")

            # Create TaskInstance with cached information
            task_instance = TaskInstance(
                uuid=ti_uuid,
                instance=client,
                model_type=actual_model_type,
                instance_id=instance_id_cached
            )

            self.taskinstances.append(task_instance)
            logger.info(f"Loaded TaskInstance {ti_uuid} from {base_url} (model: {actual_model_type})")

        if self._strategy:
            self._strategy.taskinstances = self.taskinstances

        logger.info(f"Loaded {len(self.taskinstances)} TaskInstance(s)")

    def add_task_instance(self, base_url: str, model_name: Optional[str] = None) -> UUID:
        """
        Add a single TaskInstance

        Args:
            base_url: TaskInstance URL
            model_name: Model name that this instance runs (optional, for filtering)

        Returns:
            UUID of the registered instance
        """
        ti_uuid = uuid4()
        client = TaskInstanceClient(base_url)

        # Fetch status once during registration to cache model_type and instance_id
        instance_id_cached = None
        actual_model_type = model_name  # Use provided model_name as fallback

        try:
            status = client.get_status()
            if status.instance_id:
                instance_id_cached = status.instance_id
                self._instance_id_to_uuid[status.instance_id] = ti_uuid
                logger.debug(f"Cached instance_id mapping: {status.instance_id} -> {ti_uuid}")

            # Use actual model_type from status if available
            if status.model_type:
                actual_model_type = status.model_type
                logger.debug(f"Cached model_type: {status.model_type}")
        except Exception as e:
            logger.warning(f"Could not get instance info for caching during registration: {e}")

        # Create TaskInstance with cached information
        task_instance = TaskInstance(
            uuid=ti_uuid,
            instance=client,
            model_type=actual_model_type,
            instance_id=instance_id_cached
        )

        self.taskinstances.append(task_instance)

        if self._strategy:
            self._strategy.taskinstances = self.taskinstances

        # If async scheduling is enabled and using lock-free, create/update scheduler
        if self.use_lockfree and self.async_scheduler_manager is not None and model_name:
            # Get task instances for this model
            model_instances = [ti for ti in self.taskinstances
                              if ti.model_type == model_name or ti.model_type is None]

            # Create or update scheduler for this model type
            if not self.async_scheduler_manager.get_scheduler(model_name):
                self.async_scheduler_manager.create_scheduler(
                    model_type=model_name,
                    strategy=self.strategy,
                    taskinstances=model_instances
                )
                logger.info(f"Created lock-free scheduler for model {model_name}")

        logger.info(f"Added TaskInstance {ti_uuid} at {base_url} for model {model_name}")
        return ti_uuid

    def remove_task_instance(self, instance_uuid: UUID) -> bool:
        """Remove a TaskInstance by UUID"""
        for i, ti in enumerate(self.taskinstances):
            if ti.uuid == instance_uuid:
                removed_ti = self.taskinstances.pop(i)

                # Remove from instance_id cache
                try:
                    status = removed_ti.instance.get_status()
                    if status.instance_id and status.instance_id in self._instance_id_to_uuid:
                        del self._instance_id_to_uuid[status.instance_id]
                        logger.debug(f"Removed instance_id mapping from cache: {status.instance_id}")
                except Exception as e:
                    logger.debug(f"Could not remove instance_id from cache: {e}")

                logger.info(f"Removed TaskInstance {instance_uuid}")
                return True

        logger.warning(f"TaskInstance {instance_uuid} not found")
        return False

    def remove_task_instance_by_address(self, host: str, port: int) -> Optional[UUID]:
        """
        Remove a TaskInstance by host and port

        Args:
            host: TaskInstance host address
            port: TaskInstance port number

        Returns:
            UUID of the removed instance, or None if not found
        """
        target_url = f"http://{host}:{port}"

        for i, ti in enumerate(self.taskinstances):
            # Compare base_url with target URL
            if ti.instance.base_url == target_url:
                removed_ti = self.taskinstances.pop(i)

                # Remove from instance_id cache
                try:
                    status = removed_ti.instance.get_status()
                    if status.instance_id and status.instance_id in self._instance_id_to_uuid:
                        del self._instance_id_to_uuid[status.instance_id]
                        logger.debug(f"Removed instance_id mapping from cache: {status.instance_id}")
                except Exception as e:
                    logger.debug(f"Could not remove instance_id from cache: {e}")

                # Update strategy's taskinstances reference
                if self._strategy:
                    self._strategy.taskinstances = self.taskinstances

                logger.info(f"Removed TaskInstance {removed_ti.uuid} at {target_url}")
                return removed_ti.uuid

        logger.warning(f"TaskInstance at {target_url} not found")
        return None

    def get_uuid_by_instance_id(self, instance_id: str) -> Optional[UUID]:
        """
        Get TaskInstance UUID by instance_id using cache

        Args:
            instance_id: Instance ID (format: "ti-<port>")

        Returns:
            UUID if found, None otherwise
        """
        # First try cache (fast path)
        if instance_id in self._instance_id_to_uuid:
            return self._instance_id_to_uuid[instance_id]

        # Cache miss - do slow lookup and update cache
        for ti in self.taskinstances:
            try:
                status = ti.instance.get_status()
                if status.instance_id == instance_id:
                    # Update cache for future lookups
                    self._instance_id_to_uuid[instance_id] = ti.uuid
                    logger.debug(f"Cache miss - added instance_id mapping: {instance_id} -> {ti.uuid}")
                    return ti.uuid
            except Exception as e:
                logger.debug(f"Could not get status for instance {ti.uuid}: {e}")
                continue

        logger.warning(f"Instance ID {instance_id} not found")
        return None

    async def _dispatch_task_via_websocket(
        self,
        instance_id: str,
        task_id: str,
        model_name: str,
        input_data: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> bool:
        """
        Dispatch a task to TaskInstance via WebSocket

        Args:
            instance_id: Target instance identifier (e.g., "localhost:8100")
            task_id: Unique task identifier
            model_name: Model name for the task
            input_data: Task input data
            metadata: Task metadata

        Returns:
            True if dispatch successful, False if should fallback to HTTP
        """
        if not self.result_submission_manager:
            logger.debug("ResultSubmissionManager not available, using HTTP fallback")
            return False

        # Check if WebSocket connection exists
        if not self.result_submission_manager.has_connection(instance_id):
            logger.debug(f"No WebSocket connection for {instance_id}, using HTTP fallback")
            return False

        # Dispatch via WebSocket
        success = await self.result_submission_manager.dispatch_task(
            instance_id=instance_id,
            task_id=task_id,
            model_name=model_name,
            task_input=input_data,
            metadata=metadata
        )

        if success:
            logger.info(f"Task {task_id} dispatched to {instance_id} via WebSocket")
        else:
            logger.warning(f"WebSocket dispatch failed for task {task_id}, will use HTTP fallback")

        return success

    def _dispatch_task_sync(
        self,
        instance_id: str,
        task_id: str,
        model_name: str,
        input_data: Dict[str, Any],
        metadata: Dict[str, Any],
        instance_client: TaskInstanceClient
    ):
        """
        Dispatch task with WebSocket (preferred) or HTTP fallback.

        Returns:
            enqueue_response from TaskInstance
        """
        # Try WebSocket first if available
        use_websocket = False
        if self.result_submission_manager:
            try:
                # Run async websocket dispatch in event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're already in an async context, create a task
                    # This is a workaround for sync context calling async code
                    logger.debug("Event loop already running, using HTTP fallback")
                else:
                    use_websocket = loop.run_until_complete(
                        self._dispatch_task_via_websocket(
                            instance_id, task_id, model_name, input_data, metadata
                        )
                    )
            except RuntimeError:
                # No event loop available, use HTTP fallback
                logger.debug("No event loop available, using HTTP fallback")
            except Exception as e:
                logger.warning(f"WebSocket dispatch error: {e}, using HTTP fallback")

        # If WebSocket succeeded, create a mock response
        # (actual task is already enqueued via WebSocket)
        if use_websocket:
            # Return a mock response since task is already dispatched
            from .models import EnqueueResponse
            return EnqueueResponse(
                status="success",
                task_id=task_id,
                message="Task dispatched via WebSocket",
                queue_size=0,  # Not available via WebSocket
                expected_completion_time=0.0  # Not available via WebSocket
            )

        # Fallback to HTTP
        logger.debug(f"Dispatching task {task_id} to {instance_id} via HTTP")
        return instance_client.enqueue_task(
            input_data=input_data,
            metadata=metadata,
            task_id=task_id,
            model_name=model_name
        )

    # @pyinstrument.profile()
    def schedule(self, request: SchedulerRequest) -> SchedulerResponse:
        """
        Schedule a task to the optimal TaskInstance

        Args:
            request: Scheduler request containing task information

        Returns:
            SchedulerResponse with routing information
        """
        arrival_time = time.time()

        if not self.taskinstances:
            raise RuntimeError("No TaskInstances configured")

        if not request.request_id:
            request.request_id = str(uuid4())

        # Create selection request
        selection_req = SelectionRequest(
            model_type=request.model_type,
            input_data=request.input_data,
            metadata=request.metadata
        )

        # Use strategy to select optimal instance
        result = self.strategy.select(selection_req)
        selected_instance = result.selected_instance
        queue_info = result.queue_info

        selection_time = time.time()
        # Enqueue task to selected instance
        try:
            # Use pre-assigned task_id if it's a valid UUID, otherwise generate new one
            if request.task_id and is_valid_uuid(request.task_id):
                task_id = request.task_id
                logger.debug(f"Using pre-assigned UUID task_id: {task_id}")
            else:
                task_id = str(uuid4())
                if request.task_id:
                    logger.debug(f"Ignoring non-UUID task_id '{request.task_id}', generated new: {task_id}")

            # Get instance_id for WebSocket dispatch
            instance_id = selected_instance.instance_id
            if not instance_id:
                # Fallback: get instance_id from status call
                try:
                    status = selected_instance.instance.get_status()
                    instance_id = status.get("instance_id")
                except Exception:
                    pass

            # Register task in tracker (must be done before dispatch)
            self.task_tracker.register_task(
                task_id=task_id,
                ti_uuid=selected_instance.uuid,
                model_name=request.model_type,
                submit_time=arrival_time
            )

            # Mark as scheduled
            self.task_tracker.mark_scheduled(task_id)

            # Store arrival time
            self.request_times[task_id] = (arrival_time, request.request_id)

            # Dispatch task first (critical operation)
            dispatch_start_time = time.time()

            try:
                enqueue_response = self._dispatch_task_sync(
                    instance_id=instance_id,
                    task_id=task_id,
                    model_name=request.model_type,
                    input_data=request.input_data,
                    metadata=request.metadata,
                    instance_client=selected_instance.instance
                )
            except Exception as e:
                # If dispatch fails, this is critical - re-raise the exception
                raise e

            dispatch_end_time = time.time()
            enqueue_time = dispatch_end_time  # For backward compatibility

            # Submit queue update to background worker (non-blocking)
            self._submit_queue_update(
                selected_instance=selected_instance,
                request=selection_req,
                task_id=task_id
            )

            logger.info(f"Schedule finished, overhead: Selection: {selection_time - arrival_time:.3f}s Dispatch: {dispatch_end_time - dispatch_start_time:.3f}s (queue update queued)")
            # Save routing information
            self.last_routing_info = {
                "request_id": request.request_id,
                "task_id": task_id,
                "instance_uuid": str(selected_instance.uuid),
                "instance_url": selected_instance.instance.base_url,
                "model_type": queue_info.model_type,
                "expected_ms": queue_info.expected_ms,
                "queue_size_before": queue_info.queue_size,
                "arrival_time": arrival_time
            }

            logger.info(
                f"Task {task_id} scheduled to instance {selected_instance.uuid} "
                f"(model: {queue_info.model_type}, expected: {queue_info.expected_ms}ms)"
            )

            return SchedulerResponse(
                task_id=task_id,
                instance_id=str(selected_instance.uuid),
                instance_url=selected_instance.instance.base_url,
                model_type=queue_info.model_type,
                queue_size=enqueue_response.queue_size
            )

        except Exception as e:
            logger.error(f"Failed to enqueue task to instance {selected_instance.uuid}: {e}")
            raise RuntimeError(f"Failed to schedule task: {e}")

    def get_last_routing_info(self) -> Dict[str, Any]:
        """Get last routing information"""
        if self.last_routing_info is None:
            raise RuntimeError("No routing information available")
        return self.last_routing_info

    def get_instance_statuses(self) -> List[Dict[str, Any]]:
        """Get status of all configured TaskInstances"""
        statuses = []

        for ti in self.taskinstances:
            try:
                status = ti.instance.get_status()
                statuses.append({
                    "uuid": str(ti.uuid),
                    "url": ti.instance.base_url,
                    "instance_id": status.instance_id,
                    "model_type": status.model_type,
                    "replicas": status.replicas_running,
                    "queue_size": status.queue_size,
                    "status": status.status
                })
            except Exception as e:
                logger.warning(f"Failed to get status for instance {ti.uuid}: {e}")
                statuses.append({
                    "uuid": str(ti.uuid),
                    "url": ti.instance.base_url,
                    "status": "error",
                    "error": str(e)
                })

        return statuses

    def get_total_capacity(self) -> Dict[str, int]:
        """Get total capacity by model type"""
        capacity = {}

        for ti in self.taskinstances:
            try:
                status = ti.instance.get_status()
                if status.model_type:
                    capacity[status.model_type] = capacity.get(status.model_type, 0) + status.replicas_running
            except Exception:
                pass

        return capacity

    def handle_task_completion(self, task_id: str, instance_uuid: UUID, execution_time: float) -> Optional[float]:
        """Handle task completion notification"""
        total_time_ms = None

        # Mark task as completed in tracker
        self.task_tracker.mark_completed(task_id=task_id)

        # Calculate total time if we have arrival time
        if task_id in self.request_times:
            arrival_time, request_id = self.request_times[task_id]
            completion_time = time.time()
            total_time_ms = (completion_time - arrival_time) * 1000

            self.timing_statistics.append((task_id, total_time_ms, execution_time))

            if len(self.timing_statistics) > 1000:
                self.timing_statistics = self.timing_statistics[-1000:]

            logger.info(
                f"Task {task_id} completed - Total: {total_time_ms:.2f}ms, "
                f"Execution: {execution_time:.2f}ms"
            )

            del self.request_times[task_id]

        # Submit queue update to background worker (non-blocking)
        self._submit_completion_update(
            instance_uuid=instance_uuid,
            task_id=task_id,
            execution_time=execution_time
        )

        return total_time_ms

    def get_timing_statistics(self) -> Dict[str, Any]:
        """Get timing statistics for completed tasks"""
        if not self.timing_statistics:
            return {
                "total_tasks": 0,
                "avg_total_time_ms": 0.0,
                "avg_execution_time_ms": 0.0,
                "avg_overhead_ms": 0.0,
                "recent_tasks": []
            }

        total_times = [t[1] for t in self.timing_statistics]
        execution_times = [t[2] for t in self.timing_statistics]
        overheads = [t[1] - t[2] for t in self.timing_statistics]

        recent_tasks = [
            {
                "task_id": task_id,
                "total_time_ms": total_time,
                "execution_time_ms": exec_time,
                "overhead_ms": total_time - exec_time
            }
            for task_id, total_time, exec_time in self.timing_statistics[-10:]
        ]

        return {
            "total_tasks": len(self.timing_statistics),
            "avg_total_time_ms": sum(total_times) / len(total_times),
            "avg_execution_time_ms": sum(execution_times) / len(execution_times),
            "avg_overhead_ms": sum(overheads) / len(overheads),
            "min_total_time_ms": min(total_times),
            "max_total_time_ms": max(total_times),
            "recent_tasks": recent_tasks
        }

    def _start_queue_update_worker(self):
        """Start the background thread for processing queue updates"""
        self._queue_update_thread = threading.Thread(
            target=self._queue_update_worker,
            name="QueueUpdateWorker",
            daemon=True
        )
        self._queue_update_thread.start()
        logger.info("Started background queue update worker thread")

    def _queue_update_worker(self):
        """Background worker that processes queue update tasks sequentially"""
        logger.info("Queue update worker started")

        while not self._queue_update_shutdown.is_set():
            try:
                # Get task from queue with timeout to check shutdown flag periodically
                task = self._queue_update_queue.get(timeout=1.0)

                if task is None:  # Poison pill for shutdown
                    break

                # Process the queue update based on task type
                try:
                    if task.task_type == 'schedule':
                        # Handle schedule queue update
                        self.strategy.update_queue(
                            selected_instance=task.selected_instance,
                            request=task.request,
                            task_id=task.task_id
                        )
                    elif task.task_type == 'completion':
                        # Handle completion queue update
                        self.strategy.update_queue_on_completion(
                            instance_uuid=task.instance_uuid,
                            task_id=task.task_id,
                            execution_time=task.execution_time
                        )
                    else:
                        logger.error(f"Unknown task type: {task.task_type}")
                        continue

                    elapsed = time.time() - task.timestamp
                    logger.debug(
                        f"Queue update ({task.task_type}) completed for task {task.task_id} "
                        f"(queued for {elapsed:.3f}s)"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to update queue state for task {task.task_id} ({task.task_type}): {e}"
                    )

            except Empty:
                # Timeout occurred, loop back to check shutdown flag
                continue
            except Exception as e:
                logger.error(f"Unexpected error in queue update worker: {e}")

        logger.info("Queue update worker stopped")

    def _submit_queue_update(self, selected_instance: TaskInstance,
                            request: SelectionRequest, task_id: str):
        """Submit a schedule queue update task to the background worker"""
        task = QueueUpdateTask(
            task_type='schedule',
            task_id=task_id,
            timestamp=time.time(),
            selected_instance=selected_instance,
            request=request
        )

        self._queue_update_queue.put(task)
        logger.debug(f"Queued schedule update for {task_id}, queue size: {self._queue_update_queue.qsize()}")

    def _submit_completion_update(self, instance_uuid: UUID, task_id: str,
                                 execution_time: float):
        """Submit a completion queue update task to the background worker"""
        task = QueueUpdateTask(
            task_type='completion',
            task_id=task_id,
            timestamp=time.time(),
            instance_uuid=instance_uuid,
            execution_time=execution_time
        )

        self._queue_update_queue.put(task)
        logger.debug(f"Queued completion update for {task_id}, queue size: {self._queue_update_queue.qsize()}")

    def shutdown(self):
        """Shutdown the scheduler and background workers cleanly"""
        logger.info("Shutting down scheduler...")

        # Signal shutdown to worker thread
        self._queue_update_shutdown.set()

        # Send poison pill to wake up worker if it's waiting
        self._queue_update_queue.put(None)

        # Wait for worker thread to finish
        if self._queue_update_thread and self._queue_update_thread.is_alive():
            self._queue_update_thread.join(timeout=5.0)
            if self._queue_update_thread.is_alive():
                logger.warning("Queue update worker thread did not stop cleanly")

        logger.info("Scheduler shutdown complete")
