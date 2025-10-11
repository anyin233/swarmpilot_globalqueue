"""
SwarmPilot Scheduler Core

Main scheduler class that routes tasks to appropriate TaskInstances.
Integrates with TaskTracker for task state management.
"""

from loguru import logger
from typing import Dict, Any, List, Optional
from uuid import uuid4, UUID
import yaml
import time

from .client import TaskInstanceClient
from .task_tracker import TaskTracker
from .models import SchedulerRequest, SchedulerResponse
from .strategies import (
    BaseStrategy,
    ShortestQueueStrategy,
    RoundRobinStrategy,
    WeightedStrategy,
    ProbabilisticQueueStrategy,
    TaskInstance,
    SelectionRequest
)


class SwarmPilotScheduler:
    """
    Main scheduler class that routes tasks to appropriate TaskInstances

    Features:
    - Multiple scheduling strategies
    - Task state tracking via TaskTracker
    - Timing statistics
    - Dynamic instance management
    """

    def __init__(self, strategy: Optional[BaseStrategy] = None):
        """
        Initialize Scheduler

        Args:
            strategy: TaskInstance selection strategy (defaults to ShortestQueue)
        """
        self.taskinstances: List[TaskInstance] = []
        self._strategy = strategy
        self.task_tracker = TaskTracker()
        self.last_routing_info: Optional[Dict[str, Any]] = None

        # Track request arrival times for timing calculation
        self.request_times: Dict[str, tuple[float, str]] = {}

        # Track timing statistics
        self.timing_statistics: List[tuple[str, float, float]] = []

    @property
    def strategy(self) -> BaseStrategy:
        """Get the current strategy, creating default if not set"""
        if self._strategy is None:
            self._strategy = ShortestQueueStrategy(
                self.taskinstances,
                use_lookup_predictor=True,
                prediction_file="/home/yanweiye/Project/swarmpilot/swarmpilot_taskinstance/pred.json"
            )
        return self._strategy

    @strategy.setter
    def strategy(self, strategy: BaseStrategy):
        """Set a new strategy"""
        self._strategy = strategy
        if self._strategy:
            self._strategy.taskinstances = self.taskinstances

    def set_strategy(self, strategy_name: str) -> None:
        """Set strategy by name"""
        strategy_map = {
            "shortest_queue": ShortestQueueStrategy,
            "round_robin": RoundRobinStrategy,
            "weighted": WeightedStrategy,
            "probabilistic": ProbabilisticQueueStrategy
        }

        strategy_class = strategy_map.get(strategy_name.lower())
        if not strategy_class:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        if strategy_class == ShortestQueueStrategy:
            self.strategy = strategy_class(
                self.taskinstances,
                use_lookup_predictor=True,
                prediction_file="/home/yanweiye/Project/swarmpilot/swarmpilot_taskinstance/pred.json"
            )
        else:
            self.strategy = strategy_class(self.taskinstances)

        logger.info(f"Set scheduling strategy to: {strategy_name}")

    def load_task_instances_from_config(self, config_path: str) -> None:
        """Load TaskInstances from configuration file"""
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)

        instances = data.get('instances', [])
        self.taskinstances.clear()

        for instance_config in instances:
            if isinstance(instance_config, dict):
                host = instance_config.get('host', 'localhost')
                port = instance_config.get('port', 8100)
                base_url = f"http://{host}:{port}"
            else:
                base_url = instance_config

            ti_uuid = uuid4()
            client = TaskInstanceClient(base_url)
            task_instance = TaskInstance(uuid=ti_uuid, instance=client)

            self.taskinstances.append(task_instance)
            logger.info(f"Loaded TaskInstance {ti_uuid} from {base_url}")

        if self._strategy:
            self._strategy.taskinstances = self.taskinstances

        logger.info(f"Loaded {len(self.taskinstances)} TaskInstance(s)")

    def add_task_instance(self, base_url: str) -> UUID:
        """Add a single TaskInstance"""
        ti_uuid = uuid4()
        client = TaskInstanceClient(base_url)
        task_instance = TaskInstance(uuid=ti_uuid, instance=client)

        self.taskinstances.append(task_instance)

        if self._strategy:
            self._strategy.taskinstances = self.taskinstances

        logger.info(f"Added TaskInstance {ti_uuid} at {base_url}")
        return ti_uuid

    def remove_task_instance(self, instance_uuid: UUID) -> bool:
        """Remove a TaskInstance"""
        for i, ti in enumerate(self.taskinstances):
            if ti.uuid == instance_uuid:
                self.taskinstances.pop(i)
                logger.info(f"Removed TaskInstance {instance_uuid}")
                return True

        logger.warning(f"TaskInstance {instance_uuid} not found")
        return False

    def schedule(self, request: SchedulerRequest) -> SchedulerResponse:
        """
        Schedule a task to the optimal TaskInstance

        Args:
            request: Scheduler request containing task information

        Returns:
            SchedulerResponse with routing information
        """
        arrival_time = time.time()

        if not self.taskinstances:
            raise RuntimeError("No TaskInstances configured")

        if not request.request_id:
            request.request_id = str(uuid4())

        # Create selection request
        selection_req = SelectionRequest(
            model_type=request.model_type,
            input_data=request.input_data,
            metadata=request.metadata
        )

        # Use strategy to select optimal instance
        result = self.strategy.select(selection_req)
        selected_instance = result.selected_instance
        queue_info = result.queue_info

        # Enqueue task to selected instance
        try:
            enqueue_response = selected_instance.instance.enqueue_task(
                input_data=request.input_data,
                metadata=request.metadata
            )

            # Register task in tracker
            self.task_tracker.register_task(
                task_id=enqueue_response.task_id,
                ti_uuid=selected_instance.uuid,
                model_name=request.model_type,
                submit_time=arrival_time
            )

            # Mark as scheduled
            self.task_tracker.mark_scheduled(enqueue_response.task_id)

            # Store arrival time
            self.request_times[enqueue_response.task_id] = (arrival_time, request.request_id)

            # Update queue state
            try:
                self.strategy.update_queue(
                    selected_instance=selected_instance,
                    request=selection_req,
                    enqueue_response=enqueue_response
                )
            except Exception as e:
                logger.warning(f"Failed to update queue state: {e}")

            # Save routing information
            self.last_routing_info = {
                "request_id": request.request_id,
                "task_id": enqueue_response.task_id,
                "instance_uuid": str(selected_instance.uuid),
                "instance_url": selected_instance.instance.base_url,
                "model_type": queue_info.model_type,
                "expected_ms": queue_info.expected_ms,
                "queue_size_before": queue_info.queue_size,
                "arrival_time": arrival_time
            }

            logger.info(
                f"Task {enqueue_response.task_id} scheduled to instance {selected_instance.uuid} "
                f"(model: {queue_info.model_type}, expected: {queue_info.expected_ms}ms)"
            )

            return SchedulerResponse(
                task_id=enqueue_response.task_id,
                instance_id=str(selected_instance.uuid),
                instance_url=selected_instance.instance.base_url,
                model_type=queue_info.model_type,
                queue_size=enqueue_response.queue_size
            )

        except Exception as e:
            logger.error(f"Failed to enqueue task to instance {selected_instance.uuid}: {e}")
            raise RuntimeError(f"Failed to schedule task: {e}")

    def get_last_routing_info(self) -> Dict[str, Any]:
        """Get last routing information"""
        if self.last_routing_info is None:
            raise RuntimeError("No routing information available")
        return self.last_routing_info

    def get_instance_statuses(self) -> List[Dict[str, Any]]:
        """Get status of all configured TaskInstances"""
        statuses = []

        for ti in self.taskinstances:
            try:
                status = ti.instance.get_status()
                statuses.append({
                    "uuid": str(ti.uuid),
                    "url": ti.instance.base_url,
                    "instance_id": status.instance_id,
                    "model_type": status.model_type,
                    "replicas": status.replicas_running,
                    "queue_size": status.queue_size,
                    "status": status.status
                })
            except Exception as e:
                logger.warning(f"Failed to get status for instance {ti.uuid}: {e}")
                statuses.append({
                    "uuid": str(ti.uuid),
                    "url": ti.instance.base_url,
                    "status": "error",
                    "error": str(e)
                })

        return statuses

    def get_total_capacity(self) -> Dict[str, int]:
        """Get total capacity by model type"""
        capacity = {}

        for ti in self.taskinstances:
            try:
                status = ti.instance.get_status()
                if status.model_type:
                    capacity[status.model_type] = capacity.get(status.model_type, 0) + status.replicas_running
            except Exception:
                pass

        return capacity

    def handle_task_completion(self, task_id: str, instance_uuid: UUID, execution_time: float) -> Optional[float]:
        """Handle task completion notification"""
        total_time_ms = None

        # Mark task as completed in tracker
        self.task_tracker.mark_completed(task_id=task_id)

        # Calculate total time if we have arrival time
        if task_id in self.request_times:
            arrival_time, request_id = self.request_times[task_id]
            completion_time = time.time()
            total_time_ms = (completion_time - arrival_time) * 1000

            self.timing_statistics.append((task_id, total_time_ms, execution_time))

            if len(self.timing_statistics) > 1000:
                self.timing_statistics = self.timing_statistics[-1000:]

            logger.info(
                f"Task {task_id} completed - Total: {total_time_ms:.2f}ms, "
                f"Execution: {execution_time:.2f}ms"
            )

            del self.request_times[task_id]

        # Update queue state
        self.strategy.update_queue_on_completion(
            instance_uuid=instance_uuid,
            task_id=task_id,
            execution_time=execution_time
        )

        return total_time_ms

    def get_timing_statistics(self) -> Dict[str, Any]:
        """Get timing statistics for completed tasks"""
        if not self.timing_statistics:
            return {
                "total_tasks": 0,
                "avg_total_time_ms": 0.0,
                "avg_execution_time_ms": 0.0,
                "avg_overhead_ms": 0.0,
                "recent_tasks": []
            }

        total_times = [t[1] for t in self.timing_statistics]
        execution_times = [t[2] for t in self.timing_statistics]
        overheads = [t[1] - t[2] for t in self.timing_statistics]

        recent_tasks = [
            {
                "task_id": task_id,
                "total_time_ms": total_time,
                "execution_time_ms": exec_time,
                "overhead_ms": total_time - exec_time
            }
            for task_id, total_time, exec_time in self.timing_statistics[-10:]
        ]

        return {
            "total_tasks": len(self.timing_statistics),
            "avg_total_time_ms": sum(total_times) / len(total_times),
            "avg_execution_time_ms": sum(execution_times) / len(execution_times),
            "avg_overhead_ms": sum(overheads) / len(overheads),
            "min_total_time_ms": min(total_times),
            "max_total_time_ms": max(total_times),
            "recent_tasks": recent_tasks
        }
