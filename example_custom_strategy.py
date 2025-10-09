#!/usr/bin/env python3
"""
Example: How to create and use a custom selection strategy

This example demonstrates:
1. How to create a custom strategy by inheriting from BaseStrategy
2. How to inject the custom strategy into SwarmPilotGlobalMsgQueue
"""

from strategy import BaseStrategy, SelectionRequest, ModelMsgQueue
from main import SwarmPilotGlobalMsgQueue, GlobalRequestMessage
from typing import List
from uuid import uuid4
from loguru import logger
import random


class RandomStrategy(BaseStrategy):
    """
    Example custom strategy: randomly select a queue from candidates

    This is just for demonstration purposes. In production, you would
    implement more sophisticated logic based on your requirements.
    """

    def _select_from_candidates(self, candidates: List[ModelMsgQueue], request: SelectionRequest) -> ModelMsgQueue:
        """
        Randomly select a queue from candidates

        Args:
            candidates: List of candidate queues
            request: Selection request (not used in this strategy)

        Returns:
            Randomly selected queue
        """
        selected = random.choice(candidates)

        logger.info(
            f"RandomStrategy selected: {selected.model_name}:{selected.port} "
            f"(expected_ms={selected.expected_ms})"
        )

        return selected


class LeastLoadedStrategy(BaseStrategy):
    """
    Example custom strategy: select the queue with the smallest queue length

    This strategy ignores expected_ms and only considers the queue length.
    """

    def _select_from_candidates(self, candidates: List[ModelMsgQueue], request: SelectionRequest) -> ModelMsgQueue:
        """
        Select the queue with smallest length

        Args:
            candidates: List of candidate queues
            request: Selection request (not used in this strategy)

        Returns:
            Queue with minimum length
        """
        selected = min(candidates, key=lambda q: q.length)

        logger.info(
            f"LeastLoadedStrategy selected: {selected.model_name}:{selected.port} "
            f"(queue_length={selected.length})"
        )

        return selected


class WeightedStrategy(BaseStrategy):
    """
    Example custom strategy: weighted selection based on both time and queue length

    This strategy considers both expected_ms and queue length with configurable weights.
    """

    def __init__(self, taskinstances, time_weight: float = 0.7, length_weight: float = 0.3):
        """
        Initialize weighted strategy

        Args:
            taskinstances: List of TaskInstance objects
            time_weight: Weight for expected_ms (default 0.7)
            length_weight: Weight for queue length (default 0.3)
        """
        super().__init__(taskinstances)
        self.time_weight = time_weight
        self.length_weight = length_weight

    def _select_from_candidates(self, candidates: List[ModelMsgQueue], request: SelectionRequest) -> ModelMsgQueue:
        """
        Select queue based on weighted score

        Score = time_weight * normalized_expected_ms + length_weight * normalized_length
        (Lower score is better)

        Args:
            candidates: List of candidate queues
            request: Selection request (not used in this strategy)

        Returns:
            Queue with minimum weighted score
        """
        # Normalize expected_ms and length
        max_time = max(q.expected_ms for q in candidates) or 1.0
        max_length = max(q.length for q in candidates) or 1.0

        def calculate_score(q: ModelMsgQueue) -> float:
            norm_time = q.expected_ms / max_time
            norm_length = q.length / max_length
            return self.time_weight * norm_time + self.length_weight * norm_length

        selected = min(candidates, key=calculate_score)

        logger.info(
            f"WeightedStrategy selected: {selected.model_name}:{selected.port} "
            f"(expected_ms={selected.expected_ms}, length={selected.length}, "
            f"score={calculate_score(selected):.3f})"
        )

        return selected


def main():
    """Demonstrate how to use custom strategies"""
    logger.info("=== Custom Strategy Example ===")

    # Example 1: Using default strategy (ShortestQueueStrategy)
    logger.info("\n1. Using default strategy (ShortestQueueStrategy)")
    queue1 = SwarmPilotGlobalMsgQueue()
    queue1.load_task_instance_from_config("task_instances.yaml")
    logger.info(f"Strategy: {queue1.strategy.__class__.__name__}")

    # Example 2: Using RandomStrategy
    logger.info("\n2. Using RandomStrategy")
    queue2 = SwarmPilotGlobalMsgQueue()
    queue2.load_task_instance_from_config("task_instances.yaml")
    queue2.strategy = RandomStrategy(queue2.taskinstances)
    logger.info(f"Strategy: {queue2.strategy.__class__.__name__}")

    # Example 3: Using LeastLoadedStrategy
    logger.info("\n3. Using LeastLoadedStrategy")
    queue3 = SwarmPilotGlobalMsgQueue()
    queue3.load_task_instance_from_config("task_instances.yaml")
    queue3.strategy = LeastLoadedStrategy(queue3.taskinstances)
    logger.info(f"Strategy: {queue3.strategy.__class__.__name__}")

    # Example 4: Using WeightedStrategy with custom weights
    logger.info("\n4. Using WeightedStrategy (70% time, 30% length)")
    queue4 = SwarmPilotGlobalMsgQueue()
    queue4.load_task_instance_from_config("task_instances.yaml")
    queue4.strategy = WeightedStrategy(queue4.taskinstances, time_weight=0.7, length_weight=0.3)
    logger.info(f"Strategy: {queue4.strategy.__class__.__name__}")

    # Example 5: Injecting strategy during initialization
    logger.info("\n5. Injecting strategy during initialization")
    custom_strategy = LeastLoadedStrategy([])  # Empty list will be updated after loading
    queue5 = SwarmPilotGlobalMsgQueue(strategy=custom_strategy)
    queue5.load_task_instance_from_config("task_instances.yaml")
    logger.info(f"Strategy: {queue5.strategy.__class__.__name__}")

    logger.info("\n=== Example Complete ===")
    logger.info("\nTo use a custom strategy in production:")
    logger.info("1. Create your strategy class by inheriting from BaseStrategy")
    logger.info("2. Implement the _select_from_candidates() method")
    logger.info("3. Inject your strategy using queue.strategy = YourStrategy(queue.taskinstances)")


if __name__ == "__main__":
    main()
