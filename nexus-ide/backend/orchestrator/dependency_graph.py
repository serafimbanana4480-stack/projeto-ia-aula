"""Dependency graph for multi-agent task orchestration.

Models tasks as a Directed Acyclic Graph (DAG) where edges represent
dependencies. The orchestrator uses topological sorting to determine
execution order and identify parallelizable tasks.

Architecture:
- ``TaskNode``: a single unit of work with metadata
- ``DependencyGraph``: DAG with validation, topological sort, and parallel groups
- ``ExecutionPlan``: serializable plan with steps and dependencies
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class TaskPriority(int, Enum):
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


@dataclass
class TaskNode:
    """A single unit of work in the dependency graph.

    Each task is assigned to an agent type and may depend on other tasks.
    Tasks with no mutual dependencies can execute in parallel.
    """

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    description: str = ""
    agent: str = "CODER"  # agent type to execute this task
    model_key: str = "coder"  # model tier to use
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING

    # Execution context
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    context: str = ""  # additional context for the agent

    # Dependencies
    depends_on: list[str] = field(default_factory=list)  # task_ids this depends on
    required_by: list[str] = field(default_factory=list)  # task_ids that depend on this

    # Execution metadata
    max_retries: int = 2
    retry_count: int = 0
    timeout_seconds: int = 300
    started_at: float = 0.0
    completed_at: float = 0.0
    error_message: str = ""

    # Tool configuration
    allowed_tools: list[str] = field(default_factory=list)
    sandboxed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "agent": self.agent,
            "model_key": self.model_key,
            "priority": self.priority.value,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "required_by": self.required_by,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "timeout_seconds": self.timeout_seconds,
            "error_message": self.error_message,
            "sandboxed": self.sandboxed,
        }


class DependencyGraph:
    """Directed Acyclic Graph for task orchestration.

    Validates that the graph is acyclic, computes execution layers
    (parallel groups), and tracks task status.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}
        self._adjacency: dict[str, list[str]] = defaultdict(list)  # task_id -> [dependents]
        self._in_degree: dict[str, int] = defaultdict(int)

    def add_task(self, task: TaskNode) -> TaskNode:
        """Add a task node to the graph."""
        if task.task_id in self._nodes:
            raise ValueError(f"Duplicate task_id: {task.task_id}")
        self._nodes[task.task_id] = task
        self._in_degree[task.task_id] = len(task.depends_on)
        for dep_id in task.depends_on:
            self._adjacency[dep_id].append(task.task_id)
        return task

    def add_dependency(self, from_task_id: str, to_task_id: str) -> None:
        """Add a dependency: to_task depends on from_task."""
        if from_task_id not in self._nodes:
            raise KeyError(f"Task not found: {from_task_id}")
        if to_task_id not in self._nodes:
            raise KeyError(f"Task not found: {to_task_id}")

        if to_task_id not in self._nodes[from_task_id].required_by:
            self._nodes[from_task_id].required_by.append(to_task_id)
        if from_task_id not in self._nodes[to_task_id].depends_on:
            self._nodes[to_task_id].depends_on.append(from_task_id)
        self._adjacency[from_task_id].append(to_task_id)
        self._in_degree[to_task_id] += 1

    def validate(self) -> tuple[bool, str]:
        """Validate that the graph is acyclic.

        Returns (is_valid, error_message).
        """
        if not self._nodes:
            return False, "Graph is empty"

        # Check all dependencies exist
        for task in self._nodes.values():
            for dep_id in task.depends_on:
                if dep_id not in self._nodes:
                    return False, f"Task {task.task_id} depends on non-existent {dep_id}"

        # Detect cycles using Kahn's algorithm
        in_degree = dict(self._in_degree)
        queue: deque[str] = deque(tid for tid, deg in in_degree.items() if deg == 0)
        visited = 0

        while queue:
            node_id = queue.popleft()
            visited += 1
            for neighbor in self._adjacency.get(node_id, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self._nodes):
            return False, "Graph contains a cycle"

        return True, ""

    def topological_layers(self) -> list[list[str]]:
        """Compute execution layers for parallel execution.

        Each layer contains tasks that can execute in parallel.
        Tasks in layer N depend only on tasks in layers < N.
        """
        in_degree = dict(self._in_degree)
        queue: deque[str] = deque(tid for tid, deg in in_degree.items() if deg == 0)
        layers: list[list[str]] = []
        processed = 0

        while queue:
            layer: list[str] = []
            for _ in range(len(queue)):
                node_id = queue.popleft()
                layer.append(node_id)
                processed += 1
                for neighbor in self._adjacency.get(node_id, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
            if layer:
                layers.append(layer)

        if processed != len(self._nodes):
            logger.error("Cycle detected during topological sort")
            return []

        return layers

    def get_ready_tasks(self) -> list[TaskNode]:
        """Return tasks whose dependencies are all satisfied."""
        ready: list[TaskNode] = []
        for task in self._nodes.values():
            if task.status != TaskStatus.PENDING:
                continue
            deps_satisfied = all(
                self._nodes[dep_id].status == TaskStatus.COMPLETED for dep_id in task.depends_on
            )
            if deps_satisfied:
                ready.append(task)
        return ready

    def get_task(self, task_id: str) -> TaskNode | None:
        return self._nodes.get(task_id)

    def get_all_tasks(self) -> list[TaskNode]:
        return list(self._nodes.values())

    def update_status(self, task_id: str, status: TaskStatus, error: str = "") -> None:
        """Update a task's execution status."""
        if task_id in self._nodes:
            self._nodes[task_id].status = status
            if error:
                self._nodes[task_id].error_message = error

    def is_complete(self) -> bool:
        """Check if all tasks have reached a terminal state."""
        terminal = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        }
        return all(t.status in terminal for t in self._nodes.values())

    def has_failures(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self._nodes.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [t.to_dict() for t in self._nodes.values()],
            "layers": self.topological_layers(),
            "is_valid": self.validate()[0],
            "total_tasks": len(self._nodes),
        }


@dataclass
class ExecutionPlan:
    """Serializable execution plan with steps and dependencies.

    This is the structure sent to the frontend for display and approval.
    """

    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    session_id: str = ""

    # Steps
    steps: list[TaskNode] = field(default_factory=list)
    dependency_graph: DependencyGraph = field(default_factory=DependencyGraph)

    # Metadata
    estimated_duration_seconds: int = 0
    total_steps: int = 0
    parallel_layers: int = 0
    risk_level: str = "low"  # low, medium, high
    requires_approval: bool = True
    approved: bool = False
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "description": self.description,
            "session_id": self.session_id,
            "steps": [s.to_dict() for s in self.steps],
            "graph": self.dependency_graph.to_dict(),
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "total_steps": len(self.steps),
            "parallel_layers": len(self.dependency_graph.topological_layers()),
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "approved": self.approved,
        }

    @classmethod
    def from_steps(
        cls,
        title: str,
        description: str,
        steps: list[TaskNode],
        session_id: str = "",
    ) -> ExecutionPlan:
        """Create a plan from a list of steps, building the dependency graph."""
        plan = cls(
            title=title,
            description=description,
            session_id=session_id,
            steps=steps,
            total_steps=len(steps),
        )
        for step in steps:
            plan.dependency_graph.add_task(step)
        valid, _ = plan.dependency_graph.validate()
        if valid:
            plan.parallel_layers = len(plan.dependency_graph.topological_layers())
        return plan
