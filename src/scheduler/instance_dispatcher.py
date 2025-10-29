"""
Instance Dispatcher - Per-TaskInstance background dispatch management

This module implements a high-performance dispatch system where each TaskInstance
has a dedicated background thread with its own queue for processing tasks.

Key Features:
- Per-instance dispatch threads for parallel processing
- Lock-free queues for high throughput
- Automatic retry with exponential backoff
- Health monitoring and graceful degradation
- Support for both WebSocket and HTTP dispatch
"""

from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass
from uuid import UUID
from loguru import logger
import threading
import queue
import time
import asyncio
import websockets
import json
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from urllib.parse import urlparse

from .client import TaskInstanceClient
from .models import EnqueueResponse


class DispatchStatus(Enum):
    """Status of a dispatch operation"""
    PENDING = "pending"
    DISPATCHING = "dispatching"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"


@dataclass
class DispatchTask:
    """Task to be dispatched to a TaskInstance"""
    task_id: str
    model_name: str
    input_data: Dict[str, Any]
    metadata: Dict[str, Any]
    instance_id: str
    enqueue_time: float
    retry_count: int = 0
    max_retries: int = 3
    callback: Optional[Callable[[str, bool, Optional[EnqueueResponse]], None]] = None


class InstanceDispatcher:
    """
    Manages dispatch queue and background thread for a single TaskInstance

    Features:
    - Dedicated background thread for continuous task processing
    - Thread-safe queue for task submission
    - Automatic retry with exponential backoff
    - Health monitoring and statistics
    """

    def __init__(
        self,
        instance_uuid: UUID,
        instance_client: TaskInstanceClient,
        instance_id: Optional[str] = None,
        max_queue_size: int = 10000,
        batch_size: int = 1,
        retry_delay_ms: int = 100,
        health_check_interval: float = 30.0,
        result_submission_manager: Optional[Any] = None,
        enable_websocket: bool = True,
        websocket_reconnect_interval: float = 5.0
    ):
        """
        Initialize InstanceDispatcher

        Args:
            instance_uuid: UUID of the TaskInstance
            instance_client: Client for communicating with the TaskInstance
            instance_id: Optional instance ID for WebSocket dispatch
            max_queue_size: Maximum size of the dispatch queue
            batch_size: Number of tasks to dispatch in a batch
            retry_delay_ms: Initial retry delay in milliseconds
            health_check_interval: Interval for health checks in seconds
            result_submission_manager: Optional manager for WebSocket dispatch (deprecated)
            enable_websocket: Whether to enable WebSocket connection
            websocket_reconnect_interval: Interval for WebSocket reconnection attempts
        """
        self.instance_uuid = instance_uuid
        self.instance_client = instance_client
        self.instance_id = instance_id or str(instance_uuid)
        self.max_queue_size = max_queue_size
        self.batch_size = batch_size
        self.retry_delay_ms = retry_delay_ms
        self.health_check_interval = health_check_interval
        self.result_submission_manager = result_submission_manager  # Deprecated
        self.enable_websocket = enable_websocket
        self.websocket_reconnect_interval = websocket_reconnect_interval

        # Dispatch queue
        self.dispatch_queue = queue.Queue(maxsize=max_queue_size)

        # Worker thread
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        # WebSocket connection
        self._websocket = None
        self._websocket_lock = threading.Lock()
        self._websocket_connected = False
        self._websocket_url = self._build_websocket_url()

        # Statistics
        self._stats_lock = threading.Lock()
        self.stats = {
            'tasks_dispatched': 0,
            'tasks_failed': 0,
            'tasks_retried': 0,
            'total_dispatch_time': 0.0,
            'last_dispatch_time': 0.0,
            'queue_size': 0,
            'is_healthy': True,
            'last_health_check': 0.0
        }

        # Event loop for async operations
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self):
        """Start the dispatcher background thread"""
        if self._running:
            logger.warning(f"Dispatcher for {self.instance_uuid} already running")
            return

        self._running = True
        self._stop_event.clear()

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name=f"Dispatcher-{self.instance_uuid}",
            daemon=True
        )
        self._worker_thread.start()

        logger.info(f"Started dispatcher for TaskInstance {self.instance_uuid}")

    def stop(self, timeout: float = 5.0):
        """
        Stop the dispatcher background thread

        Args:
            timeout: Maximum time to wait for thread to stop
        """
        if not self._running:
            return

        logger.info(f"Stopping dispatcher for TaskInstance {self.instance_uuid}")

        self._running = False
        self._stop_event.set()

        if self._worker_thread:
            self._worker_thread.join(timeout)
            if self._worker_thread.is_alive():
                logger.warning(f"Dispatcher thread for {self.instance_uuid} did not stop cleanly")

        # Clean up WebSocket connection
        if self._loop and not self._loop.is_closed():
            if self._websocket_connected:
                self._loop.run_until_complete(self._disconnect_websocket())
            # Clean up event loop
            self._loop.close()

        logger.info(f"Stopped dispatcher for TaskInstance {self.instance_uuid}")

    def submit_task(
        self,
        task_id: str,
        model_name: str,
        input_data: Dict[str, Any],
        metadata: Dict[str, Any],
        callback: Optional[Callable[[str, bool, Optional[EnqueueResponse]], None]] = None,
        timeout: float = 0.1
    ) -> bool:
        """
        Submit a task to the dispatch queue (non-blocking)

        Args:
            task_id: Unique task identifier
            model_name: Name of the model to run
            input_data: Task input data
            metadata: Task metadata
            callback: Optional callback for dispatch result
            timeout: Maximum time to wait for queue space

        Returns:
            True if task was queued, False if queue is full
        """
        if not self._running:
            logger.error(f"Cannot submit task - dispatcher for {self.instance_uuid} not running")
            return False

        dispatch_task = DispatchTask(
            task_id=task_id,
            model_name=model_name,
            input_data=input_data,
            metadata=metadata,
            instance_id=self.instance_id or str(self.instance_uuid),
            enqueue_time=time.time(),
            callback=callback
        )

        try:
            self.dispatch_queue.put(dispatch_task, block=True, timeout=timeout)

            with self._stats_lock:
                self.stats['queue_size'] = self.dispatch_queue.qsize()

            return True

        except queue.Full:
            logger.warning(f"Dispatch queue full for instance {self.instance_uuid}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics"""
        with self._stats_lock:
            stats = self.stats.copy()
            stats['websocket_connected'] = self._websocket_connected
            return stats

    def _build_websocket_url(self) -> str:
        """Build WebSocket URL from instance client base URL"""
        if not self.instance_client or not self.instance_client.base_url:
            return None

        # Parse the HTTP URL
        parsed = urlparse(self.instance_client.base_url)

        # Convert HTTP to WS protocol
        if parsed.scheme == 'https':
            ws_scheme = 'wss'
        else:
            ws_scheme = 'ws'

        # Build WebSocket URL for task submission endpoint
        ws_url = f"{ws_scheme}://{parsed.netloc}/ws/submit"
        logger.debug(f"Built WebSocket URL for {self.instance_uuid}: {ws_url}")
        return ws_url

    async def _connect_websocket(self) -> bool:
        """Establish WebSocket connection to the TaskInstance"""
        if not self.enable_websocket or not self._websocket_url:
            return False

        try:
            logger.info(f"Connecting WebSocket to {self._websocket_url} for instance {self.instance_uuid}")

            # Create WebSocket connection with keepalive configuration
            # ping_interval: Send ping every 30 seconds
            # ping_timeout: Wait 10 seconds for pong response
            # The server (FastAPI/Starlette) should automatically respond to ping frames
            self._websocket = await websockets.connect(
                self._websocket_url,
                ping_interval=30,  # Send ping frame every 30 seconds
                ping_timeout=10,   # Timeout if no pong received within 10 seconds
                close_timeout=10   # Timeout for close handshake
            )

            # Send registration message
            await self._websocket.send(json.dumps({
                "type": "register",
                "instance_id": self.instance_id,
                "instance_uuid": str(self.instance_uuid)
            }))

            # Wait for acknowledgment
            response = await asyncio.wait_for(self._websocket.recv(), timeout=5.0)
            data = json.loads(response)

            if data.get("type") == "ack" and data.get("status") == "registered":
                self._websocket_connected = True
                logger.info(f"WebSocket connected for instance {self.instance_uuid}")

                with self._stats_lock:
                    self.stats['websocket_connections'] = self.stats.get('websocket_connections', 0) + 1

                return True
            else:
                logger.warning(f"Unexpected registration response: {data}")
                await self._websocket.close()
                self._websocket = None
                return False

        except websockets.exceptions.InvalidURI as e:
            logger.error(f"Invalid WebSocket URI for {self.instance_uuid}: {e}")
            self._websocket = None
            self._websocket_connected = False
            return False
        except websockets.exceptions.WebSocketException as e:
            logger.warning(f"WebSocket connection error for {self.instance_uuid}: {type(e).__name__}: {e}")
            self._websocket = None
            self._websocket_connected = False
            return False
        except Exception as e:
            logger.warning(f"Failed to connect WebSocket for {self.instance_uuid}: {type(e).__name__}: {e}")
            self._websocket = None
            self._websocket_connected = False
            return False

    async def _disconnect_websocket(self):
        """Disconnect WebSocket connection"""
        if self._websocket:
            try:
                await self._websocket.close()
                logger.info(f"WebSocket disconnected for instance {self.instance_uuid}")
            except Exception as e:
                logger.warning(f"Error closing WebSocket for {self.instance_uuid}: {e}")
            finally:
                self._websocket = None
                self._websocket_connected = False

    async def _dispatch_via_websocket(self, task: DispatchTask) -> bool:
        """
        Dispatch task via WebSocket connection

        Args:
            task: Task to dispatch

        Returns:
            True if successful, False otherwise
        """
        if not self._websocket or not self._websocket_connected:
            return False

        try:
            # Send task message
            await self._websocket.send(json.dumps({
                "type": "task",
                "task_id": task.task_id,
                "model_name": task.model_name,
                "task_input": task.input_data,
                "metadata": task.metadata
            }))

            # Wait for acknowledgment with timeout
            response = await asyncio.wait_for(self._websocket.recv(), timeout=5.0)
            data = json.loads(response)

            if data.get("type") == "task_ack" and data.get("task_id") == task.task_id:
                logger.debug(f"Task {task.task_id} dispatched via WebSocket to {self.instance_uuid}")

                with self._stats_lock:
                    self.stats['websocket_dispatches'] = self.stats.get('websocket_dispatches', 0) + 1

                return True
            else:
                logger.warning(f"Unexpected task response: {data}")
                return False

        except asyncio.TimeoutError:
            logger.warning(f"WebSocket dispatch timeout for task {task.task_id}")
            return False
        except websockets.exceptions.ConnectionClosed as e:
            # Handle connection closed errors specifically
            logger.warning(f"WebSocket connection closed for task {task.task_id}: code={e.code}, reason={e.reason}")
            # Mark connection as disconnected for reconnection
            self._websocket_connected = False
            self._websocket = None
            return False
        except Exception as e:
            logger.warning(f"WebSocket dispatch error for {task.task_id}: {type(e).__name__}: {e}")
            # Connection might be broken, mark it as disconnected
            self._websocket_connected = False
            self._websocket = None
            return False

    def _worker_loop(self):
        """Main worker loop for processing dispatch tasks"""
        logger.info(f"Dispatcher worker started for instance {self.instance_uuid}")

        # Create event loop for async operations
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Initialize WebSocket connection if enabled
        if self.enable_websocket:
            self._loop.run_until_complete(self._connect_websocket())

        last_health_check = 0.0
        last_reconnect_attempt = 0.0

        while not self._stop_event.is_set():
            # Periodic health check
            now = time.time()
            if now - last_health_check > self.health_check_interval:
                self._check_health()
                last_health_check = now

            # WebSocket reconnection if needed
            if self.enable_websocket and not self._websocket_connected:
                if now - last_reconnect_attempt > self.websocket_reconnect_interval:
                    logger.debug(f"Attempting to reconnect WebSocket for {self.instance_uuid}")
                    self._loop.run_until_complete(self._connect_websocket())
                    last_reconnect_attempt = now

            # Get task from queue (with timeout to allow checking stop event)
            try:
                task = self.dispatch_queue.get(block=True, timeout=0.1)
            except queue.Empty:
                continue

            # Update queue size stat
            with self._stats_lock:
                self.stats['queue_size'] = self.dispatch_queue.qsize()

            # Dispatch the task
            dispatch_start = time.time()
            success, response = self._dispatch_task(task)
            dispatch_time = time.time() - dispatch_start

            # Update statistics
            with self._stats_lock:
                if success:
                    self.stats['tasks_dispatched'] += 1
                else:
                    self.stats['tasks_failed'] += 1

                self.stats['total_dispatch_time'] += dispatch_time
                self.stats['last_dispatch_time'] = dispatch_time

            # Call callback if provided
            if task.callback:
                try:
                    task.callback(task.task_id, success, response)
                except Exception as e:
                    logger.error(f"Error in dispatch callback: {e}")

        # Cleanup WebSocket before exiting
        if self._websocket_connected:
            self._loop.run_until_complete(self._disconnect_websocket())

        logger.info(f"Dispatcher worker stopped for instance {self.instance_uuid}")

    def _dispatch_task(self, task: DispatchTask) -> tuple[bool, Optional[EnqueueResponse]]:
        """
        Dispatch a single task with retry logic

        Args:
            task: Task to dispatch

        Returns:
            Tuple of (success, response)
        """
        while task.retry_count <= task.max_retries:
            try:
                # Try WebSocket dispatch first if connected
                if self._websocket_connected:
                    ws_success = self._loop.run_until_complete(
                        self._dispatch_via_websocket(task)
                    )
                    if ws_success:
                        # Create mock response for WebSocket dispatch
                        response = EnqueueResponse(
                            task_id=task.task_id,
                            queue_size=0,  # Not available via WebSocket
                            enqueue_time=time.time()
                        )
                        return True, response
                    else:
                        logger.debug(f"WebSocket dispatch failed for {task.task_id}, falling back to HTTP")

                # Fall back to HTTP dispatch
                response = self.instance_client.enqueue_task(
                    input_data=task.input_data,
                    metadata=task.metadata,
                    task_id=task.task_id,
                    model_name=task.model_name
                )

                logger.debug(f"Task {task.task_id} dispatched to {self.instance_uuid} via HTTP")
                return True, response

            except Exception as e:
                task.retry_count += 1

                if task.retry_count <= task.max_retries:
                    # Calculate retry delay with exponential backoff
                    retry_delay = (self.retry_delay_ms / 1000.0) * (2 ** (task.retry_count - 1))

                    logger.warning(
                        f"Failed to dispatch task {task.task_id} to {self.instance_uuid}: {e}. "
                        f"Retrying in {retry_delay:.2f}s (attempt {task.retry_count}/{task.max_retries})"
                    )

                    with self._stats_lock:
                        self.stats['tasks_retried'] += 1

                    time.sleep(retry_delay)
                else:
                    logger.error(
                        f"Failed to dispatch task {task.task_id} to {self.instance_uuid} "
                        f"after {task.max_retries} retries: {e}"
                    )
                    return False, None

        return False, None

    def _check_health(self):
        """Check health of the TaskInstance"""
        try:
            status = self.instance_client.get_status()

            with self._stats_lock:
                self.stats['is_healthy'] = status.status == "healthy"
                self.stats['last_health_check'] = time.time()

        except Exception as e:
            logger.warning(f"Health check failed for {self.instance_uuid}: {e}")

            with self._stats_lock:
                self.stats['is_healthy'] = False
                self.stats['last_health_check'] = time.time()


class DispatchQueueManager:
    """
    Manages dispatch queues for all TaskInstances

    Features:
    - Creates and manages InstanceDispatcher for each TaskInstance
    - Provides centralized monitoring and statistics
    - Handles graceful shutdown of all dispatchers
    """

    def __init__(
        self,
        max_queue_size: int = 10000,
        batch_size: int = 1,
        retry_delay_ms: int = 100,
        health_check_interval: float = 30.0,
        enable_websocket: bool = True,
        websocket_reconnect_interval: float = 5.0
    ):
        """
        Initialize DispatchQueueManager

        Args:
            max_queue_size: Maximum queue size per instance
            batch_size: Batch size for dispatch
            retry_delay_ms: Initial retry delay
            health_check_interval: Health check interval
            enable_websocket: Whether to enable WebSocket connections
            websocket_reconnect_interval: WebSocket reconnection interval
        """
        self.max_queue_size = max_queue_size
        self.batch_size = batch_size
        self.retry_delay_ms = retry_delay_ms
        self.health_check_interval = health_check_interval
        self.enable_websocket = enable_websocket
        self.websocket_reconnect_interval = websocket_reconnect_interval

        # Dispatchers mapped by instance UUID
        self.dispatchers: Dict[UUID, InstanceDispatcher] = {}
        self._dispatchers_lock = threading.RLock()

        # Reference to result submission manager (injected later)
        self.result_submission_manager = None

        # Manager state
        self._running = False

        logger.info("DispatchQueueManager initialized")

    def set_result_submission_manager(self, manager):
        """Set the result submission manager for WebSocket dispatch"""
        self.result_submission_manager = manager

        # Update existing dispatchers
        with self._dispatchers_lock:
            for dispatcher in self.dispatchers.values():
                dispatcher.result_submission_manager = manager

    def create_dispatcher(
        self,
        instance_uuid: UUID,
        instance_client: TaskInstanceClient,
        instance_id: Optional[str] = None
    ) -> InstanceDispatcher:
        """
        Create and start a dispatcher for a TaskInstance

        Args:
            instance_uuid: UUID of the TaskInstance
            instance_client: Client for the TaskInstance
            instance_id: Optional instance ID

        Returns:
            Created InstanceDispatcher
        """
        with self._dispatchers_lock:
            if instance_uuid in self.dispatchers:
                logger.warning(f"Dispatcher already exists for {instance_uuid}")
                return self.dispatchers[instance_uuid]

            dispatcher = InstanceDispatcher(
                instance_uuid=instance_uuid,
                instance_client=instance_client,
                instance_id=instance_id,
                max_queue_size=self.max_queue_size,
                batch_size=self.batch_size,
                retry_delay_ms=self.retry_delay_ms,
                health_check_interval=self.health_check_interval,
                result_submission_manager=self.result_submission_manager,
                enable_websocket=self.enable_websocket,
                websocket_reconnect_interval=self.websocket_reconnect_interval
            )

            self.dispatchers[instance_uuid] = dispatcher

            # Auto-start if manager is running
            if self._running:
                dispatcher.start()

            logger.info(f"Created dispatcher for TaskInstance {instance_uuid}")
            return dispatcher

    def remove_dispatcher(self, instance_uuid: UUID):
        """
        Remove and stop a dispatcher

        Args:
            instance_uuid: UUID of the TaskInstance
        """
        with self._dispatchers_lock:
            dispatcher = self.dispatchers.pop(instance_uuid, None)

            if dispatcher:
                dispatcher.stop()
                logger.info(f"Removed dispatcher for TaskInstance {instance_uuid}")
            else:
                logger.warning(f"No dispatcher found for {instance_uuid}")

    def submit_task(
        self,
        instance_uuid: UUID,
        task_id: str,
        model_name: str,
        input_data: Dict[str, Any],
        metadata: Dict[str, Any],
        callback: Optional[Callable[[str, bool, Optional[EnqueueResponse]], None]] = None
    ) -> bool:
        """
        Submit a task to the appropriate dispatcher queue

        Args:
            instance_uuid: UUID of the target TaskInstance
            task_id: Task identifier
            model_name: Model name
            input_data: Task input
            metadata: Task metadata
            callback: Optional completion callback

        Returns:
            True if task was queued, False otherwise
        """
        with self._dispatchers_lock:
            dispatcher = self.dispatchers.get(instance_uuid)

            if not dispatcher:
                logger.error(f"No dispatcher found for instance {instance_uuid}")
                return False

            return dispatcher.submit_task(
                task_id=task_id,
                model_name=model_name,
                input_data=input_data,
                metadata=metadata,
                callback=callback
            )

    def start_all(self):
        """Start all dispatchers"""
        with self._dispatchers_lock:
            if self._running:
                logger.warning("DispatchQueueManager already running")
                return

            self._running = True

            for dispatcher in self.dispatchers.values():
                dispatcher.start()

            logger.info(f"Started {len(self.dispatchers)} dispatchers")

    def stop_all(self, timeout: float = 5.0):
        """
        Stop all dispatchers

        Args:
            timeout: Maximum time to wait for each dispatcher
        """
        with self._dispatchers_lock:
            if not self._running:
                return

            self._running = False

            # Use thread pool for parallel shutdown
            with ThreadPoolExecutor(max_workers=min(len(self.dispatchers), 10)) as executor:
                futures = []
                for dispatcher in self.dispatchers.values():
                    future = executor.submit(dispatcher.stop, timeout)
                    futures.append(future)

                # Wait for all to complete
                for future in futures:
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error stopping dispatcher: {e}")

            logger.info("All dispatchers stopped")

    def get_stats(self) -> Dict[UUID, Dict[str, Any]]:
        """Get statistics from all dispatchers"""
        with self._dispatchers_lock:
            stats = {}
            for uuid, dispatcher in self.dispatchers.items():
                stats[uuid] = dispatcher.get_stats()
            return stats

    def get_total_stats(self) -> Dict[str, Any]:
        """Get aggregated statistics"""
        all_stats = self.get_stats()

        total_stats = {
            'num_dispatchers': len(all_stats),
            'total_tasks_dispatched': sum(s['tasks_dispatched'] for s in all_stats.values()),
            'total_tasks_failed': sum(s['tasks_failed'] for s in all_stats.values()),
            'total_tasks_retried': sum(s['tasks_retried'] for s in all_stats.values()),
            'total_queue_size': sum(s['queue_size'] for s in all_stats.values()),
            'healthy_instances': sum(1 for s in all_stats.values() if s['is_healthy']),
            'avg_dispatch_time': 0.0
        }

        # Calculate average dispatch time
        total_time = sum(s['total_dispatch_time'] for s in all_stats.values())
        total_dispatched = total_stats['total_tasks_dispatched']

        if total_dispatched > 0:
            total_stats['avg_dispatch_time'] = total_time / total_dispatched

        return total_stats