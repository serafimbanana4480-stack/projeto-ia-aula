"""Immutable execution envelopes and truthful terminal-state rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, is_dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class ExecutionMode(StrEnum):
    """User-visible execution lane."""

    CHAT = "chat"
    ASSISTED = "assisted"
    MISSION = "mission"


class ExecutionState(StrEnum):
    """States a run may occupy from dispatch through terminal completion."""

    QUEUED = "queued"
    ROUTING = "routing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ErrorCategory(StrEnum):
    """Stable categories for errors exposed by the execution envelope."""

    PROVIDER = "provider"
    MODEL = "model"
    TOOL = "tool"
    VALIDATION = "validation"
    VERIFICATION = "verification"
    PROJECT_CONTEXT = "project_context"
    PLANNING = "planning"
    DISK_PRESSURE = "disk_pressure"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


_TERMINAL_STATES = frozenset(
    {
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.BLOCKED,
        ExecutionState.CANCELLED,
        ExecutionState.INTERRUPTED,
    }
)


def is_terminal_state(state: ExecutionState | str) -> bool:
    """Return whether ``state`` is a terminal execution state."""

    try:
        normalized = state if isinstance(state, ExecutionState) else ExecutionState(state)
    except (TypeError, ValueError):
        return False
    return normalized in _TERMINAL_STATES


def terminal_state_for(state: ExecutionState | str | None) -> ExecutionState | None:
    """Return ``state`` only when it is terminal; otherwise return ``None``."""

    if state is None:
        return None
    try:
        normalized = state if isinstance(state, ExecutionState) else ExecutionState(state)
    except (TypeError, ValueError):
        return None
    return normalized if normalized in _TERMINAL_STATES else None


def _json_safe(value: Any) -> Any:
    """Convert contract values recursively into JSON-compatible primitives."""

    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return str(value)


@dataclass(frozen=True, slots=True)
class RunContext:
    """Correlation identifiers and lane metadata shared by every run event."""

    session_id: str
    run_id: str
    correlation_id: str
    mission_id: str | None
    project_path: str | None
    mode: ExecutionMode

    def __post_init__(self) -> None:
        for name in ("session_id", "run_id", "correlation_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "mission_id": self.mission_id,
            "project_path": self.project_path,
            "mode": self.mode.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RunContext:
        return cls(
            session_id=str(value["session_id"]),
            run_id=str(value["run_id"]),
            correlation_id=str(value["correlation_id"]),
            mission_id=value.get("mission_id"),
            project_path=value.get("project_path"),
            mode=ExecutionMode(value["mode"]),
        )


@dataclass(frozen=True, slots=True)
class ExecutionError:
    """Structured error attached to a failed or blocked outcome."""

    category: ErrorCategory
    message: str
    provider: str | None = None
    model: str | None = None
    retry_after: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(
            {
                "category": self.category,
                "message": self.message,
                "provider": self.provider,
                "model": self.model,
                "retry_after": self.retry_after,
                "details": self.details,
            }
        )


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Complete execution snapshot with a guarded completion claim."""

    state: ExecutionState
    context: RunContext
    provider: str | None = None
    model: str | None = None
    error: ExecutionError | None = None
    evidence: list[Any] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    failed_tasks: list[Any] = field(default_factory=list)
    completion_proven: bool = False

    def _completion_is_proven(self) -> bool:
        try:
            state = (
                self.state
                if isinstance(self.state, ExecutionState)
                else ExecutionState(self.state)
            )
        except (TypeError, ValueError):
            return False
        evidence_proven = any(
            (
                item.get("verified") is True
                if isinstance(item, Mapping) and "verified" in item
                else True
            )
            for item in self.evidence
        )
        return (
            state is ExecutionState.COMPLETED
            and self.error is None
            and not self.failed_tasks
            and evidence_proven
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(
            {
                "state": self.state,
                "context": self.context,
                "provider": self.provider,
                "model": self.model,
                "error": self.error,
                "evidence": self.evidence,
                "files_changed": self.files_changed,
                "commands_run": self.commands_run,
                "failed_tasks": self.failed_tasks,
                "completion_proven": self._completion_is_proven(),
            }
        )
