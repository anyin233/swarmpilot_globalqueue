"""
Predictor Service FastAPI Application

Implements all API endpoints defined in Predictor.md for execution time prediction.
This service provides:
- Model training
- Single task prediction
- Batch prediction
- Lookup table generation
"""

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from typing import Dict, Any, List
from loguru import logger
import time
import os
from pathlib import Path

from .models import (
    TrainRequest, TrainResponse,
    PredictSingleRequest, PredictSingleResponse,
    PredictBatchRequest, PredictBatchResponse,
    PredictTableRequest, PredictTableResponse,
    PredictionSummary, PredictionResult, ModelInfo,
    PredictorModelsResponse, PredictorModelInfo
)
from .predictor import LookupPredictor


# Initialize FastAPI app
app = FastAPI(
    title="SwarmPilot Predictor",
    description="Task execution time prediction service",
    version="1.0.0"
)

# Global predictor instance (can be switched between modes)
predictor_instance: Dict[str, Any] = {
    "mode": "default",  # "default" or "lookup_table"
    "lookup_predictor": None
}


@app.get("/health")
async def health_check():
    """
    Health check endpoint

    Returns service health status and available prediction methods
    """
    return {
        "status": "healthy",
        "service": "predictor",
        "version": "1.0.0",
        "mode": predictor_instance["mode"],
        "lookup_predictor_loaded": predictor_instance["lookup_predictor"] is not None
    }


@app.get("/models", response_model=PredictorModelsResponse)
async def get_available_models():
    """
    Get list of available models for prediction

    Returns information about all models that can be used for prediction,
    including their supported hardware and software configurations.
    """
    try:
        # TODO: Implement actual model discovery
        # This would typically involve:
        # 1. Scan model registry
        # 2. Load model metadata
        # 3. Return available models with their configurations

        # If lookup predictor is loaded, get stats from it
        models = []
        if predictor_instance["lookup_predictor"]:
            stats = predictor_instance["lookup_predictor"].get_stats()
            for model_type in stats.get("model_types", []):
                models.append(
                    PredictorModelInfo(
                        model_type=model_type,
                        model_name=model_type,
                        total_predictions=stats["successful_records"],
                        hardware_types=[],
                        software_versions=[]
                    )
                )

        return PredictorModelsResponse(
            status="success",
            models=models
        )

    except Exception as e:
        logger.error(f"Failed to get available models: {e}")
        return PredictorModelsResponse(
            status="error",
            models=[]
        )


@app.post("/train", response_model=TrainResponse)
async def train_model(request: TrainRequest):
    """
    Train quantile execution time prediction model

    Args:
        request: Training request with configuration

    Returns:
        Training result with model key and metrics

    Note: This is a stub implementation. Full training logic needs to be implemented
          based on your specific ML framework and training pipeline.
    """
    try:
        start_time = time.time()

        logger.info("Received training request")

        # TODO: Implement actual model training logic
        # This would typically involve:
        # 1. Parse training config
        # 2. Load training data
        # 3. Train quantile regression model
        # 4. Save trained model
        # 5. Return model key and metrics

        duration = int(time.time() - start_time)

        return TrainResponse(
            status="error",
            model_key=None,
            metrics=None,
            duration_seconds=duration
        )

    except Exception as e:
        logger.error(f"Training failed: {e}")
        return TrainResponse(
            status="error",
            model_key=None,
            metrics={"error": str(e)},
            duration_seconds=0
        )


@app.post(
    "/predict/single/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}",
    response_model=PredictSingleResponse
)
async def predict_single(
    model_type: str,
    model_name: str,
    hardware: str,
    software_name: str,
    software_version: str,
    request: PredictSingleRequest
):
    """
    Predict execution time distribution for a single task

    Args:
        model_type: Model type identifier
        model_name: Model name
        hardware: Hardware configuration
        software_name: Software framework name
        software_version: Software version
        request: Prediction request with trace and settings

    Returns:
        Prediction result with quantiles and statistics
    """
    try:
        start_time = time.time()

        logger.info(
            f"Single prediction request: model_type={model_type}, "
            f"hardware={hardware}, lookup_table={request.lookup_table}"
        )

        # Use lookup table if requested and available
        if request.lookup_table and request.lookup_table_name:
            if predictor_instance["lookup_predictor"] is None:
                # Try to load the lookup table
                table_path = f"lookup_tables/{request.lookup_table_name}"
                if os.path.exists(table_path):
                    predictor_instance["lookup_predictor"] = LookupPredictor(table_path)

            if predictor_instance["lookup_predictor"]:
                # Perform lookup prediction
                metadata = {
                    "model_name": model_name,
                    "hardware": hardware,
                    "software_name": software_name,
                    "software_version": software_version
                }

                prediction = predictor_instance["lookup_predictor"].predict(
                    model_type=model_type,
                    metadata=metadata
                )

                if prediction:
                    duration = int(time.time() - start_time)

                    # Extract quantiles and predictions
                    quantiles = prediction.get("quantiles", [])
                    quantile_predictions = prediction.get("quantile_predictions", [])

                    # Calculate expectation and error
                    expect = prediction.get("expect", sum(quantile_predictions) / len(quantile_predictions) if quantile_predictions else 0)
                    error = prediction.get("error", 0)

                    model_info = ModelInfo(
                        type=model_type,
                        name=model_name,
                        hardware=hardware,
                        software_name=software_name,
                        software_version=software_version
                    )

                    result = PredictionResult(
                        status="success",
                        quantile_predictions=quantile_predictions,
                        quantiles=quantiles,
                        model_info=model_info,
                        expect=expect,
                        error=error
                    )

                    summary = PredictionSummary(
                        total=1,
                        success=1,
                        failed=0,
                        confidence_level=request.confidence_level,
                        duration_seconds=duration
                    )

                    return PredictSingleResponse(
                        summary=summary,
                        results=result
                    )

        # TODO: Implement default prediction using ML model
        # This would involve:
        # 1. Load appropriate quantile regression model
        # 2. Extract features from trace
        # 3. Perform prediction
        # 4. Calculate expectation and error from quantiles

        duration = int(time.time() - start_time)

        # Return error response for now
        result = PredictionResult(
            status="error",
            quantile_predictions=None,
            quantiles=None,
            model_info=None,
            expect=None,
            error=None
        )

        summary = PredictionSummary(
            total=1,
            success=0,
            failed=1,
            confidence_level=request.confidence_level,
            duration_seconds=duration
        )

        return PredictSingleResponse(
            summary=summary,
            results=result
        )

    except Exception as e:
        logger.error(f"Single prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/predict/batch/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}",
    response_model=PredictBatchResponse
)
async def predict_batch(
    model_type: str,
    model_name: str,
    hardware: str,
    software_name: str,
    software_version: str,
    request: PredictBatchRequest
):
    """
    Batch predict execution time distributions for multiple tasks

    Args:
        model_type: Model type identifier
        model_name: Model name
        hardware: Hardware configuration
        software_name: Software framework name
        software_version: Software version
        request: Batch prediction request with list of traces

    Returns:
        Batch prediction results with statistics
    """
    try:
        start_time = time.time()

        logger.info(
            f"Batch prediction request: model_type={model_type}, "
            f"hardware={hardware}, num_traces={len(request.trace)}"
        )

        results = []
        total_expect = 0.0
        total_error_sq = 0.0
        success_count = 0
        failed_count = 0

        # Use lookup table if requested and available
        if request.lookup_table and request.lookup_table_name:
            if predictor_instance["lookup_predictor"] is None:
                table_path = f"lookup_tables/{request.lookup_table_name}"
                if os.path.exists(table_path):
                    predictor_instance["lookup_predictor"] = LookupPredictor(table_path)

            if predictor_instance["lookup_predictor"]:
                metadata = {
                    "model_name": model_name,
                    "hardware": hardware,
                    "software_name": software_name,
                    "software_version": software_version
                }

                for trace_item in request.trace:
                    prediction = predictor_instance["lookup_predictor"].predict(
                        model_type=model_type,
                        metadata=metadata
                    )

                    if prediction:
                        quantiles = prediction.get("quantiles", [])
                        quantile_predictions = prediction.get("quantile_predictions", [])
                        expect = prediction.get("expect", sum(quantile_predictions) / len(quantile_predictions) if quantile_predictions else 0)
                        error = prediction.get("error", 0)

                        model_info = ModelInfo(
                            type=model_type,
                            name=model_name,
                            hardware=hardware,
                            software_name=software_name,
                            software_version=software_version
                        )

                        result = PredictionResult(
                            status="success",
                            quantile_predictions=quantile_predictions,
                            quantiles=quantiles,
                            model_info=model_info,
                            expect=expect,
                            error=error
                        )

                        results.append(result)
                        total_expect += expect
                        total_error_sq += error ** 2
                        success_count += 1
                    else:
                        result = PredictionResult(
                            status="error",
                            quantile_predictions=None,
                            quantiles=None,
                            model_info=None,
                            expect=None,
                            error=None
                        )
                        results.append(result)
                        failed_count += 1

        # TODO: Implement default batch prediction using ML model

        duration = int(time.time() - start_time)

        # Calculate total error (using error propagation formula)
        import math
        total_error = math.sqrt(total_error_sq) if success_count > 0 else 0.0

        summary = PredictionSummary(
            total=len(request.trace),
            success=success_count,
            failed=failed_count,
            confidence_level=request.confidence_level,
            duration_seconds=duration
        )

        return PredictBatchResponse(
            summary=summary,
            results=results,
            expect=total_expect,
            error=total_error
        )

    except Exception as e:
        logger.error(f"Batch prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/predict/table/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}",
    response_model=PredictTableResponse
)
async def generate_lookup_table(
    model_type: str,
    model_name: str,
    hardware: str,
    software_name: str,
    software_version: str,
    trace_file: UploadFile = File(...),
    confidence_level: float = 0.95
):
    """
    Generate a lookup table from trace file

    Args:
        model_type: Model type identifier
        model_name: Model name
        hardware: Hardware configuration
        software_name: Software framework name
        software_version: Software version
        trace_file: Uploaded trace file
        confidence_level: Confidence level for predictions

    Returns:
        Path to generated lookup table

    Note: This is a stub implementation. Full lookup table generation
          needs to be implemented based on your prediction pipeline.
    """
    try:
        logger.info(
            f"Lookup table generation request: model_type={model_type}, "
            f"hardware={hardware}, file={trace_file.filename}"
        )

        # TODO: Implement actual lookup table generation
        # This would typically involve:
        # 1. Parse trace file
        # 2. For each trace, perform prediction
        # 3. Save results to CSV lookup table
        # 4. Return path to saved table

        # Create lookup_tables directory if it doesn't exist
        os.makedirs("lookup_tables", exist_ok=True)

        # Generate output filename
        output_filename = (
            f"{model_type}_{model_name}_{hardware}_"
            f"{software_name}_{software_version}_lookup.csv"
        )
        output_path = f"lookup_tables/{output_filename}"

        # For now, return error
        return PredictTableResponse(
            status="failed",
            path=None
        )

    except Exception as e:
        logger.error(f"Lookup table generation failed: {e}")
        return PredictTableResponse(
            status="failed",
            path=None
        )


@app.on_event("startup")
async def startup_event():
    """Initialize predictor service"""
    logger.info("Starting SwarmPilot Predictor v1.0...")

    # Load default lookup table if configured
    default_lookup_table = os.environ.get("DEFAULT_LOOKUP_TABLE")
    if default_lookup_table and os.path.exists(default_lookup_table):
        try:
            predictor_instance["lookup_predictor"] = LookupPredictor(default_lookup_table)
            predictor_instance["mode"] = "lookup_table"
            logger.info(f"Loaded default lookup table from {default_lookup_table}")
        except Exception as e:
            logger.error(f"Failed to load default lookup table: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8200)
