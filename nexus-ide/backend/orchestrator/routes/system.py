"""System-level REST API — self-improvement, global controls, and session health.

Endpoints:
    GET  /api/system/health              overall system health snapshot
    GET  /api/system/session-health     long-running session health metrics
    GET  /api/system/healer/status      self-healing engine status
    GET  /api/system/self-improvement   latest improvement proposals
    POST /api/system/self-improvement/run  trigger analysis on demand
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.core.self_improvement import SelfImprovementAnalyzer
from backend.middleware.auth import require_auth
from backend.tools.web_search import SearchProvidersUnavailable, search_images, search_web

logger = logging.getLogger(__name__)
router = APIRouter()


def _web_search_enabled() -> bool:
    """Read the active environment's web-search feature flag.

    Older/custom configs may omit the flag, so they retain the historical
    enabled behavior. Explicit false values fail closed for both UI endpoints.
    """
    from backend.config.settings import load_environment_config

    config = load_environment_config()
    features = config.get("features", {}) if isinstance(config, dict) else {}
    value = features.get("enable_web_search", True) if isinstance(features, dict) else True
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}
    return bool(value)


def _require_web_search_enabled() -> None:
    if not _web_search_enabled():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "web_search_disabled",
                "message": "A pesquisa web está desativada na configuração do ambiente.",
            },
        )


@router.get("/system/health")
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
async def get_healer_status(
    request: Request, _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    """Return self-healing engine status."""
    healer = getattr(request.app.state, "healer", None)
    if not healer:
        return {"running": False, "error": "Healer not initialized"}
    return healer.status()


@router.get("/system/self-improvement")
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
async def web_search_endpoint(
    request: Request,
    payload: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Execute a web search query."""
    query_value = payload.get("query", "")
    if not isinstance(query_value, str) or not query_value.strip():
        raise HTTPException(status_code=422, detail="Query is required")
    query = query_value.strip()
    if len(query) > 400:
        raise HTTPException(status_code=422, detail="Query must be 400 characters or fewer")
    _require_web_search_enabled()
    raw_limit = payload.get("limit", 10)
    try:
        limit = max(1, min(int(raw_limit), 50))
    except (TypeError, ValueError, OverflowError):
        limit = 10
    try:
        result = await search_web(query, max_results=limit)
        return result
    except SearchProvidersUnavailable as exc:
        logger.warning("Web search providers unavailable: %s", ", ".join(exc.providers))
        raise HTTPException(
            status_code=502,
            detail={
                "code": "providers_unavailable",
                "message": "Os motores de pesquisa não responderam. Tenta novamente daqui a pouco.",
            },
        ) from exc
    except Exception as exc:
        logger.exception("Web search failed")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "search_internal_error",
                "message": "A pesquisa falhou por um erro interno.",
            },
        ) from exc


@router.post("/web_search/images")
async def web_image_search_endpoint(
    response: Response,
    payload: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Search image results on demand; results are not cached by the app."""
    query_value = payload.get("query", "")
    if not isinstance(query_value, str) or not query_value.strip():
        raise HTTPException(status_code=422, detail="Query is required")
    query = query_value.strip()
    if len(query) > 400:
        raise HTTPException(status_code=422, detail="Query must be 400 characters or fewer")
    _require_web_search_enabled()
    response.headers["Cache-Control"] = "no-store"
    limit = payload.get("limit", 24)
    try:
        bounded_limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError, OverflowError):
        bounded_limit = 24
    try:
        return await search_images(query, max_results=bounded_limit)
    except Exception as exc:
        logger.exception("Image search failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "provider_error",
                "message": "O fornecedor de pesquisa de imagens não respondeu corretamente.",
            },
        ) from exc
