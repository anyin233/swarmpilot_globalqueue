"""
Task Instance Client

Client for TaskInstance API (refactored, port-less architecture).
Provides methods for model management, queue operations, and result retrieval.
"""
import httpx
from typing import Optional, Dict, Any, List

from .models import (
    InstanceStatus,
    StartModelsRequest,
    StartModelsResponse,
    StopModelsRequest,
    StopModelsResponse,
    InstanceStatusResponse,
    QueueStatusResponse,
    EnqueueRequest,
    EnqueueResponse,
    PredictResponse,
    TaskResult
)


# ========== Task Instance Client ==========

class TaskInstanceClient:
    """
    Client for refactored TaskInstance API (without port-based identification)

    Args:
        base_url: TaskInstance service URL (e.g., "http://localhost:8100")
        timeout: Request timeout in seconds
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        """Initialize TaskInstance client"""
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close HTTP client"""
        self.close()

    def close(self):
        """Close HTTP client connection"""
        self.client.close()

    # ========== Model Management API ==========

    def start_models(
        self,
        model_type: str,
        count: int = 1,
        config: Optional[Dict[str, Any]] = None,
        num_gpus_per_model: int = 0
    ) -> StartModelsResponse:
        """
        Start homogeneous model replicas

        Args:
            model_type: Type of model to deploy (all replicas will be same type)
            count: Number of replicas to start
            config: Optional configuration
            num_gpus_per_model: GPUs required per replica

        Returns:
            StartModelsResponse: Information about started replicas

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        request_data = StartModelsRequest(
            model_type=model_type,
            count=count,
            config=config or {},
            num_gpus_per_model=num_gpus_per_model
        )
        response = self.client.post(
            f"{self.base_url}/models/start",
            json=request_data.model_dump()
        )
        response.raise_for_status()
        return StartModelsResponse(**response.json())

    def stop_models(self, count: Optional[int] = None) -> StopModelsResponse:
        """
        Stop model replicas

        Args:
            count: Number of replicas to stop (None = all)

        Returns:
            StopModelsResponse: Information about stopped replicas

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        request_data = StopModelsRequest(count=count)
        response = self.client.post(
            f"{self.base_url}/models/stop",
            json=request_data.model_dump()
        )
        response.raise_for_status()
        return StopModelsResponse(**response.json())

    def get_status(self) -> InstanceStatusResponse:
        """
        Get TaskInstance status

        Returns:
            InstanceStatusResponse: Current status of this instance

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        response = self.client.get(f"{self.base_url}/status")
        response.raise_for_status()
        return InstanceStatusResponse(**response.json())

    # ========== Queue Management API ==========

    def enqueue_task(
        self,
        input_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> EnqueueResponse:
        """
        Enqueue a task to this instance

        Args:
            input_data: Task input data
            metadata: Optional task metadata

        Returns:
            EnqueueResponse: Task ID and queue information

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        request_data = EnqueueRequest(
            input_data=input_data,
            metadata=metadata or {}
        )
        response = self.client.post(
            f"{self.base_url}/queue/enqueue",
            json=request_data.model_dump()
        )
        response.raise_for_status()
        return EnqueueResponse(**response.json())

    def predict_queue(self) -> PredictResponse:
        """
        Predict queue completion time

        Returns:
            PredictResponse: Expected completion time and error margin

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        response = self.client.post(f"{self.base_url}/queue/predict")
        response.raise_for_status()
        return PredictResponse(**response.json())

    def get_queue_status(self) -> QueueStatusResponse:
        """
        Get queue status

        Returns:
            QueueStatusResponse: Queue size and model type

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        response = self.client.get(f"{self.base_url}/queue/status")
        response.raise_for_status()
        return QueueStatusResponse(**response.json())

    # ========== Result Management API ==========

    def get_result(self, task_id: str) -> TaskResult:
        """
        Get task result by ID

        Args:
            task_id: Task identifier

        Returns:
            TaskResult: Task execution result

        Raises:
            httpx.HTTPError: HTTP request failed or result not found
        """
        response = self.client.get(f"{self.base_url}/results/{task_id}")
        response.raise_for_status()
        return TaskResult(**response.json())

    def get_all_results(self) -> List[TaskResult]:
        """
        Get all results for this instance

        Returns:
            List[TaskResult]: All available results

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        response = self.client.get(f"{self.base_url}/results")
        response.raise_for_status()
        results = response.json()
        return [TaskResult(**r) for r in results]

    # ========== Convenience Methods ==========

    def get_prediction_time(self) -> tuple[float, float]:
        """
        Get queue prediction time (convenience method)

        Returns:
            tuple[float, float]: (expected_ms, error_ms)
        """
        result = self.predict_queue()
        return result.expected_ms, result.error_ms

    def is_running(self) -> bool:
        """
        Check if instance has running models

        Returns:
            bool: True if models are running
        """
        try:
            status = self.get_status()
            return status.status == "running"  # Compare with string instead of enum
        except httpx.HTTPError:
            return False

    def get_model_type(self) -> Optional[str]:
        """
        Get the model type this instance manages

        Returns:
            Optional[str]: Model type or None if not configured
        """
        try:
            status = self.get_status()
            return status.model_type
        except httpx.HTTPError:
            return None