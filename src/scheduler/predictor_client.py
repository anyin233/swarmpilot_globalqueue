"""
Predictor Service Client

Client for interacting with the Predictor service to obtain execution time predictions.
The Predictor service provides quantile-based predictions for task execution times
based on model type and task metadata.

Usage:
    predictor = PredictorClient(base_url="http://predictor:8200")
    prediction = predictor.predict("gpt-3.5-turbo", {"input_tokens": 100})
"""

import httpx
from typing import Dict, Any, Optional, List
from loguru import logger

from .models import (
    PredictorRequest,
    PredictorResponse,
    PredictorHealthResponse,
    PredictorModelsResponse
)


class PredictorClient:
    """
    Client for Predictor service API

    The Predictor service provides execution time predictions based on:
    - Model type (e.g., 'gpt-3.5-turbo', 'llama-7b')
    - Task metadata (hardware, software version, input/output size, etc.)

    The service returns quantile-based predictions that can be used for
    scheduling decisions and queue time estimation.

    Args:
        base_url: Predictor service URL (e.g., "http://predictor-service:8200")
        timeout: Request timeout in seconds (default: 10.0)

    Example:
        >>> predictor = PredictorClient("http://localhost:8200")
        >>> response = predictor.predict(
        ...     model_type="gpt-3.5-turbo",
        ...     metadata={"input_tokens": 100, "output_tokens": 50}
        ... )
        >>> if response.status == "success":
        ...     print(f"Median prediction: {response.quantile_predictions[2]}ms")
    """

    def __init__(self, base_url: str, timeout: float = 10.0):
        """
        Initialize Predictor client

        Args:
            base_url: Predictor service URL
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)
        logger.info(f"Initialized PredictorClient with base_url={self.base_url}")

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close HTTP client"""
        self.close()

    def close(self):
        """Close HTTP client connection"""
        self.client.close()

    # ========== Core Prediction API ==========

    def predict(
        self,
        model_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> PredictorResponse:
        """
        Request execution time prediction from Predictor service

        This is the main method for obtaining predictions. The Predictor will
        analyze the model_type and metadata to provide quantile-based execution
        time predictions.

        Args:
            model_type: Model identifier (e.g., 'gpt-3.5-turbo', 'llama-7b')
            metadata: Optional task metadata for more accurate predictions.
                     Common fields include:
                     - model_name: Specific model variant
                     - hardware: Hardware type (e.g., 'A100', 'V100')
                     - software_name: Framework (e.g., 'vllm', 'pytorch')
                     - software_version: Framework version
                     - input_tokens: Estimated input token count
                     - output_tokens: Estimated output token count
                     - batch_size: Batch size if applicable

        Returns:
            PredictorResponse: Prediction results with quantiles and predicted times

        Raises:
            httpx.HTTPError: HTTP request failed

        Example:
            >>> response = predictor.predict(
            ...     "gpt-3.5-turbo",
            ...     {"hardware": "A100", "input_tokens": 100}
            ... )
            >>> if response.status == "success":
            ...     median_time = response.quantile_predictions[2]  # Assuming 0.5 quantile is at index 2

        TODO: This method requires a running Predictor service.
              Implement the actual Predictor service with the following API:

              Endpoint: POST {predictor_base_url}/predict
              Request Body: {
                  "model_type": str,
                  "metadata": dict
              }
              Response: {
                  "status": "success" | "error",
                  "message": str (optional, for errors),
                  "model_type": str,
                  "quantiles": [0.1, 0.25, 0.5, 0.75, 0.9],
                  "quantile_predictions": [float, ...],
                  "prediction_method": str,
                  "confidence": float
              }
        """
        request_data = PredictorRequest(
            model_type=model_type,
            metadata=metadata or {}
        )

        try:
            # TODO: Replace with actual Predictor service call
            # For now, return a placeholder response indicating the service is not implemented
            logger.warning(
                f"PredictorClient.predict() called but service not implemented. "
                f"model_type={model_type}, metadata_keys={list((metadata or {}).keys())}"
            )

            # Return error response indicating service needs to be implemented
            return PredictorResponse(
                status="error",
                message="Predictor service not implemented. This is a placeholder response."
            )

            # Actual implementation should be:
            # response = self.client.post(
            #     f"{self.base_url}/predict",
            #     json=request_data.model_dump()
            # )
            # response.raise_for_status()
            # return PredictorResponse(**response.json())

        except httpx.HTTPError as e:
            logger.error(f"Predictor request failed: {e}")
            return PredictorResponse(
                status="error",
                message=f"HTTP request failed: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Unexpected error in predictor request: {e}")
            return PredictorResponse(
                status="error",
                message=f"Unexpected error: {str(e)}"
            )

    # ========== Service Management API ==========

    def health_check(self) -> PredictorHealthResponse:
        """
        Check if Predictor service is healthy

        Returns:
            PredictorHealthResponse: Service health status

        Raises:
            httpx.HTTPError: HTTP request failed

        TODO: Implement Predictor service health check endpoint:
              Endpoint: GET {predictor_base_url}/health
              Response: {
                  "status": "healthy" | "unhealthy",
                  "service": "predictor",
                  "version": str,
                  "total_models": int
              }
        """
        try:
            # TODO: Replace with actual health check call
            logger.warning("PredictorClient.health_check() called but service not implemented")

            return PredictorHealthResponse(
                status="unhealthy",
                service="predictor"
            )

            # Actual implementation:
            # response = self.client.get(f"{self.base_url}/health")
            # response.raise_for_status()
            # return PredictorHealthResponse(**response.json())

        except httpx.HTTPError as e:
            logger.error(f"Predictor health check failed: {e}")
            raise

    def get_available_models(self) -> PredictorModelsResponse:
        """
        Get list of models available for prediction

        Returns:
            PredictorModelsResponse: List of available models with metadata

        Raises:
            httpx.HTTPError: HTTP request failed

        TODO: Implement Predictor service models listing endpoint:
              Endpoint: GET {predictor_base_url}/models
              Response: {
                  "status": "success" | "error",
                  "models": [
                      {
                          "model_type": str,
                          "model_name": str,
                          "total_predictions": int,
                          "hardware_types": [str, ...],
                          "software_versions": [str, ...]
                      },
                      ...
                  ]
              }
        """
        try:
            # TODO: Replace with actual models listing call
            logger.warning("PredictorClient.get_available_models() called but service not implemented")

            return PredictorModelsResponse(
                status="error",
                models=[]
            )

            # Actual implementation:
            # response = self.client.get(f"{self.base_url}/models")
            # response.raise_for_status()
            # return PredictorModelsResponse(**response.json())

        except httpx.HTTPError as e:
            logger.error(f"Failed to get available models: {e}")
            raise

    # ========== Convenience Methods ==========

    def get_median_prediction(
        self,
        model_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[float]:
        """
        Get median (p50) execution time prediction

        Convenience method that extracts the median prediction from the full
        quantile response.

        Args:
            model_type: Model identifier
            metadata: Optional task metadata

        Returns:
            float: Median predicted execution time in milliseconds, or None if prediction failed

        TODO: This method depends on predict() being implemented
        """
        response = self.predict(model_type, metadata)

        if response.status != "success":
            logger.warning(f"Prediction failed for {model_type}: {response.message}")
            return None

        if not response.quantiles or not response.quantile_predictions:
            logger.warning(f"No quantile data in response for {model_type}")
            return None

        # Find the median (0.5 quantile)
        try:
            median_idx = response.quantiles.index(0.5)
            return response.quantile_predictions[median_idx]
        except (ValueError, IndexError):
            logger.warning(f"Could not find median quantile for {model_type}")
            # Fallback: return middle value
            mid_idx = len(response.quantile_predictions) // 2
            return response.quantile_predictions[mid_idx]

    def get_prediction_range(
        self,
        model_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        confidence_level: float = 0.8
    ) -> Optional[tuple[float, float]]:
        """
        Get prediction range for given confidence level

        Returns the prediction range (min, max) that covers the specified
        confidence level (e.g., 80% confidence means 10th to 90th percentile).

        Args:
            model_type: Model identifier
            metadata: Optional task metadata
            confidence_level: Confidence level (0-1), default 0.8

        Returns:
            tuple[float, float]: (min_time, max_time) in milliseconds, or None if failed

        TODO: This method depends on predict() being implemented
        """
        response = self.predict(model_type, metadata)

        if response.status != "success" or not response.quantiles or not response.quantile_predictions:
            return None

        # Calculate quantile indices for confidence level
        lower_q = (1 - confidence_level) / 2
        upper_q = 1 - lower_q

        try:
            # Find closest quantiles
            lower_idx = min(range(len(response.quantiles)),
                          key=lambda i: abs(response.quantiles[i] - lower_q))
            upper_idx = min(range(len(response.quantiles)),
                          key=lambda i: abs(response.quantiles[i] - upper_q))

            return (
                response.quantile_predictions[lower_idx],
                response.quantile_predictions[upper_idx]
            )
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not calculate prediction range: {e}")
            return None

    def is_available(self) -> bool:
        """
        Check if Predictor service is available

        Returns:
            bool: True if service is healthy and reachable

        TODO: This method depends on health_check() being implemented
        """
        try:
            health = self.health_check()
            return health.status == "healthy"
        except Exception as e:
            logger.debug(f"Predictor service not available: {e}")
            return False
