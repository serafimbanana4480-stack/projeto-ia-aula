"""SWARM — Professional Multi-Agent Orchestration System.

Architecture overview
=====================

The SWARM package implements a Coordinator-centric multi-agent system with
explicit communication, persistent memory, RAG-grounded context, operational
modes, quality scoring, and a safe proposal-then-approval workflow.

Top-level layout
----------------

- ``core``            — Orchestrator, Coordinator, Agent definitions
- ``communication``   — Inter-agent message bus with full audit trail
- ``memory``          — Short/long/project/decision/architecture memory
- ``rag``             — Chunker, hybrid retriever (semantic + keyword)
- ``research``        — External research agent with multi-source synthesis
- ``review``          — Reviewer agent (bugs, security, performance, style, tests)
- ``quality``         — Quality gate (quality, confidence, risk, complexity)
- ``modes``           — Operational mode registry
- ``workflows``       — Safe implementation workflow (propose→approve→implement)
- ``api``             — FastAPI routes mounted under ``/api/swarm``
"""

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
