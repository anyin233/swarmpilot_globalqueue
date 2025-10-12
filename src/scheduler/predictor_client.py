"""
Predictor Service Client

Client for interacting with the Predictor service to obtain execution time predictions.
The Predictor service provides quantile-based predictions for task execution times
based on model type and task metadata.

API Specification:
    The Predictor service uses the following endpoint structure:
    - Single prediction: POST /predict/single/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}
    - Batch prediction: POST /predict/batch/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}
    - Health check: GET /health

Usage:
    predictor = PredictorClient(base_url="http://predictor:8200")
    response = predictor.predict_single(
        model_type="llm",
        model_name="gpt-3.5-turbo",
        hardware="A100",
        software_name="vllm",
        software_version="0.2.0",
        trace={"input_feature": [{"param_name": "input_tokens", "val": 100}]},
        confidence_level=0.95
    )
"""

import httpx
from typing import Dict, Any, Optional, List
from loguru import logger

from .models import (
    PredictSingleRequest,
    PredictSingleResponse,
    PredictBatchRequest,
    PredictBatchResponse,
    PredictionResult
)


class PredictorClient:
    """
    Client for Predictor service API

    The Predictor service provides execution time predictions based on:
    - Model type, name, hardware, software configuration
    - Task trace data (input features, hardware info, etc.)

    The service returns quantile-based predictions with expected value and error
    that can be used for scheduling decisions and queue time estimation.

    Args:
        base_url: Predictor service URL (e.g., "http://predictor-service:8101")
        timeout: Request timeout in seconds (default: 30.0)

    Example:
        >>> predictor = PredictorClient("http://localhost:8101")
        >>> response = predictor.predict_single(
        ...     model_type="llm",
        ...     model_name="gpt-3.5-turbo",
        ...     hardware="A100",
        ...     software_name="vllm",
        ...     software_version="0.2.0",
        ...     trace={"input_feature": [{"param_name": "input_tokens", "val": 100}]},
        ...     confidence_level=0.95
        ... )
        >>> if response.results.status == "success":
        ...     print(f"Expected time: {response.results.expect}ms")
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
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

    def predict_single(
        self,
        model_type: str,
        model_name: str,
        hardware: str,
        software_name: str,
        software_version: str,
        trace: Dict[str, Any],
        confidence_level: float = 0.95,
        lookup_table: bool = False,
        lookup_table_name: Optional[str] = None
    ) -> PredictSingleResponse:
        """
        Request execution time prediction for a single task from Predictor service

        Args:
            model_type: Model type identifier (e.g., 'ocr', 'llm', 'flux')
            model_name: Model name (e.g., 'gpt-3.5-turbo', 'llama-7b')
            hardware: Hardware identifier (e.g., 'A100', 'V100', 'cpu')
            software_name: Framework name (e.g., 'vllm', 'pytorch')
            software_version: Framework version (e.g., '0.2.0', '2.0.0')
            trace: Trace object containing task information. Should include:
                   - input_feature: List of input features, e.g.,
                     [{"param_name": "input_tokens", "val": 100}]
                   - hardware_info: Optional hardware info dict
                   - model_id: Optional model identifier
                   - duration_ms: Optional actual duration (for training data)
            confidence_level: Confidence level for prediction (default: 0.95)
            lookup_table: Whether to use lookup table for faster predictions
            lookup_table_name: Name of lookup table to use (required if lookup_table=True)

        Returns:
            PredictSingleResponse: Prediction result with summary and results

        Example:
            >>> response = predictor.predict_single(
            ...     model_type="llm",
            ...     model_name="gpt-3.5-turbo",
            ...     hardware="A100",
            ...     software_name="vllm",
            ...     software_version="0.2.0",
            ...     trace={
            ...         "input_feature": [
            ...             {"param_name": "input_tokens", "val": 100},
            ...             {"param_name": "output_tokens", "val": 50}
            ...         ]
            ...     },
            ...     confidence_level=0.95
            ... )
            >>> if response.results.status == "success":
            ...     print(f"Expected time: {response.results.expect}ms ± {response.results.error}ms")
        """
        # Build request body
        request_body = PredictSingleRequest(
            trace=trace,
            confidence_level=confidence_level,
            lookup_table=lookup_table,
            lookup_table_name=lookup_table_name
        )

        # Build URL with path parameters
        url = (
            f"{self.base_url}/predict/single/{model_type}/{model_name}/"
            f"{hardware}/{software_name}/{software_version}"
        )

        try:
            response = self.client.post(
                url,
                json=request_body.model_dump(exclude_none=True)
            )
            response.raise_for_status()
            return PredictSingleResponse(**response.json())

        except httpx.HTTPStatusError as e:
            logger.error(f"Predictor request failed with status {e.response.status_code}: {e}")
            # Try to parse error response
            try:
                error_data = e.response.json()
                logger.error(f"Error details: {error_data}")
            except Exception:
                pass
            raise
        except httpx.HTTPError as e:
            logger.error(f"Predictor HTTP request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in predictor request: {e}")
            raise

    # ========== Service Management API ==========

    def health_check(self) -> Dict[str, str]:
        """
        Check if Predictor service is healthy

        Returns:
            dict: Health status response with {"status": "ok"}

        Raises:
            httpx.HTTPError: HTTP request failed
        """
        try:
            response = self.client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            logger.error(f"Predictor health check failed: {e}")
            raise

    def is_available(self) -> bool:
        """
        Check if Predictor service is available

        Returns:
            bool: True if service is healthy and reachable
        """
        try:
            health = self.health_check()
            return health.get("status") == "ok"
        except Exception as e:
            logger.debug(f"Predictor service not available: {e}")
            return False

    # ========== Backward Compatibility ==========

    def predict(
        self,
        model_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> PredictSingleResponse:
        """
        Backward-compatible prediction method

        This method extracts the required parameters from metadata and calls predict_single().
        It's provided for backward compatibility with existing code.

        Args:
            model_type: Model type identifier (used as model_name if not in metadata)
            metadata: Metadata dict that should contain:
                - model_name: Optional, defaults to model_type
                - hardware: Required, e.g., 'A100', 'V100', 'cpu'
                - software_name: Required, e.g., 'vllm', 'pytorch'
                - software_version: Required, e.g., '0.2.0'
                - input_tokens: Optional input token count
                - output_tokens: Optional output token count
                - Any other fields will be passed in trace.input_feature

        Returns:
            PredictSingleResponse: Prediction result

        Raises:
            ValueError: If required fields are missing from metadata

        Example:
            >>> response = predictor.predict(
            ...     "gpt-3.5-turbo",
            ...     {
            ...         "hardware": "A100",
            ...         "software_name": "vllm",
            ...         "software_version": "0.2.0",
            ...         "input_tokens": 100
            ...     }
            ... )
        """
        metadata = metadata or {}

        # Extract required parameters from metadata
        model_name = metadata.get("model_name")
        model_type = metadata.get("model_type")
        hardware = metadata.get("hardware")
        software_name = metadata.get("software_name")
        software_version = metadata.get("software_version")

        # Validate required fields
        if not hardware:
            raise ValueError("metadata must contain 'hardware' field")
        if not software_name:
            raise ValueError("metadata must contain 'software_name' field")
        if not software_version:
            raise ValueError("metadata must contain 'software_version' field")

        # Build trace object from metadata
        input_features = []

        # Add common features
        if "input_tokens" in metadata:
            input_features.append({"param_name": "input_tokens", "val": metadata["input_tokens"]})
        if "output_tokens" in metadata:
            input_features.append({"param_name": "output_tokens", "val": metadata["output_tokens"]})
        if "batch_size" in metadata:
            input_features.append({"param_name": "batch_size", "val": metadata["batch_size"]})

        # Add any other numeric features
        skip_keys = {"model_name", "hardware", "software_name", "software_version",
                     "input_tokens", "output_tokens", "batch_size", "server_time_cost",
                     "confidence_level", "lookup_table", "lookup_table_name"}

        for key, value in metadata.items():
            if key not in skip_keys and isinstance(value, (int, float)):
                input_features.append({"param_name": key, "val": value})

        # Build trace object with model_id for proper model type detection
        trace = {"input_feature": input_features, "model_id": model_name} if input_features else {"model_id": model_name}

        # Extract optional parameters
        confidence_level = metadata.get("confidence_level", 0.95)
        lookup_table = metadata.get("lookup_table", False)
        lookup_table_name = metadata.get("lookup_table_name")

        # Call predict_single
        return self.predict_single(
            model_type=model_type,
            model_name=model_name,
            hardware=hardware,
            software_name=software_name,
            software_version=software_version,
            trace=trace,
            confidence_level=confidence_level,
            lookup_table=lookup_table,
            lookup_table_name=lookup_table_name
        )

    # ========== Convenience Methods ==========

    def get_expected_time(
        self,
        model_type: str,
        model_name: str,
        hardware: str,
        software_name: str,
        software_version: str,
        trace: Dict[str, Any],
        confidence_level: float = 0.95,
        lookup_table: bool = False,
        lookup_table_name: Optional[str] = None
    ) -> Optional[tuple[float, float]]:
        """
        Get expected execution time and error from prediction

        Convenience method that extracts the expected time (mean) and error (std deviation)
        from the prediction response.

        Args:
            model_type: Model type identifier
            model_name: Model name
            hardware: Hardware identifier
            software_name: Framework name
            software_version: Framework version
            trace: Trace object containing task information
            confidence_level: Confidence level for prediction (default: 0.95)
            lookup_table: Whether to use lookup table
            lookup_table_name: Name of lookup table to use

        Returns:
            tuple[float, float]: (expect, error) in milliseconds, or None if prediction failed
                - expect: Expected execution time (mean)
                - error: Standard deviation of execution time

        Example:
            >>> result = predictor.get_expected_time(
            ...     "llm", "gpt-3.5-turbo", "A100", "vllm", "0.2.0",
            ...     {"input_feature": [{"param_name": "input_tokens", "val": 100}]}
            ... )
            >>> if result:
            ...     expect, error = result
            ...     print(f"Expected: {expect}ms ± {error}ms")
        """
        try:
            response = self.predict_single(
                model_type=model_type,
                model_name=model_name,
                hardware=hardware,
                software_name=software_name,
                software_version=software_version,
                trace=trace,
                confidence_level=confidence_level,
                lookup_table=lookup_table,
                lookup_table_name=lookup_table_name
            )

            if response.results.status != "success":
                logger.warning(f"Prediction failed: {response.results.status}")
                return None

            if response.results.expect is None or response.results.error is None:
                logger.warning("Prediction response missing expect or error fields")
                return None

            return (response.results.expect, response.results.error)

        except Exception as e:
            logger.error(f"Failed to get expected time: {e}")
            return None
