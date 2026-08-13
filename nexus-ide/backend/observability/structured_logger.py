"""StructuredLogger — JSONL logging with correlation IDs.

Every log entry is a JSON object with:
- timestamp, level, message, logger name
- trace_id and span_id for distributed tracing
- structured context (arbitrary key-value pairs)
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

# Thread-local storage for correlation context
_correlation_context: dict[str, str] = {}


class StructuredLogFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "source": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        # Add correlation IDs if present
        if hasattr(record, "trace_id") and record.trace_id:
            log_entry["trace_id"] = record.trace_id
        if hasattr(record, "span_id") and record.span_id:
            log_entry["span_id"] = record.span_id

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process",
                "message", "asctime", "trace_id", "span_id",
            ):
                log_entry[key] = value

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


class StructuredLogger:
    """Logger with structured output and correlation IDs."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _log(self, level: int, message: str, **kwargs: Any) -> None:
        """Log with structured context."""
        extra = {}

        # Add correlation context
        trace_id = kwargs.pop("trace_id", _correlation_context.get("trace_id"))
        span_id = kwargs.pop("span_id", _correlation_context.get("span_id"))

        if trace_id:
            extra["trace_id"] = trace_id
        if span_id:
            extra["span_id"] = span_id

        # Add all remaining kwargs as structured fields
        extra.update(kwargs)

        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, message, **kwargs)


# Global convenience
def get_structured_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)


def set_correlation_context(trace_id: str | None = None, span_id: str | None = None) -> None:
    """Set correlation IDs for the current execution context."""
    if trace_id:
        _correlation_context["trace_id"] = trace_id
    if span_id:
        _correlation_context["span_id"] = span_id


def clear_correlation_context() -> None:
    """Clear correlation IDs."""
    _correlation_context.clear()


def configure_structured_logging(level: int = logging.INFO) -> None:
    """Configure root logger for structured JSON output."""
    handler = logging.StreamHandler(sys.stdout)
    handler._nexus_owned = True  # type: ignore[attr-defined]
    handler.setFormatter(StructuredLogFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_nexus_owned", False):
            root.removeHandler(existing)
            existing.close()
    root.addHandler(handler)
    root.setLevel(level)
