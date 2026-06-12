"""Guardian API routes — system health, suggestions, and structured logs."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.agents.guardian import NexusGuardianAgent
from backend.observability.advanced_logging import get_structured_logger

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_guardian(request: Request) -> NexusGuardianAgent | None:
    """Get guardian from app state."""
    return getattr(request.app.state, "guardian_agent", None)


@router.get("/guardian/status")
async def guardian_status(request: Request) -> dict[str, Any]:
    """Get current guardian and system status."""
    guardian = _get_guardian(request)
    if not guardian:
        return {"error": "Guardian not running"}
    return guardian.get_status()


@router.get("/guardian/suggestions")
async def guardian_suggestions(
    request: Request,
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
async def apply_suggestion(suggestion_id: str, request: Request) -> dict[str, Any]:
    """Apply a guardian suggestion."""
    guardian = _get_guardian(request)
    if not guardian:
        raise HTTPException(status_code=503, detail="Guardian not running")
    result = guardian.apply_suggestion(suggestion_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/guardian/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(suggestion_id: str, request: Request) -> dict[str, Any]:
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
    session_id: str | None = None,
    agent: str | None = None,
    level: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Query structured logs."""
    slog = get_structured_logger()
    return {
        "logs": slog.get_logs(
            session_id=session_id,
            agent=agent,
            level=level,
            limit=limit,
        ),
    }


@router.get("/guardian/metrics")
async def guardian_metrics(request: Request) -> dict[str, Any]:
    """Get real-time guardian metrics."""
    guardian = _get_guardian(request)
    slog = get_structured_logger()

    status = guardian.get_status() if guardian else {"running": False}
    stats = slog.get_stats()

    return {
        "guardian": status,
        "logs": stats,
    }


@router.get("/guardian/health-trend")
async def health_trend(request: Request, points: int = 10) -> dict[str, Any]:
    """Get system health trend."""
    guardian = _get_guardian(request)
    if not guardian:
        return {"error": "Guardian not running"}
    return {"trend": guardian.get_health_trend(points=points)}
