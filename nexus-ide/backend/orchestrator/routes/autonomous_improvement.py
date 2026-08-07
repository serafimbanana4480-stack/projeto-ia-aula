"""HTTP routes for the Autonomous Improvement System dashboard.

Shares the ``/api/improvement`` prefix with
``backend/core/routes/improvement.py`` (self-improvement proposals). Path
collisions are avoided deliberately: the proposals router owns ``/run``,
so the cycle trigger here lives at ``/run-cycle``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.middleware.auth import require_auth
from backend.orchestrator.autonomous_improvement_orchestrator import get_autonomous_improvement_orchestrator
from backend.config.settings import get_autonomous_improvement_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/improvement", tags=["improvement", "autonomous"])


@router.get("/status")
async def get_status(request: Request, _user: dict = Depends(require_auth)) -> dict:
    config = get_autonomous_improvement_config()
    orchestrator = get_autonomous_improvement_orchestrator(config=config)
    status = orchestrator.get_status()
    return status


@router.get("/cycles")
async def list_cycles(request: Request, _user: dict = Depends(require_auth)) -> dict:
    config = get_autonomous_improvement_config()
    orchestrator = get_autonomous_improvement_orchestrator(config=config)
    history = orchestrator._cycle_history[-50:]
    return {"count": len(history), "cycles": [c.__dict__ for c in history]}


@router.get("/subagents")
async def subagent_telemetry(request: Request, _user: dict = Depends(require_auth)) -> dict:
    """Subagent phase telemetry for the dashboard: aggregate stats plus the
    most recent RESEARCH/DESIGN/BUILD/VERIFY executions with budgets,
    retries, and checkpoint resumes."""
    config = get_autonomous_improvement_config()
    orchestrator = get_autonomous_improvement_orchestrator(config=config)
    manager = orchestrator.subagent_manager
    return {
        "stats": manager.get_stats(),
        "recent": manager.get_recent_results(limit=50),
    }


@router.post("/run-cycle")
async def run_cycle_now(request: Request, _user: dict = Depends(require_auth)) -> dict:
    """Trigger one autonomous improvement cycle immediately.

    Named ``/run-cycle`` because ``/api/improvement/run`` already belongs to
    the proposals router (``backend/core/routes/improvement.py``)."""
    config = get_autonomous_improvement_config()
    orchestrator = get_autonomous_improvement_orchestrator(config=config)
    result = await orchestrator.run_cycle()
    return {
        "cycle_id": result.cycle_id,
        "proposals_generated": result.proposals_generated,
        "proposals_applied": result.proposals_applied,
        "proposals_verified": result.proposals_verified,
        "wall_time_seconds": result.wall_time_seconds,
    }
