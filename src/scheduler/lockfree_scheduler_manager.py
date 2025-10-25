"""
Lock-Free Model Scheduler Manager

Manages multiple lock-free model schedulers for different model types.
Provides centralized control and monitoring with minimal locking.
"""

from typing import Dict, List, Optional, Any
from loguru import logger
import threading
from concurrent.futures import ThreadPoolExecutor, Future
import time

from .lockfree_model_scheduler import LockFreeModelScheduler
from .lockfree_task_tracker import LockFreeTaskTracker
from .strategies import BaseStrategy, TaskInstance
from .models import SchedulerRequest


class LockFreeSchedulerManager:
    """
    Manages multiple lock-free model schedulers

    Features:
    - Thread-safe scheduler management without heavy locking
    - Async task submission
    - Centralized monitoring
    - Graceful shutdown
    """

    def __init__(
        self,
        task_tracker: Optional[LockFreeTaskTracker] = None,
        max_queue_size: int = 50000,
        retry_attempts: int = 3,
        retry_delay_ms: int = 50,
        num_workers: int = 8,
        batch_size: int = 20,
        enable_profiling: bool = False
    ):
        """
        Initialize LockFreeSchedulerManager

        Args:
            task_tracker: Shared lock-free task tracker (creates new if None)
            max_queue_size: Max queue size per model scheduler
            retry_attempts: Number of retry attempts for failed tasks
            retry_delay_ms: Delay between retries
            num_workers: Number of workers per model scheduler
            batch_size: Batch size for processing
            enable_profiling: Enable performance profiling
        """
        # Use provided tracker or create new one
        self.task_tracker = task_tracker or LockFreeTaskTracker(
            max_history=100000,
            cleanup_interval=60
        )

        # Model schedulers (use RWLock pattern for safe access)
        self._schedulers: Dict[str, LockFreeModelScheduler] = {}
        self._schedulers_lock = threading.RLock()

        # Configuration
        self.max_queue_size = max_queue_size
        self.retry_attempts = retry_attempts
        self.retry_delay_ms = retry_delay_ms
        self.num_workers = num_workers
        self.batch_size = batch_size
        self.enable_profiling = enable_profiling

        # Manager state
        self._running = False
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="SchedulerManager"
        )

        # Statistics aggregation
        self._stats_lock = threading.Lock()
        self._last_stats_update = 0
        self._cached_stats: Optional[Dict[str, Any]] = None
        self._stats_cache_ttl = 1.0  # Cache stats for 1 second

    def create_scheduler(
        self,
        model_type: str,
        strategy: BaseStrategy,
        taskinstances: List[TaskInstance]
    ) -> LockFreeModelScheduler:
        """
        Create a new lock-free model scheduler

        Args:
            model_type: Model type for this scheduler
            strategy: Scheduling strategy
            taskinstances: Available task instances

        Returns:
            Created scheduler instance
        """
        with self._schedulers_lock:
            if model_type in self._schedulers:
                logger.warning(f"Scheduler for {model_type} already exists")
                return self._schedulers[model_type]

            scheduler = LockFreeModelScheduler(
                model_type=model_type,
                strategy=strategy,
                task_tracker=self.task_tracker,
                taskinstances=taskinstances,
                max_queue_size=self.max_queue_size,
                retry_attempts=self.retry_attempts,
                retry_delay_ms=self.retry_delay_ms,
                num_workers=self.num_workers,
                batch_size=self.batch_size,
                enable_profiling=self.enable_profiling
            )

            self._schedulers[model_type] = scheduler

            # Auto-start if manager is running
            if self._running:
                scheduler.start()

            logger.info(f"Created lock-free scheduler for model type: {model_type}")
            return scheduler

    def start(self):
        """Start all model schedulers"""
        with self._schedulers_lock:
            if self._running:
                logger.warning("LockFreeSchedulerManager already running")
                return

            self._running = True

            # Start all schedulers
            futures = []
            for model_type, scheduler in self._schedulers.items():
                future = self._executor.submit(scheduler.start)
                futures.append(future)

            # Wait for all to start
            for future in futures:
                try:
                    future.result(timeout=5.0)
                except Exception as e:
                    logger.error(f"Error starting scheduler: {e}")

            logger.info(
                f"Started LockFreeSchedulerManager with {len(self._schedulers)} model schedulers"
            )

    def stop(self, timeout: float = 10.0):
        """
        Stop all model schedulers

        Args:
            timeout: Maximum time to wait for shutdown
        """
        with self._schedulers_lock:
            if not self._running:
                return

            logger.info("Stopping LockFreeSchedulerManager...")
            self._running = False

            # Stop all schedulers in parallel
            futures = []
            for model_type, scheduler in self._schedulers.items():
                future = self._executor.submit(
                    scheduler.stop,
                    timeout / len(self._schedulers)
                )
                futures.append((model_type, future))

            # Wait for all to stop
            for model_type, future in futures:
                try:
                    future.result(timeout=timeout / len(self._schedulers))
                    logger.info(f"Stopped scheduler for {model_type}")
                except Exception as e:
                    logger.error(f"Error stopping scheduler for {model_type}: {e}")

        # Shutdown task tracker
        self.task_tracker.shutdown()

        # Shutdown executor
        self._executor.shutdown(wait=True)

        logger.info("LockFreeSchedulerManager stopped")

    def submit_task(self, model_type: str, request: SchedulerRequest) -> Optional[str]:
        """
        Submit a task to the appropriate model scheduler

        Args:
            model_type: Target model type
            request: Scheduler request

        Returns:
            task_id if successful, None otherwise
        """
        # Fast path - try to get scheduler without full lock
        scheduler = self._get_scheduler_fast(model_type)

        if not scheduler:
            logger.error(f"No scheduler found for model type: {model_type}")
            return None

        try:
            task_id = scheduler.submit_task(request)
            return task_id
        except Exception as e:
            logger.error(f"Failed to submit task to {model_type}: {e}")
            return None

    def submit_task_async(
        self,
        model_type: str,
        request: SchedulerRequest
    ) -> Future[Optional[str]]:
        """
        Submit a task asynchronously

        Args:
            model_type: Target model type
            request: Scheduler request

        Returns:
            Future containing task_id or None
        """
        return self._executor.submit(self.submit_task, model_type, request)

    def _get_scheduler_fast(self, model_type: str) -> Optional[LockFreeModelScheduler]:
        """
        Get scheduler with minimal locking

        Uses double-checked locking pattern for performance
        """
        # First check without lock (fast path)
        if model_type in self._schedulers:
            return self._schedulers[model_type]

        # If not found, acquire lock and check again
        with self._schedulers_lock:
            return self._schedulers.get(model_type)

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get aggregated statistics from all schedulers

        Uses caching to reduce lock contention
        """
        now = time.time()

        # Check cache
        with self._stats_lock:
            if (self._cached_stats and
                now - self._last_stats_update < self._stats_cache_ttl):
                return self._cached_stats

        # Gather stats from all schedulers
        stats = {
            "running": self._running,
            "num_schedulers": len(self._schedulers),
            "task_tracker": self.task_tracker.get_statistics(),
            "schedulers": {}
        }

        # Collect stats without holding main lock
        scheduler_items = []
        with self._schedulers_lock:
            scheduler_items = list(self._schedulers.items())

        for model_type, scheduler in scheduler_items:
            try:
                stats["schedulers"][model_type] = scheduler.get_statistics()
            except Exception as e:
                logger.error(f"Error getting stats for {model_type}: {e}")
                stats["schedulers"][model_type] = {"error": str(e)}

        # Compute totals
        totals = {
            "total_pending": 0,
            "total_scheduled": 0,
            "total_failed": 0,
            "total_workers": 0
        }

        for scheduler_stats in stats["schedulers"].values():
            if "error" not in scheduler_stats:
                totals["total_pending"] += scheduler_stats.get("pending_count", 0)
                totals["total_scheduled"] += scheduler_stats.get("total_scheduled", 0)
                totals["total_failed"] += scheduler_stats.get("total_failed", 0)
                totals["total_workers"] += scheduler_stats.get("num_workers", 0)

        stats["totals"] = totals

        # Update cache
        with self._stats_lock:
            self._cached_stats = stats
            self._last_stats_update = now

        return stats

    def get_scheduler(self, model_type: str) -> Optional[LockFreeModelScheduler]:
        """
        Get a specific model scheduler

        Args:
            model_type: Model type

        Returns:
            Scheduler instance or None
        """
        return self._get_scheduler_fast(model_type)

    def list_model_types(self) -> List[str]:
        """List all registered model types"""
        with self._schedulers_lock:
            return list(self._schedulers.keys())

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on all components

        Returns:
            Health status dictionary
        """
        health = {
            "status": "healthy",
            "manager_running": self._running,
            "schedulers": {}
        }

        # Check each scheduler
        with self._schedulers_lock:
            for model_type, scheduler in self._schedulers.items():
                scheduler_health = {
                    "running": scheduler._running,
                    "pending_count": scheduler.get_pending_count(),
                    "workers": scheduler.num_workers
                }

                # Mark unhealthy if not running or queue is too full
                if not scheduler._running:
                    scheduler_health["status"] = "stopped"
                    health["status"] = "degraded"
                elif scheduler.get_pending_count() > scheduler.max_queue_size * 0.9:
                    scheduler_health["status"] = "overloaded"
                    health["status"] = "degraded"
                else:
                    scheduler_health["status"] = "healthy"

                health["schedulers"][model_type] = scheduler_health

        return health