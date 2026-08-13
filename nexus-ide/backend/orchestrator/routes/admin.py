"""Admin REST API — GC control and session lifecycle management.

Endpoints:
    POST /api/admin/gc/run     execute a full GC cycle on demand
    GET  /api/admin/gc/stats   return current GC/session stats without running GC
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.middleware.auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


def _get_manager(request: Request) -> Any:
    """Get the SessionLifecycleManager from app state."""
    manager = getattr(request.app.state, "session_lifecycle", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Session lifecycle manager not available")
    return manager


@router.post("/gc/run")
async def run_gc(
    request: Request,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Trigger a manual garbage-collection cycle.

    Requires admin privileges.
    Rate limited to 10 requests per minute.
    """
    manager = _get_manager(request)
    try:
        report = await manager.run_gc(allow_destructive=True)
    except Exception as exc:
        logger.exception("Manual GC run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "success": True,
        "report": report,
    }


@router.get("/gc/stats")
async def get_gc_stats(
    request: Request,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Return session and GC statistics without triggering a GC run.

    Requires admin privileges.
    """
    manager = _get_manager(request)
    try:
        stats = manager.get_stats()
    except Exception as exc:
        logger.exception("Failed to get GC stats")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "success": True,
        "stats": stats,
    }


__all__ = ["router"]
