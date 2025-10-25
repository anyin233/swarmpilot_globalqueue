#!/usr/bin/env python3
"""
Example: Using Optimized Async Scheduler for High QPS

This example demonstrates how to configure and use the optimized
async scheduler to achieve 1000+ QPS task submission.

Requirements:
- Scheduler running on http://localhost:8200
- TaskInstances registered and running
- Fake predictor data (optional, for testing)
"""

import requests
import time
from concurrent.futures import ThreadPoolExecutor


SCHEDULER_URL = "http://localhost:8200"


def configure_optimized_scheduler(
    num_workers: int = 8,
    batch_size: int = 20,
    max_queue_size: int = 15000
):
    """
    Configure scheduler for high QPS (1000+)

    Args:
        num_workers: Number of worker threads per model type (default: 8)
        batch_size: Batch size for processing (default: 20)
        max_queue_size: Maximum pending queue size (default: 15000)
    """
    print("Configuring optimized scheduler...")

    settings = [
        ("async_use_optimized", True),
        ("async_num_workers", num_workers),
        ("async_batch_size", batch_size),
        ("async_max_queue_size", max_queue_size),
        ("async_retry_attempts", 3),
        ("async_retry_delay_ms", 100),
    ]

    for key, value in settings:
        response = requests.post(
            f"{SCHEDULER_URL}/settings/set",
            json={"key": key, "value": value}
        )
        if response.status_code == 200:
            print(f"  ✓ Set {key} = {value}")
        else:
            print(f"  ✗ Failed to set {key}")
            return False

    print("  ✓ Configuration complete")
    return True


def enable_async_scheduling():
    """Enable async scheduling"""
    print("\nEnabling async scheduling...")

    response = requests.post(f"{SCHEDULER_URL}/scheduler/async/enable")
    if response.status_code == 200:
        data = response.json()
        print(f"  ✓ Enabled: {data.get('message')}")
        print(f"  Config: {data.get('config')}")
        return True
    else:
        print(f"  ✗ Failed to enable async scheduling")
        return False


def submit_task(model_name: str, task_index: int) -> dict:
    """Submit a single task"""
    start_time = time.time()

    try:
        response = requests.post(
            f"{SCHEDULER_URL}/queue/submit_async",
            json={
                "model_name": model_name,
                "task_input": {},
                "metadata": {"task_index": task_index}
            },
            timeout=5
        )

        elapsed = (time.time() - start_time) * 1000  # ms

        if response.status_code == 200:
            task_id = response.json().get("task_id")
            return {
                "success": True,
                "task_id": task_id,
                "latency_ms": elapsed
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "latency_ms": elapsed
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "latency_ms": (time.time() - start_time) * 1000
        }


def submit_high_qps_workload(
    num_tasks: int = 1000,
    target_qps: int = 1000,
    max_workers: int = 50
):
    """
    Submit tasks at high QPS

    Args:
        num_tasks: Total number of tasks to submit
        target_qps: Target queries per second
        max_workers: Max concurrent HTTP workers
    """
    print(f"\nSubmitting {num_tasks} tasks at {target_qps} QPS...")

    start_time = time.time()
    results = []
    delay = 1.0 / target_qps

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []

        for i in range(num_tasks):
            # Round-robin across model types
            model_name = ["fake_drc", "fake_orca", "fake_t2vid"][i % 3]

            # Submit task
            future = executor.submit(submit_task, model_name, i)
            futures.append(future)

            # Rate limiting
            if i < num_tasks - 1:
                time.sleep(delay)

            # Progress
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                actual_qps = (i + 1) / elapsed
                print(f"  Submitted {i + 1}/{num_tasks} ({actual_qps:.0f} QPS)")

        # Collect results
        print("  Waiting for all submissions...")
        for future in futures:
            results.append(future.result())

    # Calculate statistics
    elapsed_time = time.time() - start_time
    successful = sum(1 for r in results if r.get("success"))
    failed = len(results) - successful
    latencies = [r.get("latency_ms", 0) for r in results if r.get("success")]

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p90_latency = sorted(latencies)[int(len(latencies) * 0.9)] if latencies else 0
    p99_latency = sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0

    print(f"\n{'='*60}")
    print("Submission Results:")
    print(f"{'='*60}")
    print(f"  Total tasks:      {num_tasks}")
    print(f"  Successful:       {successful} ({successful/num_tasks*100:.1f}%)")
    print(f"  Failed:           {failed}")
    print(f"  Elapsed time:     {elapsed_time:.2f}s")
    print(f"  Target QPS:       {target_qps}")
    print(f"  Actual QPS:       {num_tasks/elapsed_time:.1f}")
    print(f"\nLatency Statistics:")
    print(f"  Average:          {avg_latency:.2f}ms")
    print(f"  P90:              {p90_latency:.2f}ms")
    print(f"  P99:              {p99_latency:.2f}ms")

    return {
        "total": num_tasks,
        "successful": successful,
        "failed": failed,
        "elapsed_time": elapsed_time,
        "actual_qps": num_tasks / elapsed_time,
        "avg_latency_ms": avg_latency
    }


def monitor_scheduler():
    """Get current scheduler statistics"""
    print(f"\n{'='*60}")
    print("Scheduler Statistics:")
    print(f"{'='*60}")

    response = requests.get(f"{SCHEDULER_URL}/scheduler/async/statistics")
    if response.status_code != 200:
        print("  ✗ Failed to get statistics")
        return

    stats = response.json()
    print(f"  Enabled:          {stats.get('enabled')}")
    print(f"  Model types:      {stats.get('model_count')}")

    for scheduler in stats.get('schedulers', []):
        model = scheduler.get('model_type')
        pending = scheduler.get('pending_count', 0)
        scheduled = scheduler.get('total_scheduled', 0)
        failed = scheduler.get('total_failed', 0)
        batches = scheduler.get('total_batches', 0)
        workers = scheduler.get('num_workers', 0)

        print(f"\n  {model}:")
        print(f"    Pending:        {pending}")
        print(f"    Scheduled:      {scheduled}")
        print(f"    Failed:         {failed}")
        print(f"    Batches:        {batches}")
        print(f"    Workers:        {workers}")


def main():
    """Main example workflow"""
    print("="*60)
    print("Optimized Async Scheduler Example")
    print("="*60)

    # Check scheduler health
    print("\nChecking scheduler health...")
    try:
        response = requests.get(f"{SCHEDULER_URL}/health", timeout=5)
        if response.status_code == 200:
            print(f"  ✓ Scheduler is healthy")
        else:
            print(f"  ✗ Scheduler not healthy")
            return
    except Exception as e:
        print(f"  ✗ Cannot connect to scheduler: {e}")
        return

    # Step 1: Configure optimized scheduler
    if not configure_optimized_scheduler(
        num_workers=8,
        batch_size=20,
        max_queue_size=15000
    ):
        print("Configuration failed!")
        return

    # Step 2: Enable async scheduling
    if not enable_async_scheduling():
        print("Failed to enable async scheduling!")
        return

    time.sleep(2)

    # Step 3: Submit high QPS workload
    results = submit_high_qps_workload(
        num_tasks=1000,
        target_qps=1000,
        max_workers=50
    )

    # Step 4: Monitor statistics
    time.sleep(2)
    monitor_scheduler()

    # Summary
    print(f"\n{'='*60}")
    print("Summary:")
    print(f"{'='*60}")

    if results['actual_qps'] >= 950:
        print("  ✅ Successfully achieved 1000 QPS target!")
        print(f"  Actual QPS: {results['actual_qps']:.0f}")
        print(f"  Avg latency: {results['avg_latency_ms']:.2f}ms")
    else:
        print("  ⚠  Did not reach 1000 QPS target")
        print(f"  Actual QPS: {results['actual_qps']:.0f}")
        print("  Consider:")
        print("    - Increasing num_workers")
        print("    - Increasing batch_size")
        print("    - Checking TaskInstance availability")

    print("\nDone!")


if __name__ == "__main__":
    main()
