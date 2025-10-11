#!/usr/bin/env python3
"""
Basic Usage Example

Demonstrates how to use the scheduler programmatically.
"""

from src.scheduler import SwarmPilotScheduler
from src.scheduler.models import SchedulerRequest

def main():
    # 1. Create scheduler
    print("Creating scheduler...")
    scheduler = SwarmPilotScheduler()

    # 2. Load configuration
    print("Loading configuration...")
    try:
        scheduler.load_task_instances_from_config("examples/config_example.yaml")
        print(f"✓ Loaded {len(scheduler.taskinstances)} TaskInstances")
    except Exception as e:
        print(f"✗ Failed to load config: {e}")
        print("Note: Make sure TaskInstances are running at the configured ports")
        return

    # 3. Submit task
    print("\nSubmitting task...")
    request = SchedulerRequest(
        model_type="test_model",
        input_data={"prompt": "Hello, world!"},
        metadata={"user": "example"}
    )

    try:
        response = scheduler.schedule(request)
        print(f"✓ Task {response.task_id} scheduled to instance {response.instance_id}")
        print(f"  Model type: {response.model_type}")

        # 4. Query task
        print("\nQuerying task status...")
        task_info = scheduler.task_tracker.get_task_info(response.task_id)
        if task_info:
            print(f"✓ Task status: {task_info.task_status}")
            print(f"  Scheduled to: {task_info.scheduled_ti}")
            print(f"  Model: {task_info.model_name}")
            print(f"  Submit time: {task_info.submit_time}")
        else:
            print("✗ Task not found in tracker")

    except RuntimeError as e:
        print(f"✗ Scheduling failed: {e}")
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    main()
