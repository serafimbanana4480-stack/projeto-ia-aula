"""Dashboard routes for system monitoring, alerts, and health metrics.

Exposes:
- GET /api/dashboard/status    → current health snapshot and score
- GET /api/dashboard/alerts    → recent alerts with optional severity filter
- GET /api/dashboard/metrics   → raw metrics snapshot
- POST /api/dashboard/ask      → natural-language query answered by DashboardAgent
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.agents.base import AgentRequest
from backend.agents.dashboard_agent import DashboardAgent
from backend.middleware.auth import require_auth
from backend.orchestrator.registry import get_registry

logger = logging.getLogger(__name__)
router = APIRouter()


class DashboardAskRequest(BaseModel):
    question: str
    session_id: str = "dashboard"


class DashboardDiagnoseRequest(BaseModel):
    focus: str = "system"
    session_id: str = "dashboard"


def _get_dashboard_agent(request: Request) -> DashboardAgent:
    """Resolve the dashboard agent from app state or registry."""
    agent = getattr(request.app.state, "dashboard_agent", None)
    if isinstance(agent, DashboardAgent):
        return agent
    registry = get_registry(request.app)
    agent = registry.get("DASHBOARD")
    if not isinstance(agent, DashboardAgent):
        agent = DashboardAgent()
    return agent


@router.get("/dashboard/status")
async def dashboard_status(
    request: Request,
    _user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Return current system health status, latest snapshot, and score."""
    agent = _get_dashboard_agent(request)
    snapshot = agent.get_latest_snapshot()
    alerts = agent.get_alerts()

    try:
        from backend.mcp.store import mcp_store

        mcp_summary = mcp_store.health()
    except Exception:
        logger.exception("Failed to read MCP connector summary for dashboard status")
        mcp_summary = {"total": 0, "enabled": 0, "healthy": 0, "warning": 0, "error": 0, "untested": 0}

    return {
        "health_score": agent.get_health_score(),
        "snapshot": snapshot,
        "active_alerts": len(alerts),
        "critical_alerts": len([a for a in alerts if a.get("severity") == "critical"]),
        "mcp_connectors": mcp_summary,
    }


@router.get("/dashboard/alerts")
async def dashboard_alerts(
    request: Request,
    severity: str | None = None,
    limit: int = 50,
    _user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Return recent alerts, optionally filtered by severity."""
    agent = _get_dashboard_agent(request)
    return {
        "alerts": agent.get_alerts(severity=severity, limit=limit),
        "filter": {"severity": severity, "limit": limit},
    }


@router.get("/dashboard/metrics")
async def dashboard_metrics(
    request: Request,
    _user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Return the latest raw metrics snapshot."""
    agent = _get_dashboard_agent(request)
    snapshot = agent.get_latest_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Metrics collector not ready")
    return {"snapshot": snapshot}


@router.post("/dashboard/ask")
async def dashboard_ask(
    req: DashboardAskRequest,
    request: Request,
    _user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Answer a natural-language question about system metrics."""
    agent = _get_dashboard_agent(request)
    llm_client = getattr(request.app.state, "llm_client", None)
    if not llm_client:
        raise HTTPException(status_code=503, detail="LLM client not available")

    agent_req = AgentRequest(
        session_id=req.session_id,
        query=req.question,
        client=llm_client,
    )

    parts: list[str] = []
    async for token in agent.run(agent_req):
        parts.append(token)

    return {
        "answer": "".join(parts),
        "session_id": req.session_id,
    }


@router.post("/dashboard/diagnose")
async def dashboard_diagnose(
    req: DashboardDiagnoseRequest,
    request: Request,
    _user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Run a deeper diagnostic by consulting the ANALYZER specialist."""
    agent = _get_dashboard_agent(request)
    llm_client = getattr(request.app.state, "llm_client", None)
    if not llm_client:
        raise HTTPException(status_code=503, detail="LLM client not available")

    metrics_context = await agent._build_metrics_context()
    registry = get_registry(request.app)
    analyzer = registry.get("ANALYZER")
    if analyzer is None:
        raise HTTPException(status_code=503, detail="ANALYZER agent not available")

    diagnose_query = (
        f"You are reviewing NEXUS IDE system health. Focus area: {req.focus}.\n\n"
        f"{metrics_context}\n\n"
        "Identify root causes for any anomalies, assess risks, and list concrete "
        "corrective actions. Be concise and actionable."
    )
    agent_req = AgentRequest(
        session_id=req.session_id,
        query=diagnose_query,
        client=llm_client,
        context={
            "_system_addon": "Use your analysis tools if needed. Consult DEBUGGER for crash/root-cause issues."
        },
        max_iterations=7,
        enable_thinking=True,
    )

    parts: list[str] = []
    async for token in analyzer.run(agent_req):
        parts.append(token)

    return {
        "diagnosis": "".join(parts),
        "focus": req.focus,
        "session_id": req.session_id,
        "health_score": agent.get_health_score(),
    }
