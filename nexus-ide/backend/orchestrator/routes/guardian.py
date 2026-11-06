"""Guardian API routes — system health, suggestions, and structured logs.

The log-shaped endpoints are scoped to the caller: the structured logger is
a process-wide ring buffer shared by every tenant, so an unscoped read
disclosed every other tenant's ``session_id``, ``correlation_id`` and agent
activity.  The scope and the reasoning live in
:mod:`backend.orchestrator.routes.logs`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.agents.guardian import NexusGuardianAgent
from backend.middleware.auth import require_auth
from backend.observability.advanced_logging import get_structured_logger
from backend.orchestrator.routes.logs import (
    _buffer_capacity,
    _owned_entries,
    _owned_stats,
    _require_user,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_guardian(request: Request) -> NexusGuardianAgent | None:
    """Get guardian from app state."""
    return getattr(request.app.state, "guardian_agent", None)


@router.get("/guardian/status")
async def guardian_status(
    request: Request, auth_user: dict[str, Any] = Depends(require_auth)
) -> dict[str, Any]:
    """Get current guardian and system status."""
    guardian = _get_guardian(request)
    if not guardian:
        return {"error": "Guardian not running"}
    return guardian.get_status()


@router.get("/guardian/suggestions")
async def guardian_suggestions(
    request: Request,
    auth_user: dict[str, Any] = Depends(require_auth),
    limit: int = 10,
    category: str | None = None,
    priority: str | None = None,
    pending_only: bool = True,
) -> dict[str, Any]:
    """Get guardian suggestions with optional filtering."""
    guardian = _get_guardian(request)
    if not guardian:
        return {"error": "Guardian not running"}
    return {
        "suggestions": guardian.get_suggestions(
            limit=limit,
            category=category,
            priority=priority,
            pending_only=pending_only,
        ),
    }


@router.post("/guardian/suggestions/{suggestion_id}/apply")
async def apply_suggestion(
    suggestion_id: str, request: Request, auth_user: dict[str, Any] = Depends(require_auth)
) -> dict[str, Any]:
    """Apply a guardian suggestion."""
    guardian = _get_guardian(request)
    if not guardian:
        raise HTTPException(status_code=503, detail="Guardian not running")
    result = guardian.apply_suggestion(suggestion_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/guardian/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    suggestion_id: str, request: Request, auth_user: dict[str, Any] = Depends(require_auth)
) -> dict[str, Any]:
    """Dismiss a guardian suggestion."""
    guardian = _get_guardian(request)
    if not guardian:
        raise HTTPException(status_code=503, detail="Guardian not running")
    result = guardian.dismiss_suggestion(suggestion_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/guardian/logs")
async def guardian_logs(
    request: Request,
    auth_user: dict[str, Any] = Depends(require_auth),
    session_id: str | None = None,
    agent: str | None = None,
    level: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Query structured logs — the caller's own entries only.

    The buffer behind this endpoint is shared by every session of the
    instance, so the entries are filtered by the caller's own sessions
    before they are returned.  A ``session_id`` that belongs to somebody
    else therefore yields an empty list, not somebody else's log.
    """
    user_id = _require_user(auth_user)
    entries = _owned_entries(user_id, session_id=session_id, agent=agent, level=level)
    return {"logs": entries[:limit]}


@router.get("/guardian/metrics")
async def guardian_metrics(
    request: Request, auth_user: dict[str, Any] = Depends(require_auth)
) -> dict[str, Any]:
    """Get real-time guardian metrics.

    The log statistics are the caller's own (see
    :mod:`backend.orchestrator.routes.logs`): a global count would disclose
    how much work the other tenants of this instance are doing.
    """
    guardian = _get_guardian(request)
    slog = get_structured_logger()

    status = guardian.get_status() if guardian else {"running": False}
    user_id = _require_user(auth_user)
    entries = _owned_entries(user_id)
    stats = _owned_stats(entries, _buffer_capacity(slog))

    return {
        "guardian": status,
        "logs": stats,
    }


@router.get("/guardian/health-trend")
async def health_trend(
    request: Request, auth_user: dict[str, Any] = Depends(require_auth), points: int = 10
) -> dict[str, Any]:
    """Get system health trend."""
    guardian = _get_guardian(request)
    if not guardian:
        return {"error": "Guardian not running"}
    return {"trend": guardian.get_health_trend(points=points)}
