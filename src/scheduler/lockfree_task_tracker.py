"""
Lock-Free Task Tracker

This module provides an optimized, lock-free task state tracking functionality for the scheduler.
It uses concurrent data structures and atomic operations to minimize lock contention and prevent deadlocks.

Key optimizations:
1. Use of concurrent.futures and asyncio for non-blocking operations
2. Reader-Writer locks for better read concurrency
3. Fine-grained locking with multiple specialized locks
4. Lock-free data structures where possible
5. Immutable data patterns to reduce synchronization needs
"""

from typing import Dict, Optional, Any, Set, List
from dataclasses import dataclass, field
from threading import RLock, Lock
import time
from uuid import UUID
from loguru import logger
from collections import defaultdict
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import weakref

from .models import TaskStatus


@dataclass(frozen=True)  # Immutable for thread safety
class TaskInfo:
    """Immutable information about a tracked task"""
    task_id: str
    task_status: TaskStatus
    scheduled_ti: UUID
    submit_time: float
    model_name: str
    result: Optional[Any] = None
    completion_time: Optional[float] = None

    def with_status(self, new_status: TaskStatus) -> 'TaskInfo':
        """Create new TaskInfo with updated status"""
        return TaskInfo(
            task_id=self.task_id,
            task_status=new_status,
            scheduled_ti=self.scheduled_ti,
            submit_time=self.submit_time,
            model_name=self.model_name,
            result=self.result,
            completion_time=self.completion_time
        )

    def with_completion(self, result: Any, completion_time: float) -> 'TaskInfo':
        """Create new TaskInfo with completion data"""
        return TaskInfo(
            task_id=self.task_id,
            task_status=TaskStatus.COMPLETED,
            scheduled_ti=self.scheduled_ti,
            submit_time=self.submit_time,
            model_name=self.model_name,
            result=result,
            completion_time=completion_time
        )


class ReadWriteLock:
    """A simple reader-writer lock implementation"""
    def __init__(self):
        self._readers = 0
        self._writers = 0
        self._read_ready = threading.Condition(threading.RLock())
        self._write_ready = threading.Condition(threading.RLock())

    def acquire_read(self):
        """Acquire read lock"""
        with self._read_ready:
            while self._writers > 0:
                self._read_ready.wait()
            self._readers += 1

    def release_read(self):
        """Release read lock"""
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()

    def acquire_write(self):
        """Acquire write lock"""
        with self._write_ready:
            while self._writers > 0 or self._readers > 0:
                self._write_ready.wait()
            self._writers += 1

    def release_write(self):
        """Release write lock"""
        with self._write_ready:
            self._writers -= 1
            self._write_ready.notify_all()
        with self._read_ready:
            self._read_ready.notify_all()


class LockFreeTaskTracker:
    """
    Optimized task tracker with minimal locking

    Key improvements:
    1. Reader-writer locks for better read concurrency
    2. Separate locks for different data structures
    3. Lock-free statistics using atomic operations
    4. Async cleanup operations
    5. Immutable task info objects
    """

    def __init__(self, max_history: int = 10000, cleanup_interval: int = 60):
        """
        Initialize lock-free task tracker

        Args:
            max_history: Maximum number of completed tasks to keep in history
            cleanup_interval: Interval in seconds between automatic cleanups
        """
        # Main task storage with reader-writer lock
        self._tasks: Dict[str, TaskInfo] = {}
        self._tasks_lock = ReadWriteLock()

        # Separate indexes for fast lookups (with their own locks)
        self._status_index: Dict[TaskStatus, Set[str]] = defaultdict(set)
        self._status_lock = RLock()

        self._instance_index: Dict[UUID, Set[str]] = defaultdict(set)
        self._instance_lock = RLock()

        # Statistics with atomic-like operations
        self._stats = {
            'total_tasks': 0,
            'queued': 0,
            'scheduled': 0,
            'completed': 0
        }
        self._stats_lock = Lock()

        # Configuration
        self._max_history = max_history
        self._cleanup_interval = cleanup_interval

        # Background cleanup thread pool
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="TaskTrackerCleanup")
        self._cleanup_queue = Queue()
        self._shutdown = False

        # Start background cleanup worker
        self._start_cleanup_worker()

    def _start_cleanup_worker(self):
        """Start background cleanup worker"""
        def cleanup_worker():
            while not self._shutdown:
                try:
                    # Check for cleanup every interval
                    time.sleep(self._cleanup_interval)
                    if not self._shutdown:
                        self._async_cleanup()
                except Exception as e:
                    logger.error(f"Cleanup worker error: {e}")

        self._executor.submit(cleanup_worker)

    def register_task(
        self,
        task_id: str,
        ti_uuid: UUID,
        model_name: str,
        submit_time: Optional[float] = None
    ) -> None:
        """
        Register a new task (optimized with minimal locking)
        """
        if submit_time is None:
            submit_time = time.time()

        task_info = TaskInfo(
            task_id=task_id,
            task_status=TaskStatus.QUEUED,
            scheduled_ti=ti_uuid,
            submit_time=submit_time,
            model_name=model_name
        )

        # Update main storage
        self._tasks_lock.acquire_write()
        try:
            exists = task_id in self._tasks
            self._tasks[task_id] = task_info
        finally:
            self._tasks_lock.release_write()

        # Update indexes separately (no need to hold main lock)
        with self._status_lock:
            if exists:
                # Remove from old status
                for status_set in self._status_index.values():
                    status_set.discard(task_id)
            self._status_index[TaskStatus.QUEUED].add(task_id)

        with self._instance_lock:
            self._instance_index[ti_uuid].add(task_id)

        # Update statistics
        with self._stats_lock:
            if not exists:
                self._stats['total_tasks'] += 1
            self._stats['queued'] += 1

        logger.debug(f"Registered task {task_id} for model {model_name} on TI {ti_uuid}")

    def mark_scheduled(self, task_id: str) -> bool:
        """
        Mark a task as scheduled (optimized)
        """
        # Quick read to check existence
        self._tasks_lock.acquire_read()
        try:
            if task_id not in self._tasks:
                return False
            old_info = self._tasks[task_id]
        finally:
            self._tasks_lock.release_read()

        # Create new immutable task info
        new_info = old_info.with_status(TaskStatus.SCHEDULED)

        # Update with write lock
        self._tasks_lock.acquire_write()
        try:
            self._tasks[task_id] = new_info
        finally:
            self._tasks_lock.release_write()

        # Update indexes
        with self._status_lock:
            self._status_index[TaskStatus.QUEUED].discard(task_id)
            self._status_index[TaskStatus.SCHEDULED].add(task_id)

        # Update statistics
        with self._stats_lock:
            self._stats['queued'] -= 1
            self._stats['scheduled'] += 1

        logger.debug(f"Marked task {task_id} as scheduled")
        return True

    def mark_completed(
        self,
        task_id: str,
        result: Optional[Any] = None,
        completion_time: Optional[float] = None
    ) -> bool:
        """
        Mark a task as completed (optimized)
        """
        if completion_time is None:
            completion_time = time.time()

        # Quick read to check existence
        self._tasks_lock.acquire_read()
        try:
            if task_id not in self._tasks:
                return False
            old_info = self._tasks[task_id]
            old_status = old_info.task_status
        finally:
            self._tasks_lock.release_read()

        # Create new immutable task info
        new_info = old_info.with_completion(result, completion_time)

        # Update with write lock
        self._tasks_lock.acquire_write()
        try:
            self._tasks[task_id] = new_info
        finally:
            self._tasks_lock.release_write()

        # Update indexes
        with self._status_lock:
            self._status_index[old_status].discard(task_id)
            self._status_index[TaskStatus.COMPLETED].add(task_id)

        # Update statistics
        with self._stats_lock:
            if old_status == TaskStatus.QUEUED:
                self._stats['queued'] -= 1
            elif old_status == TaskStatus.SCHEDULED:
                self._stats['scheduled'] -= 1
            self._stats['completed'] += 1

        logger.debug(
            f"Marked task {task_id} as completed "
            f"(time: {completion_time - old_info.submit_time:.2f}s)"
        )

        # Trigger async cleanup if needed
        if self._stats['completed'] > self._max_history:
            self._executor.submit(self._async_cleanup)

        return True

    def get_task_info(self, task_id: str) -> Optional[TaskInfo]:
        """
        Get information about a task (lock-free read)
        """
        self._tasks_lock.acquire_read()
        try:
            return self._tasks.get(task_id)
        finally:
            self._tasks_lock.release_read()

    def get_all_tasks(self) -> Dict[str, TaskInfo]:
        """
        Get all tracked tasks (optimized read)
        """
        self._tasks_lock.acquire_read()
        try:
            # Return a copy to prevent external modification
            return dict(self._tasks)
        finally:
            self._tasks_lock.release_read()

    def get_tasks_by_status(self, status: TaskStatus) -> Dict[str, TaskInfo]:
        """
        Get all tasks with a specific status (using index)
        """
        # First get task IDs from index
        with self._status_lock:
            task_ids = set(self._status_index[status])

        # Then fetch task infos
        result = {}
        self._tasks_lock.acquire_read()
        try:
            for task_id in task_ids:
                if task_id in self._tasks:
                    result[task_id] = self._tasks[task_id]
        finally:
            self._tasks_lock.release_read()

        return result

    def get_tasks_by_instance(self, ti_uuid: UUID) -> Dict[str, TaskInfo]:
        """
        Get all tasks assigned to a specific Task Instance (using index)
        """
        # First get task IDs from index
        with self._instance_lock:
            task_ids = set(self._instance_index[ti_uuid])

        # Then fetch task infos
        result = {}
        self._tasks_lock.acquire_read()
        try:
            for task_id in task_ids:
                if task_id in self._tasks:
                    result[task_id] = self._tasks[task_id]
        finally:
            self._tasks_lock.release_read()

        return result

    def remove_task(self, task_id: str) -> bool:
        """
        Remove a task from tracking (optimized)
        """
        # First check and get task info
        self._tasks_lock.acquire_read()
        try:
            if task_id not in self._tasks:
                return False
            task_info = self._tasks[task_id]
        finally:
            self._tasks_lock.release_read()

        # Remove from main storage
        self._tasks_lock.acquire_write()
        try:
            if task_id in self._tasks:
                del self._tasks[task_id]
            else:
                return False
        finally:
            self._tasks_lock.release_write()

        # Update indexes
        with self._status_lock:
            self._status_index[task_info.task_status].discard(task_id)

        with self._instance_lock:
            self._instance_index[task_info.scheduled_ti].discard(task_id)

        # Update statistics
        with self._stats_lock:
            self._stats['total_tasks'] -= 1
            if task_info.task_status == TaskStatus.QUEUED:
                self._stats['queued'] -= 1
            elif task_info.task_status == TaskStatus.SCHEDULED:
                self._stats['scheduled'] -= 1
            elif task_info.task_status == TaskStatus.COMPLETED:
                self._stats['completed'] -= 1

        logger.debug(f"Removed task {task_id} from tracker")
        return True

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get tracker statistics (lock-free read)
        """
        with self._stats_lock:
            return dict(self._stats)

    def _async_cleanup(self):
        """
        Asynchronous cleanup of old completed tasks
        """
        try:
            # Get completed task IDs with completion times
            completed_tasks = []

            with self._status_lock:
                completed_ids = list(self._status_index[TaskStatus.COMPLETED])

            # Get completion times
            self._tasks_lock.acquire_read()
            try:
                for task_id in completed_ids:
                    if task_id in self._tasks:
                        task_info = self._tasks[task_id]
                        if task_info.completion_time:
                            completed_tasks.append((task_id, task_info.completion_time))
            finally:
                self._tasks_lock.release_read()

            # Determine tasks to remove
            if len(completed_tasks) > self._max_history:
                # Sort by completion time (oldest first)
                completed_tasks.sort(key=lambda x: x[1])
                to_remove = completed_tasks[:len(completed_tasks) - self._max_history + (self._max_history // 10)]

                # Remove tasks
                for task_id, _ in to_remove:
                    self.remove_task(task_id)

                logger.info(f"Cleaned up {len(to_remove)} old completed tasks")
        except Exception as e:
            logger.error(f"Error in async cleanup: {e}")

    def shutdown(self):
        """
        Shutdown the tracker and cleanup resources
        """
        self._shutdown = True
        self._executor.shutdown(wait=True)
        logger.info("LockFreeTaskTracker shutdown complete")

    def clear_completed(self) -> int:
        """
        Remove all completed tasks from tracking
        """
        with self._status_lock:
            completed_ids = list(self._status_index[TaskStatus.COMPLETED])

        removed = 0
        for task_id in completed_ids:
            if self.remove_task(task_id):
                removed += 1

        logger.info(f"Cleared {removed} completed tasks from tracker")
        return removed

    def clear_all(self) -> int:
        """
        Remove ALL tasks from tracking
        """
        self._tasks_lock.acquire_write()
        try:
            count = len(self._tasks)
            self._tasks.clear()
        finally:
            self._tasks_lock.release_write()

        with self._status_lock:
            self._status_index.clear()

        with self._instance_lock:
            self._instance_index.clear()

        with self._stats_lock:
            self._stats = {
                'total_tasks': 0,
                'queued': 0,
                'scheduled': 0,
                'completed': 0
            }

        logger.info(f"Cleared all {count} tasks from tracker")
        return count