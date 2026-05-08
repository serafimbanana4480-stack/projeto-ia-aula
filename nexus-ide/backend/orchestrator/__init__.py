"""Orchestrator package — routing, agent pool, context, fallback, multi-agent engine.

See ARCHITECTURE.md §4.
"""
from backend.orchestrator.engine import OrchestrationEngine, OrchestrationResult, OrchestrationState
from backend.orchestrator.events import EventBus, EventType, OrchestratorEvent, EventEmitter
from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskStatus,
    TaskPriority,
)

__all__ = [
    "OrchestrationEngine",
    "OrchestrationResult",
    "OrchestrationState",
    "EventBus",
    "EventType",
    "OrchestratorEvent",
    "EventEmitter",
    "DependencyGraph",
    "ExecutionPlan",
    "TaskNode",
    "TaskStatus",
    "TaskPriority",
]
