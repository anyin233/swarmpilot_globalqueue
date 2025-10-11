"""
External Interfaces Usage Example

This example demonstrates how to use the TaskInstanceClient and PredictorClient
to interact with external services.

TaskInstanceClient: ✅ Ready to use (fully implemented)
PredictorClient: ⚠️ Interface ready, service TODO (see comments below)
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scheduler import (
    TaskInstanceClient,
    PredictorClient,
    SwarmPilotScheduler,
    SchedulerRequest
)


# ========== Example 1: TaskInstanceClient Usage ==========

def example_task_instance_client():
    """
    Example: Using TaskInstanceClient to interact with a TaskInstance service

    Status: ✅ READY TO USE
    Prerequisites: TaskInstance service running at http://localhost:8100
    """
    print("=" * 60)
    print("Example 1: TaskInstanceClient Usage")
    print("=" * 60)

    # Initialize client
    client = TaskInstanceClient("http://localhost:8100", timeout=30.0)

    try:
        # 1. Get instance status
        print("\n1. Getting instance status...")
        try:
            status = client.get_status()
            print(f"   Instance ID: {status.instance_id}")
            print(f"   Model Type: {status.model_type}")
            print(f"   Replicas Running: {status.replicas_running}")
            print(f"   Queue Size: {status.queue_size}")
            print(f"   Status: {status.status}")
        except Exception as e:
            print(f"   ⚠️  Could not connect to TaskInstance: {e}")
            print(f"   Make sure TaskInstance is running at http://localhost:8100")

        # 2. Enqueue a task
        print("\n2. Enqueuing a task...")
        try:
            task_response = client.enqueue_task(
                input_data={
                    "prompt": "What is artificial intelligence?",
                    "max_tokens": 100,
                    "temperature": 0.7
                },
                metadata={
                    "user_id": "example_user",
                    "priority": "normal"
                }
            )
            print(f"   ✓ Task ID: {task_response.task_id}")
            print(f"   Queue Size: {task_response.queue_size}")
            print(f"   Enqueue Time: {task_response.enqueue_time}")

            # 3. Get queue prediction
            print("\n3. Getting queue prediction...")
            prediction = client.predict_queue()
            print(f"   Expected Time: {prediction.expected_ms:.2f} ms")
            print(f"   Error Margin: ±{prediction.error_ms:.2f} ms")
            print(f"   Queue Size: {prediction.queue_size}")

        except Exception as e:
            print(f"   ⚠️  Task operation failed: {e}")

    finally:
        client.close()
        print("\n✓ Client closed")


# ========== Example 2: PredictorClient Usage ==========

def example_predictor_client():
    """
    Example: Using PredictorClient to get execution time predictions

    Status: ⚠️ INTERFACE DEFINED - SERVICE TODO

    TODO: To activate this functionality:
    1. Implement a Predictor service at http://localhost:8200 with:
       - POST /predict endpoint
       - GET /health endpoint
       - GET /models endpoint
    2. Uncomment the actual HTTP requests in predictor_client.py
    3. See docs/EXTERNAL_INTERFACES.md for API specifications

    Current Behavior: Returns placeholder error responses
    """
    print("\n" + "=" * 60)
    print("Example 2: PredictorClient Usage")
    print("=" * 60)

    # Initialize client
    predictor = PredictorClient("http://localhost:8200", timeout=10.0)

    try:
        # 1. Check if service is available
        print("\n1. Checking Predictor service availability...")
        is_available = predictor.is_available()
        print(f"   Available: {is_available}")

        if not is_available:
            print("   ⚠️  Predictor service not available (expected - TODO)")
            print("   This is a placeholder. See TODO comments above.")

        # 2. Request prediction (will return error response until service implemented)
        print("\n2. Requesting execution time prediction...")
        response = predictor.predict(
            model_type="gpt-3.5-turbo",
            metadata={
                "hardware": "A100",
                "software_name": "vllm",
                "software_version": "0.2.0",
                "input_tokens": 100,
                "output_tokens": 50
            }
        )

        if response.status == "success":
            print(f"   ✓ Model Type: {response.model_type}")
            print(f"   Quantiles: {response.quantiles}")
            print(f"   Predictions (ms): {response.quantile_predictions}")
            print(f"   Method: {response.prediction_method}")
            print(f"   Confidence: {response.confidence}")

            # Extract median prediction
            median_idx = response.quantiles.index(0.5)
            median_time = response.quantile_predictions[median_idx]
            print(f"\n   Median Prediction: {median_time:.2f} ms")
        else:
            print(f"   ⚠️  Prediction failed: {response.message}")
            print(f"   Status: {response.status}")

        # 3. Use convenience methods
        print("\n3. Using convenience methods...")
        median = predictor.get_median_prediction("gpt-3.5-turbo")
        if median:
            print(f"   Median: {median:.2f} ms")
        else:
            print("   ⚠️  No median prediction available (service not implemented)")

        pred_range = predictor.get_prediction_range(
            "gpt-3.5-turbo",
            {"hardware": "A100"},
            confidence_level=0.8
        )
        if pred_range:
            min_time, max_time = pred_range
            print(f"   80% Range: {min_time:.2f} - {max_time:.2f} ms")
        else:
            print("   ⚠️  No prediction range available (service not implemented)")

    finally:
        predictor.close()
        print("\n✓ Client closed")


# ========== Example 3: Using LookupPredictor as Fallback ==========

def example_lookup_predictor_fallback():
    """
    Example: Using LookupPredictor when PredictorClient service is not available

    Status: ✅ READY TO USE
    Prerequisites: Prediction JSON file at specified path
    """
    from src.scheduler import LookupPredictor

    print("\n" + "=" * 60)
    print("Example 3: LookupPredictor Fallback")
    print("=" * 60)

    # Path to prediction file (update this path as needed)
    prediction_file = "/home/yanweiye/Project/swarmpilot/swarmpilot_taskinstance/pred.json"

    print(f"\nLoading predictions from: {prediction_file}")

    try:
        predictor = LookupPredictor(prediction_file)

        # Get statistics
        stats = predictor.get_stats()
        print(f"\nPrediction Statistics:")
        print(f"   Total Records: {stats['total_records']}")
        print(f"   Successful Records: {stats['successful_records']}")
        print(f"   Model Types: {', '.join(stats['model_types'])}")

        # Lookup prediction
        print(f"\nLooking up prediction for test_model...")
        prediction = predictor.predict(
            model_type="test_model",
            metadata={}
        )

        if prediction:
            print(f"   ✓ Found prediction")
            print(f"   Quantiles: {prediction.get('quantiles', [])}")
            print(f"   Predictions: {prediction.get('quantile_predictions', [])}")
        else:
            print(f"   ⚠️  No prediction found")

    except FileNotFoundError:
        print(f"   ⚠️  Prediction file not found at: {prediction_file}")
        print(f"   Update the path or create a prediction file")
    except Exception as e:
        print(f"   ⚠️  Error: {e}")


# ========== Example 4: Integrated Scheduling with Predictions ==========

def example_integrated_scheduling():
    """
    Example: Complete scheduling flow with TaskInstance and Predictor

    Status: Partially ready (TaskInstance ✅, Predictor ⚠️ TODO)
    """
    print("\n" + "=" * 60)
    print("Example 4: Integrated Scheduling")
    print("=" * 60)

    # Initialize scheduler
    scheduler = SwarmPilotScheduler()

    # Initialize clients
    ti_client = TaskInstanceClient("http://localhost:8100")
    predictor = PredictorClient("http://localhost:8200")

    try:
        # Register TaskInstance
        print("\n1. Registering TaskInstance...")
        try:
            ti_uuid = scheduler.add_task_instance(
                "http://localhost:8100",
                model_name="gpt-3.5-turbo"
            )
            print(f"   ✓ Registered: {ti_uuid}")
        except Exception as e:
            print(f"   ⚠️  Registration failed: {e}")
            return

        # Get prediction (optional - for monitoring)
        print("\n2. Getting execution time prediction...")
        pred_response = predictor.predict(
            model_type="gpt-3.5-turbo",
            metadata={"hardware": "A100", "input_tokens": 100}
        )

        if pred_response.status == "success":
            median_idx = pred_response.quantiles.index(0.5)
            expected_time = pred_response.quantile_predictions[median_idx]
            print(f"   ✓ Expected execution time: {expected_time:.2f} ms")
        else:
            print(f"   ⚠️  Prediction not available: {pred_response.message}")
            expected_time = None

        # Schedule task
        print("\n3. Scheduling task...")
        request = SchedulerRequest(
            model_type="gpt-3.5-turbo",
            input_data={
                "prompt": "Explain quantum computing",
                "max_tokens": 150
            },
            metadata={
                "hardware": "A100",
                "input_tokens": 100,
                "expected_time": expected_time
            }
        )

        try:
            response = scheduler.schedule(request)
            print(f"   ✓ Task scheduled: {response.task_id}")
            print(f"   Instance: {response.instance_id}")
            print(f"   Queue Size: {response.queue_size}")

            # Query task status
            print("\n4. Querying task status...")
            task_info = scheduler.task_tracker.get_task_info(response.task_id)
            print(f"   Status: {task_info.task_status.value}")
            print(f"   Submit Time: {task_info.submit_time}")

        except Exception as e:
            print(f"   ⚠️  Scheduling failed: {e}")

    finally:
        ti_client.close()
        predictor.close()
        print("\n✓ Clients closed")


# ========== Main ==========

def main():
    """Run all examples"""
    print("\n" + "=" * 60)
    print("External Interfaces Usage Examples")
    print("=" * 60)
    print("\nThese examples demonstrate interaction with external services:")
    print("  • TaskInstance: Worker service for task execution")
    print("  • Predictor: Service for execution time predictions")
    print("\n")

    # Run examples
    example_task_instance_client()
    example_predictor_client()
    example_lookup_predictor_fallback()
    example_integrated_scheduling()

    print("\n" + "=" * 60)
    print("Examples Complete")
    print("=" * 60)
    print("\nFor more information, see:")
    print("  • docs/EXTERNAL_INTERFACES.md - Complete interface specification")
    print("  • docs/INTEGRATION_GUIDE.md - Integration guide")
    print("  • src/scheduler/client.py - TaskInstanceClient implementation")
    print("  • src/scheduler/predictor_client.py - PredictorClient implementation")
    print("")


if __name__ == "__main__":
    main()
