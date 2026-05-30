"""Structured logging with correlation IDs, agent tracing, and queryable log store."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.models.api import RoutingDecision

logger = logging.getLogger(__name__)

# Thread-local storage for correlation context
_context = threading.local()


def get_correlation_id() -> str:
    """Get or create a correlation ID for the current context."""
    if not hasattr(_context, "correlation_id"):
        _context.correlation_id = uuid.uuid4().hex[:16]
    return _context.correlation_id


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID for the current context."""
    _context.correlation_id = cid


def clear_correlation_id() -> None:
    """Clear the correlation ID."""
    if hasattr(_context, "correlation_id"):
        del _context.correlation_id


@dataclass
class LogEntry:
    timestamp: str
    level: str
    message: str
    correlation_id: str = ""
    agent: str = ""
    session_id: str = ""
    task_id: str = ""
    source: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "correlation_id": self.correlation_id,
            "agent": self.agent,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "source": self.source,
            "extra": self.extra,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class StructuredLogger:
    """JSON-structured logging with correlation IDs and agent tracing.

    Usage:
        slog = StructuredLogger()
        slog.info("Processing request", agent="ROUTER", session_id="abc123")
        slog.agent_start("CODER", "abc123", "Write a function")
        slog.tool_call("write_file", "abc123", {"path": "test.py"})
    """

    def __init__(self, max_buffer: int = 10000) -> None:
        self._buffer: deque[LogEntry] = deque(maxlen=max_buffer)
        self._listeners: list[Callable[[LogEntry], None]] = []

    def add_listener(self, callback: Callable[[LogEntry], None]) -> None:
        """Add a callback that receives every log entry."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[LogEntry], None]) -> None:
        """Remove a listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _emit(self, entry: LogEntry) -> None:
        """Store and broadcast a log entry."""
        self._buffer.append(entry)
        for listener in self._listeners:
            try:
                listener(entry)
            except Exception:
                pass

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def log(
        self,
        level: str,
        message: str,
        *,
        agent: str = "",
        session_id: str = "",
        task_id: str = "",
        source: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log a structured message."""
        entry = LogEntry(
            timestamp=self._now(),
            level=level.upper(),
            message=message,
            correlation_id=get_correlation_id(),
            agent=agent,
            session_id=session_id,
            task_id=task_id,
            source=source or agent,
            extra=extra or {},
        )
        self._emit(entry)

        # Also emit to standard Python logger
        std_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(std_level, "[%s|%s|%s] %s", agent, session_id, task_id, message)

    def debug(self, message: str, **kwargs: Any) -> None:
        self.log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self.log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self.log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self.log("ERROR", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self.log("CRITICAL", message, **kwargs)

    # ------------------------------------------------------------------
    # Specialized logging helpers
    # ------------------------------------------------------------------

    def agent_start(self, agent: str, session_id: str, query: str, **extra: Any) -> None:
        self.info(
            f"Agent {agent} started | query: {query[:200]}",
            agent=agent,
            session_id=session_id,
            source="agent_lifecycle",
            extra={"event": "agent_start", "query": query, **extra},
        )

    def agent_end(
        self,
        agent: str,
        session_id: str,
        tokens: int,
        duration_ms: int,
        success: bool,
        **extra: Any,
    ) -> None:
        self.info(
            f"Agent {agent} finished | tokens={tokens} duration={duration_ms}ms success={success}",
            agent=agent,
            session_id=session_id,
            source="agent_lifecycle",
            extra={
                "event": "agent_end",
                "tokens": tokens,
                "duration_ms": duration_ms,
                "success": success,
                **extra,
            },
        )

    def tool_call(
        self,
        tool: str,
        session_id: str,
        args: dict[str, Any],
        result: dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        self.info(
            f"Tool call: {tool}",
            session_id=session_id,
            source="tool_execution",
            extra={
                "event": "tool_call",
                "tool": tool,
                "args": args,
                "result": result,
                **extra,
            },
        )

    def routing_decision(
        self,
        query: str,
        decision: RoutingDecision,
        latency_ms: int,
        **extra: Any,
    ) -> None:
        self.info(
            f"Routing: {decision.primary_agent} (confidence={decision.routing_confidence})",
            agent="ROUTER",
            source="routing",
            extra={
                "event": "routing_decision",
                "query": query[:200],
                "primary_agent": decision.primary_agent,
                "confidence": decision.routing_confidence,
                "reason": decision.routing_reason,
                "latency_ms": latency_ms,
                **extra,
            },
        )

    def llm_request(
        self,
        provider: str,
        model: str,
        session_id: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        success: bool,
        **extra: Any,
    ) -> None:
        level = "INFO" if success else "WARNING"
        self.log(
            level,
            f"LLM request: {provider}/{model} | in={tokens_in} out={tokens_out} | {latency_ms}ms",
            agent="LLM",
            session_id=session_id,
            source="llm",
            extra={
                "event": "llm_request",
                "provider": provider,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "latency_ms": latency_ms,
                "success": success,
                **extra,
            },
        )

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_logs(
        self,
        session_id: str | None = None,
        agent: str | None = None,
        since: datetime | None = None,
        level: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query logs with filters."""
        results: list[LogEntry] = []
        for entry in reversed(self._buffer):
            if session_id and entry.session_id != session_id:
                continue
            if agent and entry.agent != agent:
                continue
            if since:
                entry_dt = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00"))
                if entry_dt < since:
                    continue
            if level and entry.level != level.upper():
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return [e.to_dict() for e in results]

    def get_recent(self, count: int = 50) -> list[dict[str, Any]]:
        """Get most recent log entries."""
        recent = list(self._buffer)[-count:]
        return [e.to_dict() for e in recent]

    def get_stats(self) -> dict[str, Any]:
        """Get log statistics."""
        if not self._buffer:
            return {"total": 0}

        levels: dict[str, int] = {}
        agents: dict[str, int] = {}
        for entry in self._buffer:
            levels[entry.level] = levels.get(entry.level, 0) + 1
            if entry.agent:
                agents[entry.agent] = agents.get(entry.agent, 0) + 1

        return {
            "total": len(self._buffer),
            "by_level": levels,
            "by_agent": agents,
            "capacity": self._buffer.maxlen,
        }


# Global singleton
_structured_logger: StructuredLogger | None = None


def get_structured_logger() -> StructuredLogger:
    """Get the global structured logger instance."""
    global _structured_logger
    if _structured_logger is None:
        _structured_logger = StructuredLogger()
    return _structured_logger


def set_structured_logger(logger: StructuredLogger) -> None:
    """Set the global structured logger instance."""
    global _structured_logger
    _structured_logger = logger
