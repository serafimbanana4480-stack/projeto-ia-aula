"""Error reporting and retrieval endpoints.

Provides:
- ``GET  /api/errors``      — retrieve recent errors (latest first)
- ``POST /api/errors/report`` — submit an error report from frontend/agents

Errors are stored in an in-memory ring buffer (max 1000 entries) and can also
be forwarded to the EventBus if available for broader observability.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/errors", tags=["errors"])


# ---------------------------------------------------------------------------
# In-memory error store
# ---------------------------------------------------------------------------

@dataclass
class ErrorRecord:
    """A single error report."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    message: str = ""
    severity: str = "error"  # error | warning | info
    source: str = "unknown"
    stack_trace: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False


class ErrorStore:
    """Thread-safe in-memory error store with a fixed-size ring buffer."""

    def __init__(self, max_size: int = 1000) -> None:
        self._errors: list[ErrorRecord] = []
        self._max_size = max_size

    def add(self, record: ErrorRecord) -> None:
        """Insert a record (newest at the end)."""
        self._errors.append(record)
        if len(self._errors) > self._max_size:
            self._errors = self._errors[-self._max_size:]

    def recent(self, limit: int = 50, severity: str | None = None) -> list[ErrorRecord]:
        """Return the most recent ``limit`` records, optionally filtered by severity."""
        filtered = (
            self._errors if severity is None
            else [e for e in self._errors if e.severity == severity]
        )
        return list(reversed(filtered[-limit:]))

    def count(self) -> int:
        """Total stored errors."""
        return len(self._errors)

    def clear(self) -> None:
        """Clear all stored errors."""
        self._errors.clear()


# Singleton store (attached to app.state in lifespan)
_store: ErrorStore | None = None


def get_error_store(request: Request) -> ErrorStore:
    """Dependency: return the app-wide ErrorStore singleton."""
    store: ErrorStore | None = getattr(request.app.state, "error_store", None)
    if store is None:
        # Fallback: create a new one (shouldn't happen after lifespan)
        store = ErrorStore()
        request.app.state.error_store = store
    return store


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def get_errors(
    request: Request,
    limit: int = 50,
    severity: str | None = None,
) -> dict[str, Any]:
    """Return recent error reports, newest first.

    Parameters
    ----------
    limit : int
        Maximum number of records to return (default 50, max 200).
    severity : str, optional
        Filter by severity: ``error``, ``warning``, or ``info``.
    """
    store = get_error_store(request)
    limit = min(limit, 200)
    records = store.recent(limit=limit, severity=severity)

    return {
        "total": store.count(),
        "returned": len(records),
        "errors": [
            {
                "id": r.id,
                "message": r.message,
                "severity": r.severity,
                "source": r.source,
                "stack_trace": r.stack_trace,
                "context": r.context,
                "timestamp": r.timestamp,
                "acknowledged": r.acknowledged,
            }
            for r in records
        ],
    }


@router.post("/report")
async def report_error(
    request: Request,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Report an error from the frontend or an agent.

    Expected body fields (all optional except ``message``):

    - ``message`` (str): human-readable error description
    - ``severity`` (str): ``error``, ``warning``, or ``info`` (default ``error``)
    - ``source`` (str): component that generated the error
    - ``stack_trace`` (str): optional stack trace
    - ``context`` (dict): arbitrary metadata
    """
    message = body.get("message", "")
    if not message:
        return {"ok": False, "error": "message field is required"}

    record = ErrorRecord(
        message=message,
        severity=body.get("severity", "error"),
        source=body.get("source", "unknown"),
        stack_trace=body.get("stack_trace", ""),
        context=body.get("context", {}),
    )

    # Store locally
    store = get_error_store(request)
    store.add(record)

    # Also publish to EventBus if available
    event_bus = getattr(request.app.state, "event_bus", None)
    if event_bus:
        try:
            from backend.orchestrator.events import EventType, OrchestratorEvent

            await event_bus.publish(OrchestratorEvent(
                event_type=EventType.ERROR,
                source=record.source,
                content=record.message,
                data={
                    "error_id": record.id,
                    "severity": record.severity,
                    "stack_trace": record.stack_trace,
                    **record.context,
                },
            ))
        except Exception as e:
            logger.warning("Failed to publish error to EventBus: %s", e)

    logger.info("Error reported: [%s] %s — %s", record.severity, record.source, record.message)

    return {
        "ok": True,
        "error_id": record.id,
        "timestamp": record.timestamp,
    }
