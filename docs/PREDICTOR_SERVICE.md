# Predictor Service

The Predictor Service provides execution time predictions for tasks based on model characteristics and historical data. It implements the API specification defined in [Predictor.md](../Predictor.md).

## Architecture

The Predictor Service consists of:

- **FastAPI Application** (`src/scheduler/predictor_api.py`) - REST API server
- **Predictor Client** (`src/scheduler/predictor_client.py`) - Python client for calling the service
- **Lookup Predictor** (`src/scheduler/predictor.py`) - Fast lookup-based prediction using pre-computed tables
- **Data Models** (`src/scheduler/models.py`) - Pydantic models for request/response validation

## Running the Service

### Start Predictor Service

```bash
# Run on default port 8200
uv run python -m src.scheduler.predictor_api

# Or use uvicorn directly with custom port
uv run uvicorn src.scheduler.predictor_api:app --host 0.0.0.0 --port 8200
```

### Environment Variables

- `DEFAULT_LOOKUP_TABLE`: Path to default lookup table JSON file (optional)

Example:
```bash
export DEFAULT_LOOKUP_TABLE=/path/to/predictions.json
uv run python -m src.scheduler.predictor_api
```

## API Endpoints

### Health Check

```bash
curl http://localhost:8200/health
```

Response:
```json
{
  "status": "healthy",
  "service": "predictor",
  "version": "1.0.0",
  "mode": "default",
  "lookup_predictor_loaded": false
}
```

### Get Available Models

```bash
curl http://localhost:8200/models
```

### Predict Single Task

```bash
curl -X POST "http://localhost:8200/predict/single/gpt-3.5/turbo/A100/vllm/0.1.0" \
  -H "Content-Type: application/json" \
  -d '{
    "trace": {...},
    "confidence_level": 0.95,
    "lookup_table": true,
    "lookup_table_name": "predictions.json"
  }'
```

### Predict Batch

```bash
curl -X POST "http://localhost:8200/predict/batch/gpt-3.5/turbo/A100/vllm/0.1.0" \
  -H "Content-Type: application/json" \
  -d '{
    "trace": [{...}, {...}],
    "confidence_level": 0.95
  }'
```

### Generate Lookup Table

```bash
curl -X POST "http://localhost:8200/predict/table/gpt-3.5/turbo/A100/vllm/0.1.0" \
  -F "trace_file=@traces.json" \
  -F "confidence_level=0.95"
```

### Train Model

```bash
curl -X POST http://localhost:8200/train \
  -H "Content-Type: application/json" \
  -d '{
    "config": {...}
  }'
```

## Using the Python Client

```python
from src.scheduler.predictor_client import PredictorClient

# Initialize client
predictor = PredictorClient(base_url="http://localhost:8200")

# Check if service is available
if predictor.is_available():
    print("Predictor service is ready")

# Make a prediction
response = predictor.predict(
    model_type="gpt-3.5-turbo",
    metadata={
        "hardware": "A100",
        "input_tokens": 100,
        "output_tokens": 50
    }
)

if response.status == "success":
    print(f"Predicted quantiles: {response.quantiles}")
    print(f"Predicted times: {response.quantile_predictions}")

    # Get median prediction
    median = predictor.get_median_prediction("gpt-3.5-turbo", metadata)
    print(f"Median execution time: {median}ms")

    # Get prediction range (80% confidence)
    min_time, max_time = predictor.get_prediction_range(
        "gpt-3.5-turbo",
        metadata,
        confidence_level=0.8
    )
    print(f"Expected range: {min_time}-{max_time}ms")
```

## Lookup Table Format

Lookup tables are JSON files containing pre-computed predictions:

```json
[
  {
    "status": "success",
    "model_type": "gpt-3.5-turbo",
    "quantiles": [0.25, 0.5, 0.75, 0.99],
    "quantile_predictions": [100.0, 150.0, 200.0, 500.0],
    "expect": 150.0,
    "error": 25.0,
    "model_info": {
      "type": "gpt-3.5-turbo",
      "name": "turbo",
      "hardware": "A100",
      "software_name": "vllm",
      "software_version": "0.1.0"
    }
  }
]
```

## Implementation Status

### Implemented ✅
- FastAPI application with all endpoints defined in Predictor.md
- Health check and service discovery
- Lookup table-based prediction (fast, pre-computed results)
- Python client with full API support
- Request/response data models with validation

### TODO 🔨
- **Model Training** (`/train` endpoint) - Needs ML pipeline integration
- **Default Prediction Mode** - Needs quantile regression model implementation
- **Lookup Table Generation** (`/predict/table`) - Needs trace parsing and batch prediction
- **Model Registry** - Dynamic model discovery and metadata management
- **Prediction Caching** - Cache frequently requested predictions
- **Metrics and Monitoring** - Track prediction accuracy and latency

## Integration with Scheduler

The Scheduler uses the Predictor service to estimate task execution times for scheduling decisions:

```python
from src.scheduler import SwarmPilotScheduler
from src.scheduler.predictor_client import PredictorClient

# Initialize scheduler with predictor
scheduler = SwarmPilotScheduler()
scheduler.predictor = PredictorClient("http://predictor-service:8200")

# Predictor is automatically used during task scheduling
# to estimate execution times for each TaskInstance
```

## Testing

```bash
# Test predictor client (requires service to be running)
uv run pytest tests/test_predictor_client.py -v

# Test predictor implementation
uv run pytest tests/ -v
```

## Architecture Diagram

```
┌─────────────┐
│  Scheduler  │
└──────┬──────┘
       │ HTTP
       ▼
┌─────────────────┐      ┌──────────────────┐
│ Predictor Client│─────▶│ Predictor Service│
└─────────────────┘      └────────┬─────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
            ┌──────────┐  ┌─────────────┐  ┌────────┐
            │  Lookup  │  │ ML Models   │  │ Cache  │
            │  Tables  │  │ (TODO)      │  │ (TODO) │
            └──────────┘  └─────────────┘  └────────┘
```

## See Also

- [Predictor.md](../Predictor.md) - Full API specification
- [Scheduler.md](Scheduler.md) - Scheduler API documentation
- [LOOKUP_PREDICTOR.md](LOOKUP_PREDICTOR.md) - Lookup predictor implementation details
