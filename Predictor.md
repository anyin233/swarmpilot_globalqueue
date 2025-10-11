# Predictor

Predictor is responsible for predicting task execution time distributions (represented using quantiles). It maintains all prediction models internally, accepts task feature information from external sources, and returns execution time distributions for use by the Scheduler for prediction.

## API Design

### `/train`

Train quantile execution time prediction model

Parameter Design
```python
{
    "config": File              # Training configuration file
}
```

For config format, refer to other training configuration files in the project

Return Format
```python
{
    "status": str,
    "model_key": str,           # Model Key corresponding to the storage key of the trained quantile execution time prediction model
    "metrics": Dict[str, Any],
    "duration_seconds": int
}
```

### `/predict/single/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}`

Predict execution time distribution for a single task

Path Parameters
```
model_type: str           # Model type
model_name: str           # Model name
hardware: str             # Hardware configuration
software_name: str        # Software name
software_version: str     # Software version
```

For parameter setting patterns of `model_type`, `model_name`, `hardware`, `software_name`, `software_version`, refer to yaml configuration files

Request Body Parameters
```python
{
    "trace": TracePayload,      # Task trace information, format reference example trace files in project, this interface only accepts one trace item
    "confidence_level": float,   # Confidence level setting,
    "lookup_table": bool, # (Optional) Whether to use preset lookup table
    "lookup_table_name": str # (Optional, required when lookup_table == True) If using lookup table, the filename of the lookup table
}
```

Notes:
- lookup table: A lookup table used during experiments to speed up implementation, internally storing pre-computed prediction results, implemented as a CSV file with input features in front columns and predicted quantile results and expected errors in back columns.

Return Format
```python
{
    "summary": {
        "total": int,
        "success": int,
        "failed": int,
        "confidence_level": float,
        "duration_seconds": int
    },
    "results": {
        "status": str,
        "quantile_predictions": List[float],
        "quantiles": List[float],
        "model_info": {
            "type": str,
            "name": str,
            "hardware": str,
            "software_name": str,
            "software_version": str
        },
        "expect": float,
        "error": float # Based on quantile distribution theory, calculate its expectation and error (error uses standard deviation)
    }
}
```

### `/predict/batch/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}`

Batch predict execution time distributions for multiple tasks

Path Parameters
```
model_type: str           # Model type
model_name: str           # Model name
hardware: str             # Hardware configuration
software_name: str        # Software name
software_version: str     # Software version
```

For parameter setting patterns of `model_type`, `model_name`, `hardware`, `software_name`, `software_version`, refer to yaml configuration files

Request Body Parameters
```python
{
    "trace": List[TracePayload],  # List of task trace information, format reference example trace files in project, accepts a group of traces
    "confidence_level": float,     # Confidence level setting
    "lookup_table": bool, # (Optional) Whether to use preset lookup table
    "lookup_table_name": str # (Optional, required when lookup_table == True) If using lookup table, the filename of the lookup table
}
```

Notes:
- lookup table: A lookup table used during experiments to speed up implementation, internally storing pre-computed prediction results, implemented as a CSV file with input features in front columns and predicted quantile results and expected errors in back columns.

Return Format
```python
{
    "summary": {
        "total": int,
        "success": int,
        "failed": int,
        "confidence_level": float,
        "duration_seconds": int
    },
    "results": List[{
        "status": str,
        "quantile_predictions": List[float],
        "quantiles": List[float],
        "model_info": {
            "type": str,
            "name": str,
            "hardware": str,
            "software_name": str,
            "software_version": str
        },
        "expect": float,
        "error": float # Based on quantile distribution theory, calculate its expectation and error (error uses standard deviation)
    }],
    "expect": float,
    "error": float # Based on error accumulation theory, calculate the total expectation and error for all currently predicted tasks (error uses standard deviation)
}
```

### `/predict/table/{model_type}/{model_name}/{hardware}/{software_name}/{software_version}`

Interface Description: This interface will generate a lookup table and return the path to the lookup table

Request Body Parameters
```python
{
    "trace_file": upload_file,  # List of task trace information, accepts a valid trace file
    "confidence_level": float,     # Confidence level setting
}
```

Return Format
```python
{
	"status": str,  # successful, failed
	"path": str,  # path to lookup table
}
```
