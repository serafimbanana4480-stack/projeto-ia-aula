"""Logs API — query structured logs from the in-memory buffer.

GET /api/logs          → recent logs with optional filters
GET /api/logs/stats    → log statistics

Tenant scope
------------
The structured logger is a **process-wide** ring buffer: every session, every
tenant and every agent writes into the same buffer.  Handing that buffer to a
caller therefore hands over every other tenant's ``session_id``,
``correlation_id``, agent name and LLM internals — a fresh registration got a
byte-identical body to the administrator's.

So every read here is scoped to the caller.  The only thing that ties a log
entry to a tenant is the ``session_id`` it carries, and a session belongs to
exactly one user, so the scope is "entries whose session belongs to me".
Entries with no session (process-level startup chatter) belong to nobody and
are therefore **not** shown to anybody: they are not the caller's, and they
may be another tenant's.

The aggregate endpoint (``/api/logs/stats``) is scoped the same way: the
counts it reports are the caller's own.  A global count would disclose how
much work the other tenants of this instance are doing, which is exactly the
kind of aggregate that identifies a neighbour.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.middleware.auth import require_auth
from backend.observability.advanced_logging import get_structured_logger

logger = logging.getLogger(__name__)
router = APIRouter()


def _caller_session_ids(user_id: str) -> set[str]:
    """The ids of the sessions the caller owns.

    Read straight from the ``sessions`` table: ``user_id`` is the owner
    column, so the answer is exactly "the sessions that are mine".
    """
    from backend.persistence.db import get_db

    if not user_id:
        return set()
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM sessions WHERE user_id = ?", (user_id,)
            ).fetchall()
    except Exception:
        logger.warning("Could not read the caller's sessions", exc_info=True)
        return set()
    return {str(row["id"]) for row in rows}


def _buffer_capacity(slog: Any) -> int:
    """How many entries the ring buffer can hold (the read window)."""
    try:
        return int(slog.get_stats().get("capacity") or 10_000)
    except Exception:  # pragma: no cover - defensive
        return 10_000


def _owned_entries(
    user_id: str,
    *,
    session_id: str | None = None,
    agent: str | None = None,
    level: str | None = None,
) -> list[dict[str, Any]]:
    """Every log entry that belongs to the caller, newest first.

    The window is the whole buffer: filtering *after* the query is what
    makes the result correct, because the buffer is shared and the caller's
    entries are interleaved with everybody else's.
    """
    slog = get_structured_logger()
    owned = _caller_session_ids(user_id)
    if not owned:
        return []
    entries = slog.get_logs(
        session_id=session_id,
        agent=agent,
        level=level,
        limit=_buffer_capacity(slog),
    )
    return [
        entry
        for entry in entries
        if str(entry.get("session_id") or "") in owned
    ]


def _owned_stats(entries: list[dict[str, Any]], capacity: int) -> dict[str, Any]:
    """Log statistics over the caller's own entries.

    Same shape as ``StructuredLogger.get_stats()`` (the frontend renders
    both), computed over the scoped entries instead of the whole buffer.
    """
    if not entries:
        return {"total": 0, "by_level": {}, "by_agent": {}, "capacity": capacity}

    levels: dict[str, int] = {}
    agents: dict[str, int] = {}
    for entry in entries:
        level = str(entry.get("level") or "")
        levels[level] = levels.get(level, 0) + 1
        agent = str(entry.get("agent") or "")
        if agent:
            agents[agent] = agents.get(agent, 0) + 1

    return {
        "total": len(entries),
        "by_level": levels,
        "by_agent": agents,
        "capacity": capacity,
    }


def _require_user(user: dict[str, Any] | None) -> str:
    """The caller's user id, or a 401 when the guard produced nothing."""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@router.get("/logs")
async def get_logs(
    level: str | None = Query(
        None, description="Filter by level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    ),
    agent: str | None = Query(None, description="Filter by agent name"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(50, ge=1, le=500, description="Max entries"),
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return recent structured logs with optional filters.

    Scoped to the caller: only the entries whose session belongs to the
    authenticated user are returned.  A ``session_id`` filter is intersected
    with that scope — asking for somebody else's session returns nothing
    rather than somebody else's log.
    """
    user_id = _require_user(_user)
    entries = _owned_entries(user_id, session_id=session_id, agent=agent, level=level)
    logs = entries[:limit]

    return {
        "logs": logs,
        "total": len(logs),
        "filters": {
            "level": level,
            "agent": agent,
            "session_id": session_id,
            "limit": limit,
        },
    }


@router.get("/logs/recent")
async def get_recent_logs(
    count: int = Query(50, ge=1, le=200, description="Number of recent entries"),
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return the most recent log entries of the caller.

    Scoped to the caller, like ``/api/logs``: the ring buffer is shared by
    every tenant, so an unscoped read was every tenant's log.
    """
    user_id = _require_user(_user)
    entries = _owned_entries(user_id)
    recent = entries[:count]

    return {"logs": recent, "total": len(recent)}


@router.get("/logs/stats")
async def get_log_stats(
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return log statistics for the caller's own sessions.

    The counts are the caller's own.  A global count (how many entries the
    buffer holds, how many each agent produced) discloses the activity of
    the other tenants of this instance, so the aggregate is computed over
    the scoped entries instead of over the whole buffer.
    """
    user_id = _require_user(_user)
    slog = get_structured_logger()
    entries = _owned_entries(user_id)
    return _owned_stats(entries, _buffer_capacity(slog))
