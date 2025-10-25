"""
Async Task Instance Client

Asynchronous client for TaskInstance API using httpx.AsyncClient.
Provides async methods for high-throughput task submission.
"""
import httpx
import asyncio
import time
from typing import Optional, Dict, Any, List
from loguru import logger

from .models import (
    InstanceStatus,
    InstanceStatusResponse,
    EnqueueResponse,
    PredictResponse,
    TaskResult
)


class AsyncTaskInstanceClient:
    """
    Asynchronous client for TaskInstance API

    Supports concurrent HTTP requests for high-throughput scenarios.

    Args:
        base_url: TaskInstance service URL (e.g., "http://localhost:8100")
        timeout: Request timeout in seconds
        max_connections: Maximum concurrent connections
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        max_connections: int = 100
    ):
        """Initialize async TaskInstance client"""
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_connections = max_connections

        # Async client with connection pooling
        limits = httpx.Limits(
            max_keepalive_connections=max_connections,
            max_connections=max_connections
        )
        self.client = httpx.AsyncClient(
            timeout=timeout,
            limits=limits
        )

    async def __aenter__(self):
        """Async context manager support"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close HTTP client"""
        await self.close()

    async def close(self):
        """Close HTTP client connection"""
        await self.client.aclose()

    # ========== Status API ==========

    async def get_status(self) -> InstanceStatusResponse:
        """
        Get TaskInstance status asynchronously

        Returns:
            InstanceStatusResponse: Current status of this instance

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        response = await self.client.get(f"{self.base_url}/info")
        response.raise_for_status()
        data = response.json()

        deployed_model = data.get("deployed_model")
        queue_info = data.get("queue_info", {})
        instance_id = self.base_url.replace("http://", "").replace("https://", "")

        return InstanceStatusResponse(
            instance_id=instance_id,
            model_type=deployed_model.get("model_name") if deployed_model else None,
            replicas_running=deployed_model.get("replicas") if deployed_model else 0,
            queue_size=queue_info.get("length_of_queue", 0),
            status=data.get("instance_status", "unknown")
        )

    # ========== Queue Management API ==========

    async def enqueue_task(
        self,
        input_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> EnqueueResponse:
        """
        Enqueue a task asynchronously

        Args:
            input_data: Task input data
            metadata: Optional task metadata
            task_id: Optional task ID (provided by Scheduler)
            model_name: Model name for the task

        Returns:
            EnqueueResponse: Task ID and queue information

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        # If model_name not provided, get it from instance status
        if model_name is None:
            status = await self.get_status()
            model_name = status.model_type

        request_data = {
            "model_name": model_name,
            "task_input": input_data,
            "metadata": metadata or {},
            "task_id": task_id
        }

        response = await self.client.post(
            f"{self.base_url}/queue/submit",
            json=request_data
        )
        response.raise_for_status()
        result = response.json()

        return EnqueueResponse(
            task_id=result.get("task_id"),
            queue_size=0,  # Not provided by new API
            enqueue_time=time.time()
        )

    async def predict_queue(self) -> PredictResponse:
        """
        Predict queue completion time asynchronously

        Returns:
            PredictResponse: Expected completion time and error margin

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        response = await self.client.post(f"{self.base_url}/queue/predict")
        response.raise_for_status()
        return PredictResponse(**response.json())

    # ========== Batch Operations ==========

    async def enqueue_tasks_batch(
        self,
        tasks: List[Dict[str, Any]]
    ) -> List[EnqueueResponse]:
        """
        Enqueue multiple tasks concurrently

        Args:
            tasks: List of task data dicts with keys:
                - input_data: Task input
                - metadata: Optional metadata
                - task_id: Optional task ID
                - model_name: Model name

        Returns:
            List[EnqueueResponse]: List of enqueue responses
        """
        # Create concurrent tasks
        enqueue_coros = [
            self.enqueue_task(
                input_data=task.get("input_data", {}),
                metadata=task.get("metadata"),
                task_id=task.get("task_id"),
                model_name=task.get("model_name")
            )
            for task in tasks
        ]

        # Execute concurrently
        results = await asyncio.gather(*enqueue_coros, return_exceptions=True)

        # Convert exceptions to failed responses
        responses = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to enqueue task {i}: {result}")
                # Create a fake failed response
                responses.append(EnqueueResponse(
                    task_id=tasks[i].get("task_id", f"failed-{i}"),
                    queue_size=0,
                    enqueue_time=time.time()
                ))
            else:
                responses.append(result)

        return responses

    # ========== Convenience Methods ==========

    async def get_prediction_time(self) -> tuple[float, float]:
        """
        Get queue prediction time asynchronously

        Returns:
            tuple[float, float]: (expected_ms, error_ms)
        """
        result = await self.predict_queue()
        return result.expected_ms, result.error_ms

    async def is_running(self) -> bool:
        """
        Check if instance has running models

        Returns:
            bool: True if models are running
        """
        try:
            status = await self.get_status()
            return status.status == "running"
        except httpx.HTTPError:
            return False

    async def get_model_type(self) -> Optional[str]:
        """
        Get the model type this instance manages

        Returns:
            Optional[str]: Model type or None if not configured
        """
        try:
            status = await self.get_status()
            return status.model_type
        except httpx.HTTPError:
            return None
