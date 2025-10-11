#!/usr/bin/env python3
"""
Custom Strategy Example

Demonstrates how to implement a custom scheduling strategy.
"""

from typing import List
from src.scheduler import SwarmPilotScheduler
from src.scheduler.strategies import BaseStrategy, TaskInstance, TaskInstanceQueue, SelectionRequest
from src.scheduler.models import SchedulerRequest, EnqueueResponse


class RandomStrategy(BaseStrategy):
    """
    Custom strategy that selects a random TaskInstance

    This is a simple example to demonstrate how to implement
    your own scheduling logic.
    """

    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Select a random instance from candidates

        Args:
            candidates: List of (TaskInstance, TaskInstanceQueue) tuples
            request: The scheduling request

        Returns:
            Selected (TaskInstance, TaskInstanceQueue) tuple
        """
        import random
        selected = random.choice(candidates)

        print(f"RandomStrategy selected instance {selected[0].uuid}")
        return selected

    def update_queue(
        self,
        selected_instance: TaskInstance,
        request: SelectionRequest,
        enqueue_response: EnqueueResponse
    ):
        """
        Update queue state after enqueue (optional)

        Args:
            selected_instance: The selected TaskInstance
            request: The scheduling request
            enqueue_response: Response from TaskInstance
        """
        # For this simple strategy, we don't track queue state
        print(f"Task {enqueue_response.task_id} enqueued to {selected_instance.uuid}")


class LeastLoadedStrategy(BaseStrategy):
    """
    Custom strategy that selects the instance with smallest queue size

    This is more sophisticated and considers actual queue state.
    """

    def _select_from_candidates(
        self,
        candidates: List[tuple[TaskInstance, TaskInstanceQueue]],
        request: SelectionRequest
    ) -> tuple[TaskInstance, TaskInstanceQueue]:
        """
        Select instance with smallest queue size

        Args:
            candidates: List of (TaskInstance, TaskInstanceQueue) tuples
            request: The scheduling request

        Returns:
            Selected (TaskInstance, TaskInstanceQueue) tuple
        """
        # Sort by queue size and select the one with smallest queue
        selected = min(candidates, key=lambda x: x[1].queue_size)

        print(
            f"LeastLoadedStrategy selected instance {selected[0].uuid} "
            f"with queue_size={selected[1].queue_size}"
        )
        return selected

    def update_queue(
        self,
        selected_instance: TaskInstance,
        request: SelectionRequest,
        enqueue_response: EnqueueResponse
    ):
        """Update queue state (simplified)"""
        print(f"Task {enqueue_response.task_id} enqueued")


def demo_random_strategy():
    """Demonstrate random strategy"""
    print("=" * 60)
    print("Demo 1: Random Strategy")
    print("=" * 60)

    scheduler = SwarmPilotScheduler()

    # Set custom strategy
    custom_strategy = RandomStrategy(scheduler.taskinstances)
    scheduler.strategy = custom_strategy

    print(f"✓ Using custom RandomStrategy")

    # Note: Would need actual TaskInstances to schedule tasks
    print("Note: Add TaskInstances with scheduler.add_task_instance() to test")


def demo_least_loaded_strategy():
    """Demonstrate least loaded strategy"""
    print("\n" + "=" * 60)
    print("Demo 2: Least Loaded Strategy")
    print("=" * 60)

    scheduler = SwarmPilotScheduler()

    # Set custom strategy
    custom_strategy = LeastLoadedStrategy(scheduler.taskinstances)
    scheduler.strategy = custom_strategy

    print(f"✓ Using custom LeastLoadedStrategy")

    # Note: Would need actual TaskInstances to schedule tasks
    print("Note: Add TaskInstances with scheduler.add_task_instance() to test")


def demo_strategy_comparison():
    """Compare different strategies"""
    print("\n" + "=" * 60)
    print("Demo 3: Strategy Comparison")
    print("=" * 60)

    scheduler = SwarmPilotScheduler()

    strategies = [
        ("random", RandomStrategy(scheduler.taskinstances)),
        ("least_loaded", LeastLoadedStrategy(scheduler.taskinstances)),
        ("round_robin", "round_robin"),
        ("shortest_queue", "shortest_queue"),
    ]

    for name, strategy in strategies:
        if isinstance(strategy, str):
            scheduler.set_strategy(strategy)
            print(f"✓ Switched to built-in strategy: {name}")
        else:
            scheduler.strategy = strategy
            print(f"✓ Switched to custom strategy: {name}")


if __name__ == "__main__":
    demo_random_strategy()
    demo_least_loaded_strategy()
    demo_strategy_comparison()

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print("To implement your own strategy:")
    print("1. Inherit from BaseStrategy")
    print("2. Implement _select_from_candidates() method")
    print("3. Optionally implement update_queue() method")
    print("4. Set it on the scheduler with: scheduler.strategy = MyStrategy(...)")
