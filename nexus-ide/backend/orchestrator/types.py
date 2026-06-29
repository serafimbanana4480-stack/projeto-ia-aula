"""Shared types and structured logging for the orchestrator package."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _structured_log(level: str, msg: str, **extra: Any) -> None:
    ts = datetime.now(UTC).isoformat(timespec="seconds")
    payload: dict[str, Any] = {"ts": ts, "level": level, "msg": msg}
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, default=str))


class StructuredLogger:
    """Drop-in helper that emits JSON-lines structured logs to stdout."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _emit(self, level: str, msg: str, **extra: Any) -> None:
        if os.environ.get("NEXUS_STRUCTURED_LOG", "1") == "1":
            _structured_log(level, msg, **extra)
        else:
            self._logger.log(getattr(logging, level.upper(), logging.INFO), msg, extra=extra)

    def debug(self, msg: str, **extra: Any) -> None:
        self._emit("DEBUG", msg, **extra)

    def info(self, msg: str, **extra: Any) -> None:
        self._emit("INFO", msg, **extra)

    def warning(self, msg: str, **extra: Any) -> None:
        self._emit("WARNING", msg, **extra)

    def error(self, msg: str, **extra: Any) -> None:
        self._emit("ERROR", msg, **extra)

    def critical(self, msg: str, **extra: Any) -> None:
        self._emit("CRITICAL", msg, **extra)


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)


class OrchestrationState(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionContext:
    """Shared state accessible to all agents during orchestration."""

    session_id: str
    project_path: str = "."
    shared_memory: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    _global_context_parts: list[str] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def global_context(self) -> str:
        return "".join(self._global_context_parts)

    @global_context.setter
    def global_context(self, value: str) -> None:
        if not self._global_context_parts:
            self._global_context_parts.append(value)
        else:
            self._global_context_parts.append(value)


@dataclass
class OrchestrationResult:
    """Aggregated result of an orchestration run."""

    run_id: str
    state: OrchestrationState
    plan: Any | None = None
    completed_tasks: int = 0
    failed_tasks: int = 0
    total_duration_ms: int = 0
    tokens_used: int = 0
    errors: list[str] = field(default_factory=list)
    task_results: dict[str, Any] = field(default_factory=dict)
