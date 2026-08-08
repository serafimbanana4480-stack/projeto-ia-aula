"""Agent instance lifecycle REST API.

Endpoints:
    GET  /api/agents/instances                list active agent instances
    GET  /api/agents/instances/{id}           get status of a specific instance
    POST /api/agents/instances/{id}/pause     pause an agent instance
    POST /api/agents/instances/{id}/resume    resume an agent instance
    POST /api/agents/instances/{id}/abort     abort an agent instance
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.core.agent_lifecycle import AgentLifecycleManager
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_lifecycle(request: Request) -> AgentLifecycleManager | None:
    return getattr(request.app.state, "agent_lifecycle", None)


@router.get("/agents/instances")
async def list_instances(
    request: Request,
    session_id: str | None = None,
    include_terminal: bool = False,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return background agents, optionally scoped to one chat session."""
    lifecycle = _get_lifecycle(request)
    if not lifecycle:
        raise HTTPException(status_code=503, detail="Agent lifecycle manager not available")
    active = lifecycle.list_active() if not include_terminal else lifecycle.list_all()
    if session_id:
        active = [instance for instance in active if instance.mission_id == session_id]
    return {
        "agents": [i.model_dump(mode="json") for i in active],
        "count": len(active),
        "stats": lifecycle.get_stats(),
    }


@router.get("/agents/instances/{instance_id}")
async def get_instance(
    instance_id: str, request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Return the full status of a single agent instance."""
    lifecycle = _get_lifecycle(request)
    if not lifecycle:
        raise HTTPException(status_code=503, detail="Agent lifecycle manager not available")
    instance = lifecycle.get_status(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Agent instance '{instance_id}' not found")
    return instance.model_dump(mode="json")


@router.post("/agents/instances/{instance_id}/pause")
async def pause_instance(
    instance_id: str, request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Pause a running agent instance."""
    lifecycle = _get_lifecycle(request)
    if not lifecycle:
        raise HTTPException(status_code=503, detail="Agent lifecycle manager not available")
    try:
        instance = await lifecycle.pause(instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "action": "pause", "instance": instance.model_dump(mode="json")}


@router.post("/agents/instances/{instance_id}/resume")
async def resume_instance(
    instance_id: str, request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Resume a paused agent instance."""
    lifecycle = _get_lifecycle(request)
    if not lifecycle:
        raise HTTPException(status_code=503, detail="Agent lifecycle manager not available")
    try:
        instance = await lifecycle.resume(instance_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "action": "resume", "instance": instance.model_dump(mode="json")}


@router.post("/agents/instances/{instance_id}/abort")
async def abort_instance(
    instance_id: str, request: Request, reason: str = "", _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Abort a running or paused agent instance."""
    lifecycle = _get_lifecycle(request)
    if not lifecycle:
        raise HTTPException(status_code=503, detail="Agent lifecycle manager not available")
    try:
        instance = await lifecycle.abort(instance_id, reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "action": "abort", "instance": instance.model_dump(mode="json")}
