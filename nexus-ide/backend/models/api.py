"""Pydantic API models shared by routes, agents and tests.

Kept in a single module so both callers and tests can import without cycles.
See ARCHITECTURE.md §7.3 for the API contracts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentName = Literal[
    "ROUTER",
    "ARCHITECT",
    "RESEARCHER",
    "CODER",
    "ANALYZER",
    "DEBUGGER",
    "DOCUMENTER",
    "OPTIMIZER",
    "DASHBOARD",
    "MICRO",
]
ThinkingMode = Literal["fast", "deep", "iterative"]
ContextNeed = Literal["low", "medium", "high"]
EventType = Literal[
    "routing",
    "agent_started",
    "token",
    "agent_finished",
    "error",
    "done",
]


def _utcnow_iso() -> str:
    """ISO-8601 timestamp with explicit UTC marker."""
    return datetime.now(UTC).isoformat()


class ChatRequest(BaseModel):
    """Incoming POST /api/chat body."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=50_000)
    session_id: str = Field(min_length=1, max_length=128, default="default")
    mode: str = Field(default="agent", min_length=1, max_length=32)


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=2000)
    description: str = ""
    mode: str = "auto"
    preferred_model: str = ""
    trust: bool = False


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    mode: str | None = None
    preferred_model: str | None = None
    trust: bool | None = None


class FileReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)
    project_path: str = Field(default=".", min_length=1, max_length=2000)


class FileWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)
    content: str
    project_path: str = Field(default=".", min_length=1, max_length=2000)
    session_id: str | None = None
    project_id: str | None = None


class FileListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(default=".", min_length=1, max_length=2000)
    project_path: str = Field(default=".", min_length=1, max_length=2000)
    recursive: bool = True


class FileTreeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    name: str
    type: Literal["file", "directory"]
    size: int = 0
    children: list[FileTreeEntry] = Field(default_factory=list)


class TerminalExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=10_000)
    project_path: str = Field(default=".", min_length=1, max_length=2000)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    session_id: str | None = None


class TerminalExecuteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: int
    risk_level: str


class RoutingDecision(BaseModel):
    """Output of the ROUTER model. Validated with Pydantic on parse."""

    model_config = ConfigDict(extra="ignore")

    primary_agent: AgentName
    secondary_agents: list[AgentName] = Field(default_factory=list)
    requires_web_search: bool = False
    thinking_mode: ThinkingMode = "fast"
    estimated_complexity: int = Field(ge=1, le=10, default=3)
    task_type: str = "general"
    context_needed: ContextNeed = "low"
    routing_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    routing_reason: str = ""


class StreamEvent(BaseModel):
    """Envelope for every SSE chunk sent to the frontend.

    The frontend discriminates on ``type``:

    - ``routing``: payload has the RoutingDecision snapshot.
    - ``agent_started`` / ``agent_finished``: lifecycle markers.
    - ``token``: ``content`` holds one or more characters of output.
    - ``error``: ``content`` holds a human-readable error message.
    - ``done``: terminal event; client closes the connection.
    """

    type: EventType
    agent: AgentName | None = None
    content: str | None = None
    routing: RoutingDecision | None = None
    timestamp: str = Field(default_factory=_utcnow_iso)
