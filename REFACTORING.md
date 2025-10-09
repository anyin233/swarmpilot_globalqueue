# GlobalQueue Strategy Pattern Refactoring

## Overview

The GlobalQueue task instance selection logic has been refactored using the Strategy Pattern. This allows for flexible and extensible queue selection strategies.

## Architecture

### Before Refactoring

```
SwarmPilotGlobalMsgQueue
├── queues: Dict[str, PriorityQueue]  # Cached queue information
├── update_queues()                    # Manual queue cache update
└── enqueue()                          # Hardcoded shortest queue logic
```

### After Refactoring

```
SwarmPilotGlobalMsgQueue
├── taskinstances: List[TaskInstance]
├── strategy: BaseStrategy             # Pluggable strategy
└── enqueue()                          # Delegates to strategy

BaseStrategy (Abstract)
├── filter_queues()                    # Filter by model_id
└── select()                           # Main entry point
    └── _select_from_candidates()      # Strategy-specific logic

ShortestQueueStrategy (Concrete)
└── _select_from_candidates()          # Shortest expected_ms
```

## Key Components

### 1. BaseStrategy (Abstract Base Class)

Located in `strategy.py`, defines the interface for all selection strategies:

- **`filter_queues(request)`**: Queries all TaskInstances and returns candidate queues matching the request's model_id
- **`select(request)`**: Main entry point that:
  1. Filters available queues
  2. Selects optimal queue using strategy logic
  3. Returns selected queue and TaskInstance
- **`_select_from_candidates(candidates, request)`**: Abstract method to be implemented by subclasses

### 2. ShortestQueueStrategy (Default Strategy)

Implements the original queue selection logic:
- Selects the queue with the shortest `expected_ms` value
- Equivalent to the previous hardcoded behavior

### 3. SwarmPilotGlobalMsgQueue (Refactored)

Main changes:
- Removed `queues` dictionary (no more cached queue state)
- Removed `update_queues()` method (queues are queried on-demand)
- Added `strategy` property for pluggable selection strategies
- Simplified `enqueue()` to delegate selection to strategy

## Usage

### Basic Usage (Default Strategy)

```python
from main import SwarmPilotGlobalMsgQueue, GlobalRequestMessage
from uuid import uuid4

# Initialize with default strategy (ShortestQueueStrategy)
queue = SwarmPilotGlobalMsgQueue()
queue.load_task_instance_from_config("task_instances.yaml")

# Enqueue tasks - strategy is used automatically
task = GlobalRequestMessage(
    model_id="easyocr",
    input_data={},
    input_features={"metadata": {...}},
    uuid=uuid4()
)
response = queue.enqueue(task)
```

### Using Custom Strategies

```python
from main import SwarmPilotGlobalMsgQueue
from strategy import BaseStrategy, SelectionRequest, ModelMsgQueue
from typing import List

# Define custom strategy
class MyCustomStrategy(BaseStrategy):
    def _select_from_candidates(self, candidates: List[ModelMsgQueue],
                                request: SelectionRequest) -> ModelMsgQueue:
        # Your custom selection logic here
        return min(candidates, key=lambda q: q.length)

# Use custom strategy
queue = SwarmPilotGlobalMsgQueue()
queue.load_task_instance_from_config("task_instances.yaml")
queue.strategy = MyCustomStrategy(queue.taskinstances)

# Now enqueue() will use your custom strategy
response = queue.enqueue(task)
```

See `example_custom_strategy.py` for more examples including:
- RandomStrategy
- LeastLoadedStrategy
- WeightedStrategy

## Benefits

1. **Extensibility**: Easy to add new selection strategies without modifying core code
2. **On-Demand Querying**: No need to maintain cached queue state, always uses fresh data
3. **Separation of Concerns**: Selection logic is isolated from queue management
4. **Testability**: Strategies can be tested independently
5. **Flexibility**: Strategies can be swapped at runtime

## Migration Guide

### API Changes

1. **Removed**: `SwarmPilotGlobalMsgQueue.update_queues()`
   - No longer needed as queues are queried on-demand during enqueue

2. **Removed**: `SwarmPilotGlobalMsgQueue.queues` attribute
   - Queue state is no longer cached

3. **Added**: `SwarmPilotGlobalMsgQueue.strategy` property
   - Get/set the current selection strategy

4. **Deprecated**: `POST /queue/update` API endpoint
   - Returns deprecation notice
   - Queue status is now fetched dynamically

### Code Migration

**Before:**
```python
queue = SwarmPilotGlobalMsgQueue()
queue.load_task_instance_from_config("config.yaml")
queue.update_queues()  # Manual update
response = queue.enqueue(task)
queue.update_queues()  # Update after enqueue
```

**After:**
```python
queue = SwarmPilotGlobalMsgQueue()
queue.load_task_instance_from_config("config.yaml")
# No need to call update_queues()
response = queue.enqueue(task)  # Queries queues automatically
```

## Implementation Details

### Filter Logic

The `filter_queues()` method in `BaseStrategy`:
1. Queries all TaskInstances via their HTTP API
2. Gets model list from each TaskInstance
3. Filters models by matching `model_id`
4. For each matching queue:
   - Gets queue status (size)
   - Gets prediction (expected_ms, error_ms) if queue is non-empty
5. Returns list of `ModelMsgQueue` objects

### Selection Flow

```
User calls enqueue(task)
    ↓
SwarmPilotGlobalMsgQueue.enqueue()
    ↓
strategy.select(request)
    ↓
strategy.filter_queues(request)  → List[ModelMsgQueue]
    ↓
strategy._select_from_candidates()  → Selected ModelMsgQueue
    ↓
Find TaskInstance by UUID
    ↓
Return SelectionResult
    ↓
Send task to selected queue
```

## Files Modified

- `strategy.py` (NEW): Strategy classes
- `main.py`: Refactored to use strategy pattern
- `api.py`: Updated to handle removed methods
- `tests/test_global_queue.py`: Updated test
- `example_custom_strategy.py` (NEW): Custom strategy examples

## Testing

Run the updated test:
```bash
cd swarmpilot_globalqueue
uv run python tests/test_global_queue.py
```

## Future Enhancements

Potential new strategies to implement:
- **RoundRobinStrategy**: Distribute tasks evenly across instances
- **AffinityStrategy**: Keep tasks from same source on same instance
- **CostAwareStrategy**: Consider GPU/compute costs
- **LatencyAwareStrategy**: Consider network latency to TaskInstances
- **HybridStrategy**: Combine multiple strategies with weights
