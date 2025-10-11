"""
Scheduling Strategies

This package provides various strategies for selecting optimal TaskInstances
for incoming tasks.

Available Strategies:
- ShortestQueueStrategy: Select instance with shortest expected completion time
- RoundRobinStrategy: Distribute tasks evenly in round-robin fashion
- WeightedStrategy: Consider both queue time and prediction uncertainty
- ProbabilisticQueueStrategy: Probabilistic selection based on queue length

Base Classes:
- BaseStrategy: Abstract base class for all strategies
- TaskInstance: TaskInstance wrapper with UUID
- TaskInstanceQueue: Queue information structure
- SelectionRequest: Request for instance selection
- SelectionResult: Result of instance selection
"""

from .base import (
    BaseStrategy,
    TaskInstance,
    TaskInstanceQueue,
    SelectionRequest,
    SelectionResult
)
from .shortest_queue import ShortestQueueStrategy
from .round_robin import RoundRobinStrategy
from .weighted import WeightedStrategy
from .probabilistic import ProbabilisticQueueStrategy

__all__ = [
    # Base classes
    "BaseStrategy",
    "TaskInstance",
    "TaskInstanceQueue",
    "SelectionRequest",
    "SelectionResult",
    # Strategies
    "ShortestQueueStrategy",
    "RoundRobinStrategy",
    "WeightedStrategy",
    "ProbabilisticQueueStrategy",
]
