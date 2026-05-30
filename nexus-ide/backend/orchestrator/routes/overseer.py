"""OVERSEER API routes — agent health dashboard and intervention."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.agents.overseer import OverseerAgent

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_overseer(request: Request) -> OverseerAgent | None:
    """Resolve the overseer from the agent registry."""
    registry = getattr(request.app.state, "registry", None)
    if registry:
        return registry.get("OVERSEER")  # type: ignore[return-value]
    return None


@router.get("/overseer/dashboard")
async def overseer_dashboard(request: Request) -> dict[str, Any]:
    """Return the full overseer health dashboard."""
    overseer = _get_overseer(request)
    if not overseer:
        raise HTTPException(status_code=503, detail="Overseer not available")
    return overseer.get_dashboard()


@router.get("/overseer/agents/{agent_name}")
async def overseer_agent_status(agent_name: str, request: Request) -> dict[str, Any]:
    """Return status for a specific agent."""
    overseer = _get_overseer(request)
    if not overseer:
        raise HTTPException(status_code=503, detail="Overseer not available")
    status = overseer.get_agent_status(agent_name)
    if not status:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not tracked")
    return status


@router.post("/overseer/agents/{agent_name}/intervene")
async def overseer_intervene(
    agent_name: str,
    request: Request,
    action: str,
    reason: str = "",
) -> dict[str, Any]:
    """Intervene on an agent: pause, resume, abort, or escalate."""
    overseer = _get_overseer(request)
    if not overseer:
        raise HTTPException(status_code=503, detail="Overseer not available")
    result = await overseer.intervene(agent_name, action, reason)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/overseer/conflicts")
async def overseer_conflicts(request: Request) -> dict[str, Any]:
    """Return current file conflicts between agents."""
    overseer = _get_overseer(request)
    if not overseer:
        raise HTTPException(status_code=503, detail="Overseer not available")
    return {"conflicts": overseer.get_dashboard().get("file_conflicts", [])}


@router.get("/overseer/stuck")
async def overseer_stuck(request: Request) -> dict[str, Any]:
    """Return agents currently marked as stuck."""
    overseer = _get_overseer(request)
    if not overseer:
        raise HTTPException(status_code=503, detail="Overseer not available")
    return {"stuck_agents": overseer.get_dashboard().get("stuck_agents", [])}
