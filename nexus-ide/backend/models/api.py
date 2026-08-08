"""Pydantic API models shared by routes, agents and tests.

Kept in a single module so both callers and tests can import without cycles.
See ARCHITECTURE.md §7.3 for the API contracts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AgentName = Literal[
    "ROUTER",
    "PLANNER",
    "ARCHITECT",
    "ARCHITECT_DESIGN",
    "ARCHITECT_COMPLEXITY",
    "RESEARCHER",
    "RESEARCHER_WEB",
    "CODER",
    "REVIEWER",
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
    "thinking",
    "tool_call",
    "tool_result",
    "tool_error",
    "tool_confirmation",
    "progress",
    "agent_finished",
    "error",
    "metric",
    "done",
    "execution_state",
    "execution_error",
    "execution_completed",
    # Mission Control. These carry the *why* of a run — the interpreted
    # objective, the measured project state, the plan, and the contract each
    # agent was spawned under. Emitted before any agent exists, so the client
    # can render intent rather than only activity.
    "mission_brief",
    "mission_plan",
    "mission_wave",
    "mission_agent",
    "mission_decision",
    "mission_verification",
    "mission_completed",
]


def _utcnow_iso() -> str:
    """ISO-8601 timestamp with explicit UTC marker."""
    return datetime.now(UTC).isoformat()


class ChatRequest(BaseModel):
    """Incoming POST /api/chat body."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=50_000)
    session_id: str = Field(min_length=1, max_length=128, default="default")
    mode: str = Field(default="auto", min_length=1, max_length=32)
    model: str = Field(
        default="",
        max_length=128,
        description=(
            "Either a concrete provider model id ('anthropic/claude-sonnet-4', "
            "'qwen2.5:7b') or a router tier key ('coder', 'deep', 'reasoning'). "
            "A concrete id is used verbatim; a tier is resolved via "
            "config/models.yaml. Empty string or 'auto' means auto-route."
        ),
    )
    project_path: str = Field(
        default="",
        max_length=2000,
        description="Absolute path to the active project directory. Empty string means no project context.",
    )
    provider: str = Field(
        default="",
        max_length=128,
        description="LLM provider to use (e.g. 'ollama', 'openai', 'kimi'). Empty string means use default.",
    )
    thinking_strength: str = Field(
        default="",
        max_length=32,
        description="Thinking depth: '' (auto), 'low', 'medium', 'high'",
    )
    autonomous: bool = Field(
        default=True,
        description=(
            "Continue without human feedback for reversible work. Set false "
            "to use interactive confirmation gates for every risky tool."
        ),
    )
    swarm_agents: list[str] = Field(
        default_factory=list, description="Agent names to use in swarm mode"
    )
    swarm_strategy: str = Field(
        default="adaptive",
        description="Swarm strategy: divide, ensemble, pipeline, debate, adaptive",
    )
    swarm_operational_mode: str = Field(
        default="",
        max_length=32,
        description=(
            "Optional SWARM operational mode: architecture, investigation, "
            "implementation, review, bugfix, planning, research"
        ),
    )

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        import re

        if not re.match(r"^[a-zA-Z0-9_-]{1,128}$", v):
            raise ValueError("session_id must be 1-128 alphanumeric/underscore/hyphen characters")
        return v

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, v: str) -> str:
        if v and ".." in v:
            raise ValueError("project_path must not contain '..' segments")
        return v


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
    overwrite: bool = True


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
    execution: dict[str, Any] | None = None
    # Tool-call events (type in tool_call / tool_result / tool_error)
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any | None = None
    tool_error: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
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


class WorkspaceDeleteDirRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)
    move_to_trash: bool = True


class WorkspaceMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    src: str = Field(min_length=1, max_length=2000)
    dest: str = Field(min_length=1, max_length=2000)


class WorkspaceCopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    src: str = Field(min_length=1, max_length=2000)
    dest: str = Field(min_length=1, max_length=2000)


class WorkspaceFileInfoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)


class WorkspaceListBackupsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2000)


class WorkspaceRestoreBackupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_path: str = Field(min_length=1, max_length=2000)
    target_path: str = Field(min_length=1, max_length=2000)


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
