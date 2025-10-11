# Lookup-Based Predictor

This document describes the lookup-based predictor feature that simplifies prediction by using a pre-computed lookup table instead of calling the Predictor API.

## Overview

The lookup-based predictor provides a fast, table-driven prediction mechanism that:
- Reads pre-computed predictions from a JSON file
- Matches tasks to predictions based on model type
- Randomly selects from multiple matching predictions
- Eliminates network latency from Predictor API calls
- Simplifies testing and experimentation

## Architecture

```
┌─────────────────┐
│   Scheduler     │
│                 │
│  ┌───────────┐  │
│  │ Strategy  │  │
│  └─────┬─────┘  │
│        │        │
│        ├────────┼──> Lookup Predictor ──> pred.json
│        │        │         (Fast)
│        │        │
│        └────────┼──> API Predictor ──> Predictor Service
│                 │         (Network)
└─────────────────┘
```

## Usage

### 1. Enable Lookup Predictor

When creating a `ShortestQueueStrategy`, set `use_lookup_predictor=True`:

```python
from scheduler import SwarmPilotScheduler
from strategy_refactored import ShortestQueueStrategy

scheduler = SwarmPilotScheduler()

# Use lookup predictor
strategy = ShortestQueueStrategy(
    taskinstances=scheduler.taskinstances,
    use_lookup_predictor=True,  # Enable lookup mode
    prediction_file="/path/to/pred.json"  # Path to prediction file
)

scheduler.strategy = strategy
```

### 2. Use API Predictor (Default)

To use the traditional API-based predictor:

```python
strategy = ShortestQueueStrategy(
    taskinstances=scheduler.taskinstances,
    use_lookup_predictor=False,  # Use API mode (default)
    predictor_url="http://localhost:8100",
    predictor_timeout=10.0
)
```

### 3. Prediction File Format

The prediction file should be a JSON array containing prediction records:

```json
[
  {
    "status": "success",
    "quantile_predictions": [182.61, 209.48, 248.25, 987.97],
    "quantiles": [0.25, 0.5, 0.75, 0.99],
    "model_info": {
      "type": "rec.rec.recmodel.ocrrecognize",
      "name": "tx_rec_dummy",
      "hardware": "TX",
      "software_name": "rec.rec.RecModel.OcrRecognize",
      "software_version": "0.0.1"
    },
    "model_type": "tx_rec_dummy",
    "task_id": "...",
    "req_id": "..."
  },
  {
    "status": "success",
    "quantile_predictions": [100.0, 150.0, 200.0, 500.0],
    "quantiles": [0.25, 0.5, 0.75, 0.99],
    "model_type": "tx_det_dummy",
    "model_info": { ... }
  }
]
```

**Required Fields:**
- `status`: Must be "success" (failed predictions are skipped)
- `quantile_predictions`: Array of predicted execution times (in ms)
- `quantiles`: Array of quantile levels (typically [0.25, 0.5, 0.75, 0.99])
- `model_type` or `model_info.type`: Model identifier for matching

## Matching Logic

The lookup predictor matches tasks to predictions using:

1. **Primary Match**: `model_type` field
   ```python
   model_type="tx_rec_dummy"  # Matches records with model_type="tx_rec_dummy"
   ```

2. **Secondary Match**: `model_info.type` field
   ```python
   model_type="rec.rec.recmodel.ocrrecognize"  # Matches model_info.type
   ```

3. **Additional Filtering** (if metadata provided):
   - `model_name`: Matches `model_info.name`
   - `hardware`: Matches `model_info.hardware`
   - `software_name`: Matches `model_info.software_name`
   - `software_version`: Matches `model_info.software_version`

### Example Matching

```python
# Request
request = SelectionRequest(
    model_type="tx_rec_dummy",
    metadata={
        "model_name": "tx_rec_dummy",
        "hardware": "TX"
    }
)

# Matches prediction records where:
# - model_type == "tx_rec_dummy" OR model_info.type == "tx_rec_dummy"
# - AND model_info.name == "tx_rec_dummy" (if present in metadata)
# - AND model_info.hardware == "TX" (if present in metadata)
```

## Random Selection

When multiple predictions match the criteria, one is randomly selected:

```python
# If 5 predictions match the model_type
# One will be randomly selected each time
prediction = lookup_predictor.predict(model_type="tx_rec_dummy", metadata={})
```

This provides variability in predictions similar to real-world execution time variation.

## Performance Benefits

| Feature | API Predictor | Lookup Predictor |
|---------|---------------|------------------|
| Latency | 10-100ms (network) | <1ms (local) |
| Requires Service | Yes (Predictor API) | No |
| Scalability | Limited by API | Unlimited |
| Offline Support | No | Yes |
| Deterministic | No | Pseudo-random |

## Configuration

### Scheduler Configuration

```python
# scheduler.py or scheduler_api.py
from strategy_refactored import ShortestQueueStrategy

strategy = ShortestQueueStrategy(
    taskinstances=taskinstances,
    use_lookup_predictor=True,
    prediction_file="/home/yanweiye/Project/swarmpilot/swarmpilot_taskinstance/pred.json"
)
```

### Environment Variable (Optional)

```bash
# Set prediction file path via environment
export PREDICTION_FILE="/path/to/custom/pred.json"
```

```python
import os
prediction_file = os.getenv("PREDICTION_FILE", "/default/path/pred.json")
strategy = ShortestQueueStrategy(
    taskinstances=taskinstances,
    use_lookup_predictor=True,
    prediction_file=prediction_file
)
```

## Statistics

Get statistics about loaded predictions:

```python
stats = lookup_predictor.get_stats()

print(f"Total records: {stats['total_records']}")
print(f"Successful records: {stats['successful_records']}")
print(f"Model types: {stats['model_types']}")

# Output:
# Total records: 1500
# Successful records: 1450
# Model types: ['tx_rec_dummy', 'tx_det_dummy', 'tx_text_match_dummy']
```

## Testing

Run the lookup predictor tests:

```bash
cd swarmpilot_globalqueue
uv run pytest tests/test_lookup_predictor.py -v
```

Expected output:
```
tests/test_lookup_predictor.py::TestLookupPredictor::test_load_predictions PASSED
tests/test_lookup_predictor.py::TestLookupPredictor::test_get_stats PASSED
tests/test_lookup_predictor.py::TestLookupPredictor::test_predict_by_model_type PASSED
...
9 passed in 0.15s
```

## Troubleshooting

### No predictions loaded

```
WARNING: Prediction file not found: /path/to/pred.json
```

**Solution**: Verify the file path exists and is accessible.

### No matching predictions

```
WARNING: No prediction found in lookup table for model_type=unknown_model
```

**Solution**:
1. Check that the model_type exists in the prediction file
2. Verify the prediction file contains successful records
3. Use `get_stats()` to see available model types

### All predictions skipped

```
WARNING: No predictions loaded, cannot perform lookup
```

**Solution**: Ensure prediction records have `status="success"` and required fields.

## Migration Guide

### From API Predictor to Lookup Predictor

1. **Generate prediction file** from existing Predictor API calls:
   ```bash
   # Export predictions from Predictor
   curl http://localhost:8100/predictions/export > pred.json
   ```

2. **Update Scheduler configuration**:
   ```python
   # Before
   strategy = ShortestQueueStrategy(
       taskinstances=taskinstances,
       predictor_url="http://localhost:8100"
   )

   # After
   strategy = ShortestQueueStrategy(
       taskinstances=taskinstances,
       use_lookup_predictor=True,
       prediction_file="pred.json"
   )
   ```

3. **Verify predictions**:
   ```python
   stats = strategy.lookup_predictor.get_stats()
   print(f"Loaded {stats['successful_records']} predictions")
   ```

## Implementation Details

### Files

- **`lookup_predictor.py`**: Core lookup predictor class
- **`strategy_refactored.py`**: Integration into ShortestQueueStrategy
- **`tests/test_lookup_predictor.py`**: Comprehensive tests

### Key Methods

```python
class LookupPredictor:
    def __init__(self, prediction_file: str)
        """Load predictions from JSON file"""

    def predict(self, model_type: str, metadata: Dict) -> Optional[Dict]
        """Lookup prediction for model_type"""

    def get_stats(self) -> Dict
        """Get statistics about loaded predictions"""
```

## Future Enhancements

1. **Hot Reload**: Auto-reload prediction file when it changes
2. **Caching**: Cache frequently-used predictions in memory
3. **Fallback**: Try lookup first, fall back to API if no match
4. **Export Tool**: Tool to export API predictions to lookup file
5. **Compression**: Support compressed JSON files (.json.gz)

## References

- Prediction file: `swarmpilot_taskinstance/pred.json`
- Strategy implementation: `swarmpilot_globalqueue/strategy_refactored.py:264-546`
- Tests: `swarmpilot_globalqueue/tests/test_lookup_predictor.py`
