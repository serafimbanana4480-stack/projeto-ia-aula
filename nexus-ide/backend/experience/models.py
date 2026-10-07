"""Structured trace models for the NEXUS Experience Bus.

Every interaction that flows through the orchestrator is captured as an
:class:`ExperienceTrace` matching the schema defined in FASE 2:

USER → DASHBOARD → API → ORCHESTRATOR → ROUTER → PLANNER → AGENTS → TOOLS
   → EXECUTION → OBSERVATIONS → MEMORY → VERIFIER → RESULT → EXPERIENCE BUS

The trace is the single source of truth for all evolution, evaluation, and
observability downstream.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Helpers ──────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(UTC)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


# ── Enums ────────────────────────────────────────────────────────────────────

class TaskCategory(StrEnum):
    """Broad task categories for filtering and benchmarking."""

    CODING = "coding"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    ARCHITECTURE = "architecture"
    TESTING = "testing"
    REFACTORING = "refactoring"
    REPOSITORY = "repository"
    TOOL_USE = "tool_use"
    MULTI_STEP = "multi_step"
    UNKNOWN = "unknown"


class ComponentKind(StrEnum):
    """Kinds of components that can be evolved."""

    PLANNER = "planner"
    CODER = "coder"
    CRITIC = "critic"
    VERIFIER = "verifier"
    ROUTER = "router"
    DEBUGGER = "debugger"
    RESEARCHER = "researcher"
    DOCUMENTER = "documenter"
    OPTIMIZER = "optimizer"
    GUARDIAN = "guardian"
    OVERSEER = "overseer"
    PROMPT = "prompt"
    SKILL = "skill"
    WORKFLOW = "workflow"
    TOOL = "tool"
    MEMORY = "memory"
    MODEL = "model"


class ComponentStatus(StrEnum):
    """Lifecycle status for versioned components."""

    CHAMPION = "champion"
    CHALLENGER = "challenger"
    EXPERIMENTAL = "experimental"
    ARCHIVED = "archived"
    REJECTED = "rejected"


# ── Core models ──────────────────────────────────────────────────────────────

class ModelInfo(BaseModel):
    """Information about the model used for a task."""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    version: str = ""
    temperature: float = 0.0
    context_size: int = 0
    tier: str = ""  # micro/fast/coder/reasoning/deep


class TrajectoryEntry(BaseModel):
    """A single step in the agent's reasoning-execution cycle."""

    model_config = ConfigDict(extra="allow")

    agent: str = ""
    action: str = ""
    tool: str | None = None
    observation: str | None = None
    duration_ms: int = 0
    tokens_used: int = 0
    success: bool = True
    error: str | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)


class TraceResult(BaseModel):
    """Outcome of a task execution."""

    model_config = ConfigDict(extra="allow")

    success: bool = False
    score: float = 0.0  # 0.0–1.0 composite score
    error: str | None = None
    output: str | None = None


class TraceMetrics(BaseModel):
    """Resource and performance metrics for a trace."""

    model_config = ConfigDict(extra="allow")

    latency_ms: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    tool_calls: int = 0
    retries: int = 0
    cost_usd: float = 0.0
    peak_memory_mb: float = 0.0
    api_calls: int = 0


class TraceEvaluation(BaseModel):
    """Automated evaluation dimensions."""

    model_config = ConfigDict(extra="allow")

    correctness: float = 0.0   # 0.0–1.0
    efficiency: float = 0.0    # 0.0–1.0
    quality: float = 0.0       # 0.0–1.0
    regression: bool = False
    explanation: str = ""


class ExperienceTrace(BaseModel):
    """A complete structured trace of a task execution.

    This is the canonical schema from FASE 2. Every field is explicitly
    named so that queries like *“Why do React tasks fail?”* map directly
    to ``task_type`` / ``result.success`` columns.
    """

    model_config = ConfigDict(extra="allow")

    task_id: str = Field(
        default_factory=lambda: f"task_{_utcnow().strftime('%Y%m%d%H%M%S%f')}_{uuid.uuid4().hex[:8]}"
    )
    timestamp: str = Field(default_factory=_utcnow_iso)
    prompt: str = ""
    task_type: str = ""
    difficulty: float = Field(0.5, ge=0.0, le=1.0)
    category: TaskCategory = TaskCategory.UNKNOWN
    session_id: str = ""

    # ── Model & execution context ──
    model: ModelInfo = Field(default_factory=ModelInfo)
    agents: list[str] = Field(default_factory=list)

    # ── Execution trace ──
    trajectory: list[TrajectoryEntry] = Field(default_factory=list)
    memory_retrieved: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    commands_executed: list[str] = Field(default_factory=list)
    tests_executed: list[str] = Field(default_factory=list)

    # ── Outcome & metrics ──
    result: TraceResult = Field(default_factory=TraceResult)
    metrics: TraceMetrics = Field(default_factory=TraceMetrics)
    evaluation: TraceEvaluation = Field(default_factory=TraceEvaluation)

    # ── Evolution metadata ──
    parent_trace_id: str | None = None
    experiment_id: str | None = None  # set when trace is from an evolution experiment
    component_kind: ComponentKind | None = None
    component_version: str | None = None
    workflow_version: str | None = None
    version_tags: dict[str, str] = Field(default_factory=dict)
    # version_tags: e.g. {"planner": "v2", "coder": "v3", "prompt": "v1", "workflow": "w1"}

    # ── Tags for flexible querying ──
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> list[str]:
        if isinstance(v, dict):
            return list(v.keys())
        if isinstance(v, list):
            return v
        if v is None:
            return []
        return list(v)

    # ── Convenience ──
    @property
    def is_success(self) -> bool:
        return self.result.success

    @property
    def has_regression(self) -> bool:
        return self.evaluation.regression

    def add_trajectory_entry(
        self,
        agent: str,
        action: str,
        tool: str | None = None,
        observation: str | None = None,
        duration_ms: int = 0,
        **kw: Any,
    ) -> TrajectoryEntry:
        """Append a step to the trajectory."""
        entry = TrajectoryEntry(
            agent=agent,
            action=action,
            tool=tool,
            observation=observation,
            duration_ms=duration_ms,
            **kw,
        )
        self.trajectory.append(entry)
        return entry

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-safe)."""
        return self.model_dump(mode="json")

    def compute_content_hash(self) -> str:
        """Stable SHA-256 over the semantic content of this trace.

        ``timestamp`` and ``task_id`` are excluded: a replayed trace (same
        work performed, recorded at a different time) hashes equal, which is
        what lets the trace lake deduplicate identical writes.
        """
        payload = self.model_dump(mode="json")
        payload.pop("timestamp", None)
        payload.pop("task_id", None)
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
