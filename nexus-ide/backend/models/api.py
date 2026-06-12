"""Pydantic API models shared by routes, agents and tests.

Kept in a single module so both callers and tests can import without cycles.
See ARCHITECTURE.md §7.3 for the API contracts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentName = Literal[
    "ROUTER",
    "ARCHITECT",
    "ARCHITECT_DESIGN",
    "ARCHITECT_COMPLEXITY",
    "RESEARCHER",
    "RESEARCHER_WEB",
    "CODER",
    "ANALYZER",
    "DEBUGGER",
    "DOCUMENTER",
    "OPTIMIZER",
    "REFACTOR_PERFORMANCE",
    "REFACTOR_CLEAN",
    "DASHBOARD",
    "MICRO",
    "ORCHESTRATOR",
    "SWARM",
    "SUPERVISOR",
    "GUARDIAN",
    "TEST_RUNNER_UNIT",
    "TEST_RUNNER_E2E",
    "OVERSEER",
    "BUG_HUNTER_STATIC",
    "BUG_HUNTER_RUNTIME",
    "META_ANALYZER",
]
ThinkingMode = Literal["fast", "deep", "iterative"]
ContextNeed = Literal["low", "medium", "high"]
EventType = Literal[
    "routing",
    "agent_started",
    "token",
    "tool_call",
    "tool_result",
    "tool_error",
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
    model: str = Field(default="", max_length=128, description="Model tier key (e.g. 'coder','deep','reasoning') selected by the user in the UI. Empty string means auto-route.")
    project_path: str = Field(default="", max_length=2000, description="Absolute path to the active project directory. Empty string means no project context.")
    provider: str = Field(default="", max_length=128, description="LLM provider to use (e.g. 'ollama', 'openai', 'kimi'). Empty string means use default.")
    swarm_agents: list[str] = Field(default_factory=list, description="Agent names to use in swarm mode")
    swarm_strategy: str = Field(default="divide", description="Swarm strategy: divide, ensemble, pipeline, debate")


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
    # Tool-call events (type in tool_call / tool_result / tool_error)
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any | None = None
    tool_error: str | None = None
    timestamp: str = Field(default_factory=_utcnow_iso)


# ---------------------------------------------------------------------------
# Workspace Manager models
# ---------------------------------------------------------------------------


class WorkspaceReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)


class WorkspaceWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)
    content: str


class WorkspaceListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(default=".", min_length=1, max_length=2000)
    recursive: bool = False


class WorkspaceDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)
    move_to_trash: bool = True


class WorkspaceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1, max_length=500)
    root_path: str = Field(min_length=1, max_length=2000)
    max_results: int = Field(default=100, ge=1, le=1000)


class WorkspaceShellRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=10_000)
    cwd: str | None = Field(default=None, max_length=2000)
    timeout: int = Field(default=120, ge=1, le=600)
    env: dict[str, str] | None = None


class WorkspacePythonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=50_000)
    cwd: str | None = Field(default=None, max_length=2000)
    timeout: int = Field(default=120, ge=1, le=600)


class WorkspaceScriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)
    args: list[str] = Field(default_factory=list)
    cwd: str | None = Field(default=None, max_length=2000)
    timeout: int = Field(default=120, ge=1, le=600)


class WorkspaceGitInitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)


class WorkspaceGitCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)
    path: str = Field(min_length=1, max_length=2000)


class WorkspaceGitCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)
    message: str = Field(default="auto: changes from NEXUS workspace", max_length=500)


class WorkspaceGitPushRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)
    remote: str = Field(default="origin", max_length=128)
    branch: str | None = Field(default=None, max_length=128)


class WorkspaceGitStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)


class WorkspaceDiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_path: str = Field(min_length=1, max_length=2000)


class WorkspaceProjectInfoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)


class UserPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferences: dict[str, Any] = Field(default_factory=dict)


class RoutineCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    schedule_cron: str = ""


class MemoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=10_000)
    memory_type: Literal["preference", "fact", "routine", "insight"] = "fact"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
