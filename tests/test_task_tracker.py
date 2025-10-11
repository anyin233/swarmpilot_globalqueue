"""
TaskTracker Unit Tests

Tests for task state tracking functionality
"""

import pytest
from uuid import uuid4
from src.scheduler.task_tracker import TaskTracker, TaskInfo
from src.scheduler.models import TaskStatus


def test_register_task():
    """Test registering a new task"""
    tracker = TaskTracker()
    ti_uuid = uuid4()

    tracker.register_task(
        task_id="task-1",
        ti_uuid=ti_uuid,
        model_name="test_model"
    )

    task_info = tracker.get_task_info("task-1")
    assert task_info is not None
    assert task_info.task_id == "task-1"
    assert task_info.task_status == TaskStatus.QUEUED
    assert task_info.scheduled_ti == ti_uuid
    assert task_info.model_name == "test_model"


def test_mark_scheduled():
    """Test marking task as scheduled"""
    tracker = TaskTracker()
    ti_uuid = uuid4()

    tracker.register_task("task-1", ti_uuid, "test_model")
    result = tracker.mark_scheduled("task-1")

    assert result is True
    task_info = tracker.get_task_info("task-1")
    assert task_info.task_status == TaskStatus.SCHEDULED


def test_mark_scheduled_nonexistent():
    """Test marking non-existent task as scheduled"""
    tracker = TaskTracker()
    result = tracker.mark_scheduled("nonexistent-task")
    assert result is False


def test_mark_completed():
    """Test marking task as completed"""
    tracker = TaskTracker()
    ti_uuid = uuid4()

    tracker.register_task("task-1", ti_uuid, "test_model")
    result = tracker.mark_completed("task-1", result={"output": "test"})

    assert result is True
    task_info = tracker.get_task_info("task-1")
    assert task_info.task_status == TaskStatus.COMPLETED
    assert task_info.result == {"output": "test"}


def test_mark_completed_nonexistent():
    """Test marking non-existent task as completed"""
    tracker = TaskTracker()
    result = tracker.mark_completed("nonexistent-task", result={"output": "test"})
    assert result is False


def test_get_tasks_by_status():
    """Test getting tasks by status"""
    tracker = TaskTracker()
    ti_uuid1 = uuid4()
    ti_uuid2 = uuid4()

    # Create tasks with different statuses
    tracker.register_task("task-1", ti_uuid1, "test_model")
    tracker.register_task("task-2", ti_uuid2, "test_model")
    tracker.mark_scheduled("task-2")

    # Query by status (returns Dict)
    queued_tasks = tracker.get_tasks_by_status(TaskStatus.QUEUED)
    scheduled_tasks = tracker.get_tasks_by_status(TaskStatus.SCHEDULED)

    assert len(queued_tasks) == 1
    assert "task-1" in queued_tasks
    assert queued_tasks["task-1"].task_id == "task-1"

    assert len(scheduled_tasks) == 1
    assert "task-2" in scheduled_tasks
    assert scheduled_tasks["task-2"].task_id == "task-2"


def test_task_lifecycle():
    """Test complete task lifecycle"""
    tracker = TaskTracker()
    ti_uuid = uuid4()

    # Register
    tracker.register_task("task-1", ti_uuid, "test_model")
    task_info = tracker.get_task_info("task-1")
    assert task_info.task_status == TaskStatus.QUEUED

    # Schedule
    tracker.mark_scheduled("task-1")
    task_info = tracker.get_task_info("task-1")
    assert task_info.task_status == TaskStatus.SCHEDULED

    # Complete
    tracker.mark_completed("task-1", result={"output": "done"})
    task_info = tracker.get_task_info("task-1")
    assert task_info.task_status == TaskStatus.COMPLETED
    assert task_info.result == {"output": "done"}


def test_submit_time_tracking():
    """Test that submit time is tracked"""
    import time
    tracker = TaskTracker()
    ti_uuid = uuid4()

    before = time.time()
    tracker.register_task("task-1", ti_uuid, "test_model")
    after = time.time()

    task_info = tracker.get_task_info("task-1")
    assert task_info.submit_time >= before
    assert task_info.submit_time <= after


def test_custom_submit_time():
    """Test registering task with custom submit time"""
    tracker = TaskTracker()
    ti_uuid = uuid4()
    custom_time = 1234567890.0

    tracker.register_task("task-1", ti_uuid, "test_model", submit_time=custom_time)

    task_info = tracker.get_task_info("task-1")
    assert task_info.submit_time == custom_time


def test_completion_time_tracking():
    """Test that completion time is tracked"""
    import time
    tracker = TaskTracker()
    ti_uuid = uuid4()

    tracker.register_task("task-1", ti_uuid, "test_model")
    time.sleep(0.01)  # Small delay

    before = time.time()
    tracker.mark_completed("task-1", result={"output": "done"})
    after = time.time()

    task_info = tracker.get_task_info("task-1")
    assert task_info.completion_time is not None
    assert task_info.completion_time >= before
    assert task_info.completion_time <= after


def test_history_cleanup():
    """Test that task history is cleaned up"""
    tracker = TaskTracker(max_history=100)
    ti_uuid = uuid4()

    # Add a task and complete it
    tracker.register_task("task-1", ti_uuid, "test_model")
    tracker.mark_completed("task-1", result={"output": "done"})

    # Task should be in history
    task_info = tracker.get_task_info("task-1")
    assert task_info is not None
    assert task_info.task_id == "task-1"

    # Clean up should move it to history
    tracker._cleanup_old_tasks()

    # Task should still be accessible (unless too many tasks)
    task_info = tracker.get_task_info("task-1")
    # With max_history=100 and only 1 task, it should still be there
    assert task_info is not None


def test_concurrent_access():
    """Test thread safety with concurrent access"""
    import threading
    tracker = TaskTracker()
    ti_uuid = uuid4()

    def register_tasks(start_idx):
        for i in range(start_idx, start_idx + 10):
            tracker.register_task(f"task-{i}", ti_uuid, "test_model")

    threads = []
    for i in range(5):
        t = threading.Thread(target=register_tasks, args=(i * 10,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Should have 50 tasks
    all_tasks = tracker.get_tasks_by_status(TaskStatus.QUEUED)
    assert len(all_tasks) == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
