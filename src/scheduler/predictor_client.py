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

from math import e
from turtle import mode
import httpx
import os
from typing import Dict, Any, Optional, List
from loguru import logger
import json
import numpy as np

from .models import (
    PredictSingleRequest,
    PredictSingleResponse,
    PredictBatchRequest,
    PredictBatchResponse,
    PredictionResult,
    ModelInfo,
    PredictionSummary
)

def calculate_moments(p, q):
    """
    p: 分位数水平数组
    q: 对应的分位数值数组
    """
    # 内部区间的贡献（使用梯形法则）
    E_X = np.trapezoid(q, p)
    E_X2 = np.trapezoid(q**2, p)
    
    # 如果p不包含0和1，处理尾部
    if p[0] > 0:
        # 简单假设：左尾与第一个区间的斜率相同
        E_X += q[0] * p[0]
        E_X2 += q[0]**2 * p[0]
    
    if p[-1] < 1:
        # 简单假设：右尾与最后一个区间的斜率相同
        E_X += q[-1] * (1 - p[-1])
        E_X2 += q[-1]**2 * (1 - p[-1])
    
    variance = E_X2 - E_X**2
    std = np.sqrt(variance)
    
    return E_X, variance, std


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

    def __init__(self, base_url: str, timeout: float = 30.0, fake_data_bypass=False, fake_data_path=None):
        """
        Initialize Predictor client

        Args:
            base_url: Predictor service URL
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)
        
        # Fake predictor configuration
        self.use_fake_predictor = os.getenv("USE_FAKE_PREDICTOR", "false").lower() in ("true", "1", "yes")
        self.fake_predictor_url = os.getenv("FAKE_PREDICTOR_URL", "http://localhost:8200")
        
        if fake_data_bypass:
            assert fake_data_bypass, "When you want to use fake data, please set the path of the data"
            try:
                all_fake_data = os.listdir(fake_data_path)
                self.fake_data_mapping = {}
                self.fake_data_mapping_exp = {}
                self.fake_precentile = [0.01, 0.05, 0.10, 0.25, 0.40, 0.50, 0.60, 0.75, 0.90, 0.95, 0.98, 0.99, 0.995]

                
                for data_name in all_fake_data:
                    if not data_name.endswith(".json"):
                        continue
                    data_file_path = os.path.join(fake_data_path, data_name)
                    with open(data_file_path, 'r') as f:
                        fake_data = json.load(f)
                    model_name = data_name[:-5]
                    if model_name.endswith("_exp"):
                        self.fake_data_mapping_exp[model_name[:-4]] = fake_data
                    else:
                        self.fake_data_mapping[model_name] = fake_data
                    logger.info(f"Fake data of {model_name} is load from {data_name}")
                
                
                
                # Pre-compute statistics using fake_data_exp for expect/var/std
                # but keep quantile calculations from fake_data (quantile data)
                self.fake_data_statics = {}

                for (data_name, fake_data), (_, fake_data_exp) in zip(
                    self.fake_data_mapping.items(),
                    self.fake_data_mapping_exp.items()
                ):
                    if isinstance(fake_data, list):
                        # Calculate quantiles from fake_data (quantile distribution)
                        fake_data_val = [v for v in fake_data]
                        quantile_predictions = np.percentile(fake_data_val, [q * 100 for q in self.fake_precentile])

                        # Calculate expect/var/std from fake_data_exp (original samples)
                        fake_data_exp_val = np.array([v for v in fake_data_exp])
                        exp = float(np.mean(fake_data_exp_val))
                        var = float(np.var(fake_data_exp_val))
                        std = float(np.std(fake_data_exp_val))

                        self.fake_data_statics[data_name] = {
                            "quantile": quantile_predictions.tolist(),
                            "quantile_set": self.fake_precentile,
                            "expect": exp,
                            "variance": var,
                            "standard": std
                        }
                    elif isinstance(fake_data, dict):
                        cur_fake_data_statics = {}
                        all_fake_data_keyset = []
                        all_fake_data_lists = []
                        
                        for key, fake_data_list in fake_data.items():
                            # Calculate quantiles from fake_data (quantile distribution)
                            fake_data_val = [v for v in fake_data_list]
                            quantile_predictions = np.percentile(fake_data_val, [q * 100 for q in self.fake_precentile])

                            # Calculate expect/var/std from fake_data_exp (original samples)
                            fake_data_exp_val = np.array([v for v in fake_data_exp])
                            exp = float(np.mean(fake_data_exp_val))
                            var = float(np.var(fake_data_exp_val))
                            std = float(np.std(fake_data_exp_val))

                            # Convert key to float or tuple of floats for dictionary lookup
                            if isinstance(key, list):
                                new_key = tuple(int(v) for v in key)  # Multi-value keys as tuple
                            elif isinstance(key, str):
                                # Try to convert string keys to float
                                try:
                                    new_key = tuple(int(v) for v in key.split(','))
                                except ValueError:
                                    new_key = key  # Keep as string if not numeric
                            else:
                                new_key = float(key)

                            cur_fake_data_statics[new_key] = {
                                "quantile": quantile_predictions.tolist(),
                                "quantile_set": self.fake_precentile,
                                "expect": exp,
                                "variance": var,
                                "standard": std
                            }
                        self.fake_data_statics[data_name] = cur_fake_data_statics
                    else:
                        raise RuntimeError("Un-supported fake data format")
                        
                self.fake_data_enabled = True
            except Exception as e:
                logger.error(f"Cannot load fake data: {e}")
                exit(-1) # Cannot load fake data under fake data model, exit with error!
            logger.info("Fake data model enabled")
        else:
            self.fake_data_enabled = False

        if self.use_fake_predictor:
            logger.info(
                f"Initialized PredictorClient with base_url={self.base_url}, "
                f"fake_predictor_url={self.fake_predictor_url}, "
                f"use_fake_predictor=True"
            )
        else:
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
        
        if self.fake_data_enabled:
            # Bypass real predictor with fake data(pre-computed data)
            # Step 1: Extract real model name
            if model_name.startswith("fake_"):
                stripped_model_name = model_name[5:]
            else: 
                stripped_model_name = model_name
               
            
            # Step 2: Check if fake data exists
            if stripped_model_name in self.fake_data_mapping:
                # Step 3: Oh, we have fake data, let's go
                cur_model_statics = self.fake_data_statics.get(stripped_model_name)
                target_statics = None
                if cur_model_statics:
                    # Check if this is a statistics dict (list format model) or feature-keyed dict
                    if isinstance(cur_model_statics, dict) and "quantile" in cur_model_statics:
                        # This is simple list format - statistics are directly available
                        target_statics = cur_model_statics
                    elif isinstance(cur_model_statics, dict):
                        # This is dict format with feature keys - need to lookup by input_feature
                        # Parse input_feature as list of dicts
                        input_feature = trace.get('input_feature', [])
                        if isinstance(input_feature, dict):
                            # Handle dict format: {"param_name": value, ...}
                            key = [float(v) for v in input_feature.values()]
                        elif isinstance(input_feature, list):
                            # Handle list format: [{"param_name": "...", "val": value}, ...]
                            key = [float(item['val']) for item in input_feature]
                        else:
                            key = []

                        # Convert to appropriate key type for dictionary lookup
                        if len(key) == 1:
                            lookup_key = key[0]
                        elif len(key) > 1:
                            lookup_key = tuple(key)  # Multi-value keys must be tuples
                        else:
                            lookup_key = None

                        target_statics = cur_model_statics.get(lookup_key) if lookup_key is not None else None
                        if target_statics is None:
                            logger.warning(f"Warning: No fake data for key {key} in model {stripped_model_name}, fallback to external predictor")
                        else:
                            logger.debug(f"Using fake data for model {stripped_model_name} with key {key}")

                    # Return fake data result immediately
                    if target_statics:
                        logger.info(f"Fake data bypass: returning pre-computed stats for {stripped_model_name}")

                        # Construct ModelInfo
                        model_info = ModelInfo(
                            type=model_type,
                            name=model_name,
                            hardware=hardware,
                            software_name=software_name,
                            software_version=software_version
                        )

                        # Construct PredictionResult
                        prediction_result = PredictionResult(
                            status="success",
                            quantile_predictions=target_statics["quantile"],
                            quantiles=target_statics["quantile_set"],
                            model_info=model_info,
                            expect=target_statics["expect"],
                            error=target_statics["standard"]
                        )

                        # Construct PredictionSummary
                        prediction_summary = PredictionSummary(
                            total=1,
                            success=1,
                            failed=0,
                            confidence_level=confidence_level,
                            duration_seconds=0.0  # Fake data is instant
                        )

                        # Return complete response
                        return PredictSingleResponse(
                            summary=prediction_summary,
                            results=prediction_result
                        )
                else:
                    logger.warning(f"Warning: No fake data for model {stripped_model_name}, fallback to external predictor")
            else:
                logger.warning(f"Warning: No fake data for model {stripped_model_name}, fallback to external predictor")
        
        # Build request body
        request_body = PredictSingleRequest(
            trace=trace,
            confidence_level=confidence_level,
            lookup_table=lookup_table,
            lookup_table_name=lookup_table_name
        )

        # Check if we should route to fake predictor
        if self.use_fake_predictor and model_name.startswith("fake_"):
            # Strip fake_ prefix from model name
            stripped_model_name = model_name[5:]  # Remove "fake_"
            # Use fake predictor URL pattern
            url = f"{self.fake_predictor_url}/predict/single/fake/{stripped_model_name}/fake/fake/fake"
            logger.debug(f"Routing to fake predictor: {url}")
        else:
            # Build URL with path parameters for normal predictor
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

    def get_fake_percentiles(self) -> Optional[List[float]]:
        """
        Get the percentiles used in fake data mode

        Returns:
            List[float]: List of percentile values if fake data mode is enabled, None otherwise
        """
        if self.fake_data_enabled and hasattr(self, 'fake_precentile'):
            return self.fake_precentile
        return None

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
        # Use model_type parameter as default model_name if not in metadata
        model_name = metadata.get("model_name") or model_type
        extracted_model_type = metadata.get("model_type") or model_type
        hardware = metadata.get("hardware")
        software_name = metadata.get("software_name")
        software_version = metadata.get("software_version")

        # For models with fake_ prefix, automatically set hardware, software_name, and software_version to "fake"
        if model_name and model_name.startswith("fake_"):
            hardware = "fake"
            software_name = "fake"
            software_version = "fake"
            logger.debug(
                f"Model {model_name} has fake_ prefix, "
                f"automatically setting hardware=fake, software_name=fake, software_version=fake"
            )

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
        if "pixel_num" in metadata:
            input_features.append({"param_name": "pixel_num", "val": metadata["pixel_num"]})
        if "duration" in metadata:
            input_features.append({"param_name": "duration", "val": metadata["duration"]})

        # Add any other numeric features
        skip_keys = {"model_name", "hardware", "software_name", "software_version",
                     "input_tokens", "output_tokens", "batch_size", "server_time_cost",
                     "confidence_level", "lookup_table", "lookup_table_name", "pixel_num", "duration", "is_warmup"}

        for key, value in metadata.items():
            if key not in skip_keys and isinstance(value, (int, float)):
                input_features.append({"param_name": key, "val": value})

        # Build trace object with model_id for proper model type detection
        trace = {"input_feature": input_features, "model_id": model_name} if input_features else {"model_id": model_name}
        logger.info(f"feature: {trace}")
        # Extract optional parameters
        confidence_level = metadata.get("confidence_level", 0.95)
        lookup_table = metadata.get("lookup_table", False)
        lookup_table_name = metadata.get("lookup_table_name")

        # Call predict_single
        return self.predict_single(
            model_type=extracted_model_type,
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
