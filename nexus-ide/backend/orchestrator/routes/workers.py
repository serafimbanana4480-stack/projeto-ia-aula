"""Background workers REST API.

Endpoints:
    GET  /api/workers                list all background workers
    POST /api/workers/{name}/start   start a specific worker
    POST /api/workers/{name}/stop    stop a specific worker
    POST /api/workers/{name}/pause   pause a specific worker
    POST /api/workers/{name}/resume  resume a specific worker
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.core.background_workers import BackgroundWorkerManager
from backend.middleware.auth import require_auth
from backend.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_manager(request: Request) -> BackgroundWorkerManager | None:
    return getattr(request.app.state, "worker_manager", None)


@router.get("/workers")
@limiter.limit("100/minute")
async def list_workers(
    request: Request, _user: dict = Depends(require_auth)
) -> dict[str, list[dict[str, Any]]]:
    """Return status info for every background worker."""
    manager = _get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Worker manager not available")
    return {"workers": [w.model_dump(mode="json") for w in manager.list_workers()]}


@router.post("/workers/{name}/start")
@limiter.limit("60/minute")
async def start_worker(
    name: str, request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Start a specific background worker."""
    manager = _get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Worker manager not available")
    ok = await manager.start(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
    return {"success": True, "action": "start", "worker": name}


@router.post("/workers/{name}/stop")
@limiter.limit("60/minute")
async def stop_worker(
    name: str, request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Stop a specific background worker."""
    manager = _get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Worker manager not available")
    ok = await manager.stop(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
    return {"success": True, "action": "stop", "worker": name}


@router.post("/workers/{name}/pause")
@limiter.limit("60/minute")
async def pause_worker(
    name: str, request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Pause a specific background worker."""
    manager = _get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Worker manager not available")
    ok = await manager.pause(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
    return {"success": True, "action": "pause", "worker": name}


@router.post("/workers/{name}/resume")
@limiter.limit("60/minute")
async def resume_worker(
    name: str, request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Resume a paused background worker."""
    manager = _get_manager(request)
    if not manager:
        raise HTTPException(status_code=503, detail="Worker manager not available")
    ok = await manager.resume(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
    return {"success": True, "action": "resume", "worker": name}
