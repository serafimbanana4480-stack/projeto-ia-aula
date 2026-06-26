"""Metrics endpoints for dashboard.

Provides real-time metrics streaming and historical data.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.config.settings import get_settings as _get_settings
from backend.middleware.auth import decode_access_token


def _is_dev_mode() -> bool:
    try:
        return _get_settings().environment == "development"
    except Exception:
        return True


from backend.llm.circuit_breaker import all_breakers  # noqa: E402
from backend.middleware.auth import require_auth  # noqa: E402
from backend.observability.metrics_collector import get_metrics_collector  # noqa: E402
from backend.observability.metrics_store import get_metrics_store  # noqa: E402
from backend.observability.usage_store import get_usage_store  # noqa: E402
from backend.persistence.db import (  # noqa: E402
    count_pending_changes,
    get_agent_activity,
    get_change_statistics,
    get_message_statistics,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_active_session_count(request: Request) -> int:
    context = getattr(request.app.state, "context", None)
    if context is None:
        return 0
    if hasattr(context, "active_session_count"):
        return await context.active_session_count()
    return 0


async def _get_stats() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        msg_stats = await asyncio.to_thread(get_message_statistics)
        chg_stats = await asyncio.to_thread(get_change_statistics)
        return msg_stats, chg_stats
    except Exception as exc:
        logger.warning("Failed to load stats for metrics: %s", exc)
        return {}, {}


async def _build_current_metrics_payload(request: Request) -> dict[str, Any]:
    """Assemble the metrics dict shared by REST and SSE endpoints."""
    collector = get_metrics_collector()

    message_stats, change_stats = await _get_stats()
    active_sessions = await _get_active_session_count(request)
    queue_depth = await asyncio.to_thread(count_pending_changes)
    agent_activity = await asyncio.to_thread(get_agent_activity)

    snapshot = await collector.get_snapshot(
        active_sessions=active_sessions, queue_depth=queue_depth
    )

    return {
        "tokens_per_second": snapshot.tokens_per_second,
        "active_model": snapshot.active_model,
        "active_sessions": snapshot.active_sessions,
        "queue_depth": snapshot.queue_depth,
        "ram_used_bytes": snapshot.ram_used_bytes,
        "ram_total_bytes": snapshot.ram_total_bytes,
        "ram_percent": snapshot.ram_percent,
        "cpu_percent": snapshot.cpu_percent,
        "disk_used_bytes": snapshot.disk_used_bytes,
        "disk_total_bytes": snapshot.disk_total_bytes,
        "disk_percent": snapshot.disk_percent,
        "uptime_seconds": snapshot.uptime_seconds,
        "requests_total": snapshot.requests_total,
        "requests_successful": snapshot.requests_successful,
        "requests_failed": snapshot.requests_failed,
        "avg_latency_ms": snapshot.avg_latency_ms,
        "timestamp": snapshot.timestamp,
        "message_stats": message_stats,
        "change_stats": change_stats,
        "agent_activity": agent_activity,
    }


def _validate_stream_auth(request: Request, token: str | None) -> None:
    """Authenticate SSE clients that cannot send Authorization headers."""
    auth_header = request.headers.get("Authorization", "")
    bearer = (
        auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else None
    )
    jwt_token = bearer or token
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    decode_access_token(jwt_token)


@router.get("/metrics")
async def get_metrics_index(request: Request) -> dict:
    """Return available metrics endpoints."""
    return {
        "endpoints": {
            "current": "/api/metrics/current",
            "history": "/api/metrics/history",
            "flow": "/api/metrics/flow",
            "analytics": "/api/metrics/analytics",
        }
    }


@router.get("/metrics/current")
async def get_current_metrics(request: Request) -> dict:
    """Get current metrics snapshot. No auth required in dev mode."""
    return await _build_current_metrics_payload(request)


@router.get("/dashboard/stream")
async def dashboard_metrics_stream(
    request: Request,
    token: str | None = None,
) -> StreamingResponse:
    """Stream metrics snapshots over SSE for the dashboard.

    In development mode, no auth is required. In production, requires
    a valid JWT token as query parameter or Authorization header.
    """
    if not _is_dev_mode():
        _validate_stream_auth(request, token)

    async def event_stream() -> AsyncIterator[str]:
        while True:
            payload = await _build_current_metrics_payload(request)
            yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/metrics/history")
async def get_metrics_history(
    seconds: int = Query(3600, ge=1, description="Time window in seconds"),
    metric: str = Query("tokens_per_second", description="Metric name to retrieve history for"),
) -> dict:
    """Return historical timeline data for a single metric.

    Uses the in-memory metrics store (1h deque). Falls back to an empty
    dataset on any error so callers never receive a 500.
    """
    try:
        store = get_metrics_store()
        timeline = await store.get_timeline(seconds=seconds, metric=metric)
    except Exception as exc:
        logger.warning(
            "Failed to load metrics history (metric=%s, seconds=%s): %s",
            metric,
            seconds,
            exc,
        )
        timeline = []

    return {
        "metric": metric,
        "seconds": seconds,
        "data": timeline,
    }


@router.get("/models/status")
async def get_models_status() -> list[dict]:
    """Return status of available models from Ollama."""
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:11434/api/tags", timeout=5.0)
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("models", []):
                models.append(
                    {
                        "id": model.get("name"),
                        "size_bytes": model.get("size", 0),
                        "modified_at": model.get("modified_at"),
                        "details": model.get("details", {}),
                        "status": "available",
                    }
                )

            return models
    except Exception as e:
        logger.warning("Failed to fetch models from Ollama: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Ollama model inventory is unavailable",
        ) from e


@router.get("/metrics/flow")
async def get_request_flow() -> dict:
    """Return request flow data for visualization.

    Shows the flow of requests through the system:
    User → Router → Agent → LLM → Response
    """
    collector = get_metrics_collector()

    snapshot = await collector.get_snapshot(active_sessions=0, queue_depth=0)
    return {
        "available": False,
        "reason": "request flow tracing is not instrumented yet",
        "nodes": [],
        "links": [],
        "summary": {
            "total_requests": snapshot.requests_total,
            "successful_requests": snapshot.requests_successful,
            "failed_requests": snapshot.requests_failed,
            "avg_latency_ms": snapshot.avg_latency_ms,
            "throughput_tps": snapshot.tokens_per_second,
        },
    }


@router.get("/metrics/timeline")
async def get_token_timeline() -> dict:
    """Return token generation timeline data for visualization.

    Shows token generation over time for the current session.
    """
    store = get_metrics_store()

    # Get timeline data for the last hour
    timeline = await store.get_timeline(seconds=3600, metric="tokens_per_second")

    return {
        "data": timeline,
        "summary": {
            "total_tokens": sum(item.get("value", 0) for item in timeline),
            "peak_tokens_per_second": max((item.get("value", 0) for item in timeline), default=0),
            "avg_tokens_per_second": sum(item.get("value", 0) for item in timeline) / len(timeline)
            if timeline
            else 0,
        },
    }


@router.get("/metrics/analytics")
async def get_analytics(request: Request) -> dict:
    """Return analytics data for the dashboard.

    Provides comprehensive analytics including usage patterns, performance metrics,
    and system health indicators.
    """
    collector = get_metrics_collector()
    store = get_metrics_store()

    # Get current metrics
    active_sessions = await _get_active_session_count(request)
    queue_depth = count_pending_changes()
    snapshot = await collector.get_snapshot(
        active_sessions=active_sessions, queue_depth=queue_depth
    )

    # Get historical data
    history = await store.get_timeline_multi(seconds=3600)
    message_stats, change_stats = await _get_stats()

    return {
        "current": {
            "tokens_per_second": snapshot.tokens_per_second,
            "active_model": snapshot.active_model,
            "active_sessions": snapshot.active_sessions,
            "queue_depth": snapshot.queue_depth,
            "cpu_percent": snapshot.cpu_percent,
            "ram_percent": snapshot.ram_percent,
            "avg_latency_ms": snapshot.avg_latency_ms,
        },
        "history": history,
        "message_stats": message_stats,
        "change_stats": change_stats,
        "summary": {
            "total_requests": snapshot.requests_total,
            "successful_requests": snapshot.requests_successful,
            "failed_requests": snapshot.requests_failed,
            "uptime_hours": snapshot.uptime_seconds / 3600,
        },
    }


@router.get("/metrics/usage")
async def get_usage(
    range: str = Query("24h", description="Time range: 24h, 7d, or 30d"),
    _user: dict = Depends(require_auth),
) -> dict:
    """Return aggregated token usage and cost data.

    Breakdown by model and by agent (top 5 by token count).
    Time range options: 24h (default), 7d, 30d.
    """
    range_map = {"24h": 86400, "7d": 604800, "30d": 2592000}
    seconds = range_map.get(range, 86400)
    store = get_usage_store()
    return await store.get_usage(range_seconds=seconds)


@router.get("/providers/status")
async def get_providers_status(
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Return real-time status of all LLM providers.

    Includes health status, P95 latency, circuit breaker state,
    and last error for each registered provider.
    """
    # Try to get the multi-LLM manager from app state
    llm_client = getattr(request.app.state, "llm_client", None)
    if llm_client is None:
        return {
            "providers": {},
            "note": "LLM client not initialised",
        }

    # If it's a MultiLLMManager, use its provider_status
    from backend.llm.multi_llm_manager import MultiLLMManager
    if isinstance(llm_client, MultiLLMManager):
        status = llm_client.provider_status()
        return {
            "providers": status,
            "breakers": all_breakers(),
        }

    # Otherwise inspect the resilient provider's internals
    from backend.llm.factory import ResilientLLMProvider
    if isinstance(llm_client, ResilientLLMProvider):
        providers: dict[str, dict] = {}
        for idx, prov in enumerate([llm_client.primary] + llm_client.fallbacks):
            name = prov.__class__.__name__.replace("Provider", "").lower() or f"provider_{idx}"
            providers[name] = {
                "healthy": True,
                "latency": 0.0,
                "last_check": 0.0,
                "circuit_breaker": {},
            }
        return {
            "providers": providers,
            "breakers": all_breakers(),
        }
