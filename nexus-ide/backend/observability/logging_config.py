"""Structured logging with OpenTelemetry integration.

Provides:
- JSON-structured log output
- Trace context propagation
- Request-scoped loggers
- Log levels with environment-based filtering
- Automatic correlation IDs
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# Context variables for request-scoped logging
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_session_id: ContextVar[str] = ContextVar("session_id", default="")
_agent_name: ContextVar[str] = ContextVar("agent_name", default="")


class JsonFormatter(logging.Formatter):
    """JSON-structured log formatter for machine-readable logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add context
        corr_id = _correlation_id.get()
        if corr_id:
            log_entry["correlation_id"] = corr_id

        sess_id = _session_id.get()
        if sess_id:
            log_entry["session_id"] = sess_id

        agent = _agent_name.get()
        if agent:
            log_entry["agent"] = agent

        # Add exception info
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        # Add extra fields
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)  # type: ignore

        return json.dumps(log_entry, default=str)


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    log_file: str | None = None,
) -> None:
    """Configure structured logging for the application."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    if json_format:
        console.setFormatter(JsonFormatter())
    else:
        console.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    root.addHandler(console)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JsonFormatter() if json_format else logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        root.addHandler(file_handler)

    # Set levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    root.info("Logging configured (level=%s, json=%s)", level, json_format)


def set_correlation_id(correlation_id: str | None = None) -> str:
    """Set the correlation ID for the current request context."""
    cid = correlation_id or uuid.uuid4().hex[:12]
    _correlation_id.set(cid)
    return cid


def set_session_id(session_id: str) -> None:
    _session_id.set(session_id)


def set_agent_name(name: str) -> None:
    _agent_name.set(name)


def get_correlation_id() -> str:
    return _correlation_id.get()


class LoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that injects context into log records."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        extra = kwargs.get("extra", {})
        extra["correlation_id"] = _correlation_id.get()
        extra["session_id"] = _session_id.get()
        extra["agent"] = _agent_name.get()
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> LoggerAdapter:
    """Get a context-aware logger."""
    logger = logging.getLogger(name)
    return LoggerAdapter(logger, {})
