"""
Predictor Client Unit Tests

Tests for PredictorClient interface and model validation.
Note: These tests verify the client interface, not the actual service integration
since the Predictor service is not yet implemented (TODO).
"""

import pytest
from src.scheduler.predictor_client import PredictorClient
from src.scheduler.models import (
    PredictorRequest,
    PredictorResponse,
    PredictorHealthResponse,
    PredictorModelsResponse
)


def test_predictor_request_model():
    """Test PredictorRequest model validation"""
    request = PredictorRequest(
        model_type="gpt-3.5-turbo",
        metadata={
            "hardware": "A100",
            "input_tokens": 100,
            "output_tokens": 50
        }
    )

    assert request.model_type == "gpt-3.5-turbo"
    assert request.metadata["hardware"] == "A100"
    assert request.metadata["input_tokens"] == 100


def test_predictor_request_minimal():
    """Test PredictorRequest with minimal data"""
    request = PredictorRequest(model_type="llama-7b")

    assert request.model_type == "llama-7b"
    assert request.metadata == {}


def test_predictor_response_success():
    """Test PredictorResponse success case"""
    response = PredictorResponse(
        status="success",
        model_type="gpt-3.5-turbo",
        quantiles=[0.1, 0.25, 0.5, 0.75, 0.9],
        quantile_predictions=[850.0, 1050.0, 1300.0, 1650.0, 2100.0],
        prediction_method="lookup",
        confidence=0.85
    )

    assert response.status == "success"
    assert response.model_type == "gpt-3.5-turbo"
    assert len(response.quantiles) == 5
    assert len(response.quantile_predictions) == 5
    assert response.quantile_predictions[2] == 1300.0  # Median
    assert response.confidence == 0.85


def test_predictor_response_error():
    """Test PredictorResponse error case"""
    response = PredictorResponse(
        status="error",
        message="Model not found"
    )

    assert response.status == "error"
    assert response.message == "Model not found"
    assert response.model_type is None
    assert response.quantiles is None


def test_predictor_client_initialization():
    """Test PredictorClient initialization"""
    client = PredictorClient("http://localhost:8200")

    assert client.base_url == "http://localhost:8200"
    assert client.timeout == 10.0

    client.close()


def test_predictor_client_custom_timeout():
    """Test PredictorClient with custom timeout"""
    client = PredictorClient("http://localhost:8200", timeout=30.0)

    assert client.timeout == 30.0

    client.close()


def test_predictor_client_context_manager():
    """Test PredictorClient as context manager"""
    with PredictorClient("http://localhost:8200") as client:
        assert client is not None
        assert isinstance(client, PredictorClient)

    # Client should be closed after context exit


def test_predictor_client_predict_interface():
    """
    Test PredictorClient.predict() interface

    Note: This returns a placeholder error response since the service
    is not implemented (TODO). This test verifies the interface works.
    """
    client = PredictorClient("http://localhost:8200")

    response = client.predict(
        model_type="gpt-3.5-turbo",
        metadata={"hardware": "A100"}
    )

    # Should return error response indicating service not implemented
    assert isinstance(response, PredictorResponse)
    assert response.status == "error"
    assert "not implemented" in response.message.lower()

    client.close()


def test_predictor_client_health_check_interface():
    """
    Test PredictorClient.health_check() interface

    Note: Returns placeholder response since service not implemented
    """
    client = PredictorClient("http://localhost:8200")

    response = client.health_check()

    # Should return unhealthy status since service not implemented
    assert isinstance(response, PredictorHealthResponse)
    assert response.status == "unhealthy"
    assert response.service == "predictor"

    client.close()


def test_predictor_client_get_available_models_interface():
    """
    Test PredictorClient.get_available_models() interface

    Note: Returns placeholder response since service not implemented
    """
    client = PredictorClient("http://localhost:8200")

    response = client.get_available_models()

    # Should return error response with empty models list
    assert isinstance(response, PredictorModelsResponse)
    assert response.status == "error"
    assert response.models == []

    client.close()


def test_predictor_client_get_median_prediction():
    """Test get_median_prediction convenience method"""
    client = PredictorClient("http://localhost:8200")

    # Should return None since service not implemented
    median = client.get_median_prediction("gpt-3.5-turbo")

    assert median is None

    client.close()


def test_predictor_client_get_prediction_range():
    """Test get_prediction_range convenience method"""
    client = PredictorClient("http://localhost:8200")

    # Should return None since service not implemented
    range_result = client.get_prediction_range("gpt-3.5-turbo")

    assert range_result is None

    client.close()


def test_predictor_client_is_available():
    """Test is_available convenience method"""
    client = PredictorClient("http://localhost:8200")

    # Should return False since service not implemented
    available = client.is_available()

    assert available is False

    client.close()


def test_predictor_health_response_model():
    """Test PredictorHealthResponse model"""
    response = PredictorHealthResponse(
        status="healthy",
        service="predictor",
        version="1.0.0",
        total_models=15
    )

    assert response.status == "healthy"
    assert response.service == "predictor"
    assert response.version == "1.0.0"
    assert response.total_models == 15


def test_predictor_models_response_model():
    """Test PredictorModelsResponse model"""
    response = PredictorModelsResponse(
        status="success",
        models=[
            {
                "model_type": "gpt-3.5-turbo",
                "model_name": "GPT-3.5 Turbo",
                "total_predictions": 1500,
                "hardware_types": ["A100", "V100"],
                "software_versions": ["vllm-0.2.0"]
            }
        ]
    )

    assert response.status == "success"
    assert len(response.models) == 1
    assert response.models[0].model_type == "gpt-3.5-turbo"
    assert response.models[0].total_predictions == 1500


def test_predictor_request_extensive_metadata():
    """Test PredictorRequest with extensive metadata"""
    request = PredictorRequest(
        model_type="gpt-4",
        metadata={
            "model_name": "gpt-4-0613",
            "hardware": "A100",
            "software_name": "vllm",
            "software_version": "0.2.1",
            "input_tokens": 1000,
            "output_tokens": 500,
            "batch_size": 8,
            "temperature": 0.7,
            "custom_field": "custom_value"
        }
    )

    assert request.model_type == "gpt-4"
    assert len(request.metadata) == 9
    assert request.metadata["input_tokens"] == 1000
    assert request.metadata["custom_field"] == "custom_value"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
