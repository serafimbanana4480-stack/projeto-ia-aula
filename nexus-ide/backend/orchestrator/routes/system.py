"""System-level REST API — self-improvement and global controls.

Endpoints:
    GET  /api/system/self-improvement      view latest improvement proposals
    POST /api/system/self-improvement/run  trigger analysis on demand
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.core.self_improvement import SelfImprovementAnalyzer
from backend.middleware.auth import require_auth
from backend.middleware.rate_limit import limiter
from backend.tools.web_search import search_web

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/system/health")
@limiter.limit("120/minute")
async def get_system_health(request: Request) -> dict[str, Any]:
    """Return overall system health snapshot."""
    import httpx

    from backend.config.settings import get_settings

    settings = get_settings()
    health = {
        "status": "healthy",
        "services": {},
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Check Ollama
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{settings.ollama_host}/api/tags", timeout=3.0)
            health["services"]["ollama"] = "online" if r.status_code == 200 else "degraded"
    except Exception:
        health["services"]["ollama"] = "offline"

    # Check backend itself
    health["services"]["backend"] = "online"

    # Check database
    try:
        from backend.persistence.db import get_db

        with get_db() as conn:
            conn.execute("SELECT 1")
        health["services"]["database"] = "online"
    except Exception:
        health["services"]["database"] = "offline"

    if any(v == "offline" for v in health["services"].values()):
        health["status"] = "degraded"
    if all(v == "offline" for v in health["services"].values()):
        health["status"] = "unhealthy"

    # Add self-healing engine status
    healer = getattr(request.app.state, "healer", None)
    if healer:
        health["self_healing"] = healer.status()
    else:
        health["self_healing"] = {"running": False, "skills_count": 0}

    return health


@router.get("/system/healer/status")
@limiter.limit("60/minute")
async def get_healer_status(
    request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Return self-healing engine status."""
    healer = getattr(request.app.state, "healer", None)
    if not healer:
        return {"running": False, "error": "Healer not initialized"}
    return healer.status()


@router.get("/system/self-improvement")
@limiter.limit("60/minute")
async def get_self_improvement(
    request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Return the latest self-improvement report."""
    analyzer = SelfImprovementAnalyzer()
    report = analyzer.get_last_report()
    if not report:
        raise HTTPException(status_code=404, detail="No self-improvement report available")
    return report.model_dump(mode="json")


@router.post("/system/self-improvement/run")
@limiter.limit("10/minute")
async def run_self_improvement(
    request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Trigger the self-improvement analysis on demand."""
    analyzer = SelfImprovementAnalyzer()
    try:
        report = await analyzer.run_analysis()
    except Exception as exc:
        logger.exception("Self-improvement analysis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "success": True,
        "report": report.model_dump(mode="json"),
    }


@router.post("/web_search")
@limiter.limit("30/minute")
async def web_search_endpoint(
    request: Request,
    payload: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Execute a web search query."""
    query = payload.get("query", "")
    if not query:
        raise HTTPException(status_code=422, detail="Query is required")
    limit = payload.get("limit", 10)
    try:
        result = await search_web(query, max_results=limit)
        return result
    except Exception as exc:
        logger.exception("Web search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
