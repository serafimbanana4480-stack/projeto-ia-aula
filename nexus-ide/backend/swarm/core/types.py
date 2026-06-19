"""SWARM core types — single source of truth for all dataclasses / enums.

Every cross-module data structure lives here so message_bus, memory, RAG,
quality, and the orchestrator speak the same language.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Roles & Modes
# ---------------------------------------------------------------------------


class AgentRole(StrEnum):
    """Canonical SWARM agent roles. Each maps to a specialised NEXUS agent."""

    COORDINATOR = "coordinator"
    ARCHITECT = "architect"
    RESEARCHER = "researcher"
    INVESTIGATOR = "investigator"
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"


class OperationalMode(StrEnum):
    """Top-level SWARM operating modes.

    Each mode selects which agents are involved and which workflow is used.
    """

    ARCHITECTURE = "architecture"
    INVESTIGATION = "investigation"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    BUGFIX = "bugfix"
    PLANNING = "planning"
    RESEARCH = "research"


class SwarmStrategy(StrEnum):
    """Low-level strategies controlling how agents collaborate."""

    DIVIDE = "divide"  # Split into parallel subtasks
    ENSEMBLE = "ensemble"  # All agents solve, synthesise
    PIPELINE = "pipeline"  # Chain agents, output of N feeds N+1
    DEBATE = "debate"  # Propose + moderator integrates
    ADAPTIVE = "adaptive"  # Coordinator picks per objective


class MessageType(StrEnum):
    """Inter-agent message types."""

    REQUEST = "request"
    RESPONSE = "response"
    PROPOSAL = "proposal"
    APPROVAL = "approval"
    REJECTION = "rejection"
    REVIEW = "review"
    EVIDENCE = "evidence"  # RAG snippet
    RESEARCH = "research"  # External research finding
    STATUS = "status"
    ERROR = "error"


class WorkflowState(StrEnum):
    """State of the safe-implementation workflow."""

    PROPOSED = "proposed"
    DISCUSSED = "discussed"
    VALIDATED = "validated"
    APPROVED = "approved"
    IMPLEMENTING = "implementing"
    IMPLEMENTED = "implemented"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------


@dataclass
class AgentDefinition:
    """Static definition of a SWARM role."""

    role: AgentRole
    label: str
    objective: str
    responsibilities: list[str]
    limitations: list[str]
    input_messages: list[MessageType]
    output_messages: list[MessageType]
    memory_layers: list[str]  # names of memory layers it reads/writes
    maps_to: str  # underlying NEXUS agent name (e.g. "ARCHITECT")


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@dataclass
class AgentMessage:
    """A single message in the inter-agent bus."""

    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    sender: str = ""  # AgentRole value or NEXUS agent name
    recipient: str = ""  # AgentRole value, NEXUS agent name, or "broadcast"
    type: MessageType = MessageType.REQUEST
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = ""  # links related messages
    in_reply_to: str = ""  # parent message id
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decisions & reviews
# ---------------------------------------------------------------------------


@dataclass
class Decision:
    """A single architectural or implementation decision."""

    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    rationale: str = ""
    alternatives: list[str] = field(default_factory=list)
    decided_by: str = ""  # role that decided
    approved_by: list[str] = field(default_factory=list)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)
    related_message_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Quality scores
# ---------------------------------------------------------------------------


@dataclass
class QualityScores:
    """Four-axis quality assessment."""

    quality: float = 0.0  # 0-1, overall quality of the proposal / output
    confidence: float = 0.0  # 0-1, confidence in the answer
    risk: float = 0.0  # 0-1, risk of failure (1 = high risk)
    complexity: float = 0.0  # 0-1, intrinsic complexity of the change

    def gate(self, min_quality: float = 0.7, max_risk: float = 0.6) -> bool:
        """Return True if scores pass the default quality gate."""
        return self.quality >= min_quality and self.risk <= max_risk and self.confidence >= 0.5

    def to_dict(self) -> dict[str, float]:
        return {
            "quality": round(self.quality, 3),
            "confidence": round(self.confidence, 3),
            "risk": round(self.risk, 3),
            "complexity": round(self.complexity, 3),
        }


# ---------------------------------------------------------------------------
# Proposals & reviews (safe workflow)
# ---------------------------------------------------------------------------


@dataclass
class Proposal:
    """A proposal emitted by IMPLEMENTER before any code is changed."""

    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    files_to_change: list[dict[str, Any]] = field(default_factory=list)  # {path, change, rationale}
    rationale: str = ""
    created_by: str = AgentRole.IMPLEMENTER.value
    state: WorkflowState = WorkflowState.PROPOSED
    scores: QualityScores = field(default_factory=QualityScores)
    decision_refs: list[str] = field(default_factory=list)  # decision_ids used
    evidence_refs: list[str] = field(default_factory=list)  # RAG chunk ids
    research_refs: list[str] = field(default_factory=list)  # research finding ids
    discussion: list[AgentMessage] = field(default_factory=list)
    review: dict[str, Any] = field(default_factory=dict)
    implementation_log: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    _scores_initialised: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Auto-score the proposal once on first construction, so callers don't
        # have to remember to call score_proposal() before validation.
        if not self._scores_initialised:
            try:
                from backend.swarm.quality.quality_gate import score_proposal

                self.scores = score_proposal(self)
            except Exception:
                # If the quality gate is not yet importable, leave default
                pass
            self._scores_initialised = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "title": self.title,
            "description": self.description,
            "files_to_change": self.files_to_change,
            "rationale": self.rationale,
            "created_by": self.created_by,
            "state": self.state.value,
            "scores": self.scores.to_dict(),
            "decision_refs": self.decision_refs,
            "evidence_refs": self.evidence_refs,
            "research_refs": self.research_refs,
            "discussion_count": len(self.discussion),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ReviewReport:
    """REVIEWER output attached to a proposal or final answer."""

    review_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    target_id: str = ""  # proposal_id or message_id
    findings: list[dict[str, Any]] = field(
        default_factory=list
    )  # {category, severity, message, location}
    passed: bool = False
    scores: QualityScores = field(default_factory=QualityScores)
    summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "target_id": self.target_id,
            "findings": self.findings,
            "passed": self.passed,
            "scores": self.scores.to_dict(),
            "summary": self.summary,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Final result
# ---------------------------------------------------------------------------


@dataclass
class SwarmResult:
    """Aggregated result of a SWARM run."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    mode: OperationalMode = OperationalMode.ARCHITECTURE
    strategy: SwarmStrategy = SwarmStrategy.ADAPTIVE
    objective: str = ""
    final_answer: str = ""
    agents_involved: list[str] = field(default_factory=list)
    messages: list[AgentMessage] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    reviews: list[ReviewReport] = field(default_factory=list)
    evidence_used: list[dict[str, Any]] = field(default_factory=list)  # RAG snippets
    research_used: list[dict[str, Any]] = field(default_factory=list)  # external research
    scores: QualityScores = field(default_factory=QualityScores)
    state: WorkflowState = WorkflowState.PROPOSED
    duration_ms: int = 0
    tokens_used: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode.value,
            "strategy": self.strategy.value,
            "objective": self.objective,
            "final_answer": self.final_answer,
            "agents_involved": self.agents_involved,
            "decisions": [
                {
                    "decision_id": d.decision_id,
                    "title": d.title,
                    "rationale": d.rationale,
                    "decided_by": d.decided_by,
                    "confidence": d.confidence,
                }
                for d in self.decisions
            ],
            "proposals": [p.to_dict() for p in self.proposals],
            "reviews": [r.to_dict() for r in self.reviews],
            "evidence_used": self.evidence_used,
            "research_used": self.research_used,
            "scores": self.scores.to_dict(),
            "state": self.state.value,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "message_count": len(self.messages),
        }


__all__ = [
    "AgentRole",
    "OperationalMode",
    "SwarmStrategy",
    "MessageType",
    "WorkflowState",
    "AgentDefinition",
    "AgentMessage",
    "Decision",
    "QualityScores",
    "Proposal",
    "ReviewReport",
    "SwarmResult",
]
