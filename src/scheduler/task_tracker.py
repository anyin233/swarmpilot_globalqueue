"""
Task Tracker

This module provides task state tracking functionality for the scheduler.
It maintains information about all tasks submitted to the scheduler, including:
- Task status (queued, scheduled, completed)
- Scheduled Task Instance
- Submission time
- Task results (when completed)

The tracker is thread-safe and can be used in concurrent environments.
"""

from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from threading import Lock
import time
from uuid import UUID
from loguru import logger

from .models import TaskStatus


@dataclass
class TaskInfo:
    """Information about a tracked task"""
    task_id: str
    task_status: TaskStatus
    scheduled_ti: UUID
    submit_time: float
    model_name: str
    result: Optional[Any] = None
    completion_time: Optional[float] = None


class TaskTracker:
    """
    Thread-safe task tracker for the scheduler

    This class maintains a registry of all tasks submitted to the scheduler,
    tracking their status, assigned Task Instance, and results.

    Usage:
        tracker = TaskTracker()

        # Register a new task
        tracker.register_task(task_id="task-123", ti_uuid=uuid, model_name="gpt-3.5")

        # Mark as scheduled
        tracker.mark_scheduled(task_id="task-123")

        # Mark as completed with result
        tracker.mark_completed(task_id="task-123", result={"output": "..."})

        # Query task status
        info = tracker.get_task_info(task_id="task-123")
    """

    def __init__(self, max_history: int = 10000):
        """
        Initialize task tracker

        Args:
            max_history: Maximum number of completed tasks to keep in history
                        (prevents unbounded memory growth)
        """
        self._tasks: Dict[str, TaskInfo] = {}
        self._lock = Lock()
        self._max_history = max_history
        self._completed_count = 0

    def register_task(
        self,
        task_id: str,
        ti_uuid: UUID,
        model_name: str,
        submit_time: Optional[float] = None
    ) -> None:
        """
        Register a new task that has been queued

        Args:
            task_id: Unique task identifier
            ti_uuid: UUID of the Task Instance assigned to this task
            model_name: Name of the model for this task
            submit_time: Task submission timestamp (defaults to current time)
        """
        if submit_time is None:
            submit_time = time.time()

        with self._lock:
            if task_id in self._tasks:
                logger.warning(f"Task {task_id} already registered, updating info")

            self._tasks[task_id] = TaskInfo(
                task_id=task_id,
                task_status=TaskStatus.QUEUED,
                scheduled_ti=ti_uuid,
                submit_time=submit_time,
                model_name=model_name
            )

            logger.debug(f"Registered task {task_id} for model {model_name} on TI {ti_uuid}")

    def mark_scheduled(self, task_id: str) -> bool:
        """
        Mark a task as scheduled (enqueued to Task Instance)

        Args:
            task_id: Task identifier

        Returns:
            True if task was found and updated, False otherwise
        """
        with self._lock:
            if task_id not in self._tasks:
                logger.warning(f"Cannot mark task {task_id} as scheduled: not found")
                return False

            task_info = self._tasks[task_id]
            task_info.task_status = TaskStatus.SCHEDULED
            logger.debug(f"Marked task {task_id} as scheduled")
            return True

    def mark_completed(
        self,
        task_id: str,
        result: Optional[Any] = None,
        completion_time: Optional[float] = None
    ) -> bool:
        """
        Mark a task as completed with optional result

        Args:
            task_id: Task identifier
            result: Task execution result
            completion_time: Completion timestamp (defaults to current time)

        Returns:
            True if task was found and updated, False otherwise
        """
        if completion_time is None:
            completion_time = time.time()

        with self._lock:
            if task_id not in self._tasks:
                logger.warning(f"Cannot mark task {task_id} as completed: not found")
                return False

            task_info = self._tasks[task_id]
            task_info.task_status = TaskStatus.COMPLETED
            task_info.result = result
            task_info.completion_time = completion_time

            self._completed_count += 1

            # Cleanup old completed tasks if history grows too large
            if self._completed_count > self._max_history:
                self._cleanup_old_tasks()

            logger.debug(
                f"Marked task {task_id} as completed "
                f"(time: {completion_time - task_info.submit_time:.2f}s)"
            )
            return True

    def get_task_info(self, task_id: str) -> Optional[TaskInfo]:
        """
        Get information about a task

        Args:
            task_id: Task identifier

        Returns:
            TaskInfo if found, None otherwise
        """
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> Dict[str, TaskInfo]:
        """
        Get all tracked tasks

        Returns:
            Dictionary mapping task_id to TaskInfo

        Note:
            Returns a shallow copy to prevent external modification
        """
        with self._lock:
            return self._tasks.copy()

    def get_tasks_by_status(self, status: TaskStatus) -> Dict[str, TaskInfo]:
        """
        Get all tasks with a specific status

        Args:
            status: Task status to filter by

        Returns:
            Dictionary of tasks with the specified status
        """
        with self._lock:
            return {
                task_id: info
                for task_id, info in self._tasks.items()
                if info.task_status == status
            }

    def get_tasks_by_instance(self, ti_uuid: UUID) -> Dict[str, TaskInfo]:
        """
        Get all tasks assigned to a specific Task Instance

        Args:
            ti_uuid: Task Instance UUID

        Returns:
            Dictionary of tasks assigned to the instance
        """
        with self._lock:
            return {
                task_id: info
                for task_id, info in self._tasks.items()
                if info.scheduled_ti == ti_uuid
            }

    def remove_task(self, task_id: str) -> bool:
        """
        Remove a task from tracking

        Args:
            task_id: Task identifier

        Returns:
            True if task was removed, False if not found
        """
        with self._lock:
            if task_id in self._tasks:
                task_info = self._tasks.pop(task_id)
                if task_info.task_status == TaskStatus.COMPLETED:
                    self._completed_count -= 1
                logger.debug(f"Removed task {task_id} from tracker")
                return True
            return False

    def clear_completed(self) -> int:
        """
        Remove all completed tasks from tracking

        Returns:
            Number of tasks removed
        """
        with self._lock:
            completed_tasks = [
                task_id for task_id, info in self._tasks.items()
                if info.task_status == TaskStatus.COMPLETED
            ]

            for task_id in completed_tasks:
                del self._tasks[task_id]

            removed_count = len(completed_tasks)
            self._completed_count -= removed_count

            logger.info(f"Cleared {removed_count} completed tasks from tracker")
            return removed_count

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get tracker statistics

        Returns:
            Dictionary with statistics about tracked tasks
        """
        with self._lock:
            stats = {
                "total_tasks": len(self._tasks),
                "queued": 0,
                "scheduled": 0,
                "completed": 0
            }

            for info in self._tasks.values():
                if info.task_status == TaskStatus.QUEUED:
                    stats["queued"] += 1
                elif info.task_status == TaskStatus.SCHEDULED:
                    stats["scheduled"] += 1
                elif info.task_status == TaskStatus.COMPLETED:
                    stats["completed"] += 1

            return stats

    def _cleanup_old_tasks(self) -> None:
        """
        Internal method to cleanup old completed tasks

        Removes oldest completed tasks until count is below max_history.
        Must be called while holding the lock.
        """
        # Get all completed tasks sorted by completion time
        completed_tasks = [
            (task_id, info)
            for task_id, info in self._tasks.items()
            if info.task_status == TaskStatus.COMPLETED and info.completion_time is not None
        ]

        # Sort by completion time (oldest first)
        completed_tasks.sort(key=lambda x: x[1].completion_time)

        # Calculate how many to remove
        to_remove = len(completed_tasks) - self._max_history + (self._max_history // 10)

        if to_remove > 0:
            for task_id, _ in completed_tasks[:to_remove]:
                del self._tasks[task_id]
                self._completed_count -= 1

            logger.info(f"Cleaned up {to_remove} old completed tasks from tracker")
