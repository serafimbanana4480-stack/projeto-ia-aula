"""Logs API — query structured logs from the in-memory buffer.

GET /api/logs          → recent logs with optional filters
GET /api/logs/stats    → log statistics
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.middleware.auth import require_auth
from backend.observability.advanced_logging import get_structured_logger

logger = logging.getLogger(__name__)
router = APIRouter()


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
    """Return recent structured logs with optional filters."""
    slog = get_structured_logger()
    since: datetime | None = None

    logs = slog.get_logs(
        session_id=session_id,
        agent=agent,
        since=since,
        level=level,
        limit=limit,
    )

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
    """Return the most recent log entries."""
    slog = get_structured_logger()
    entries = slog.get_recent(count=count)
    return {"logs": entries, "total": len(entries)}


@router.get("/logs/stats")
async def get_log_stats(
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return log statistics (counts by level and agent)."""
    slog = get_structured_logger()
    return slog.get_stats()
