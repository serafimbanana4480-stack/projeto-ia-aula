"""SWARM core — orchestrator + coordinator + agent defs + types."""

from backend.swarm.core.agents import (
    AGENT_BINDINGS,
    AGENT_DEFINITIONS,
    all_roles,
    get_definition,
)
from backend.swarm.core.coordinator import (
    AntiLoopGuard,
    Coordinator,
    CoordinatorDecision,
    detect_mode,
)
from backend.swarm.core.orchestrator import SwarmOrchestrator, SwarmRunRequest
from backend.swarm.core.types import (
    AgentDefinition,
    AgentMessage,
    AgentRole,
    Decision,
    MessageType,
    OperationalMode,
    Proposal,
    QualityScores,
    ReviewReport,
    SwarmResult,
    SwarmStrategy,
    WorkflowState,
)

__all__ = [
    "AGENT_BINDINGS",
    "AGENT_DEFINITIONS",
    "all_roles",
    "get_definition",
    "AntiLoopGuard",
    "Coordinator",
    "CoordinatorDecision",
    "detect_mode",
    "SwarmOrchestrator",
    "SwarmRunRequest",
    "AgentDefinition",
    "AgentMessage",
    "AgentRole",
    "Decision",
    "MessageType",
    "OperationalMode",
    "Proposal",
    "QualityScores",
    "ReviewReport",
    "SwarmResult",
    "SwarmStrategy",
    "WorkflowState",
]
