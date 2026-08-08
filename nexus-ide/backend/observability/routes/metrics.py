"""Metrics endpoints for dashboard.

Provides real-time metrics streaming and historical data.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

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
    get_token_usage_overview,
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


def _validate_stream_auth(request: Request, token: str | None = None) -> None:
    """Authenticate SSE clients without accepting bearer tokens in URLs."""
    # ``token`` remains an ignored compatibility argument for integrations
    # that called this helper directly; query-string credentials are never
    # accepted for the actual stream endpoint.
    del token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    from backend.middleware.auth import decode_access_token

    decode_access_token(auth_header.removeprefix("Bearer ").strip())


@router.get("/metrics")
async def get_metrics_index(request: Request, _user: dict = Depends(require_auth)) -> dict:
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
async def get_current_metrics(request: Request, _user: dict = Depends(require_auth)) -> dict:
    """Get current metrics snapshot for authenticated users."""
    return await _build_current_metrics_payload(request)


@router.get("/dashboard/stream")
async def dashboard_metrics_stream(
    request: Request,
) -> StreamingResponse:
    """Stream metrics snapshots over SSE for the dashboard.

    Requires a valid JWT in the Authorization header. Bearer tokens in query
    strings are deliberately rejected so URLs cannot become credential logs.
    """
    _validate_stream_auth(request)

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
    _user: dict = Depends(require_auth),
) -> list[Any]:
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

    # Return the timeline directly for compatibility with the original API.
    # Frontend consumers accept both this list and the newer wrapped shape.
    return timeline


@router.get("/metrics/history/multi")
async def get_metrics_history_multi(
    seconds: int = Query(3600, ge=1, description="Time window in seconds"),
    _user: dict = Depends(require_auth),
) -> dict[str, list[Any]]:
    """Return timelines for all metrics without failing on a partial series."""
    store = get_metrics_store()
    names = getattr(store, "metric_names", None)
    if callable(names):
        names = names()
    names = names or ["tokens_per_second", "cpu_percent", "ram_percent"]
    result: dict[str, list[Any]] = {}
    for name in names:
        try:
            result[str(name)] = await store.get_timeline(seconds=seconds, metric=str(name))
        except Exception:
            result[str(name)] = []
    return result


@router.get("/models/status")
async def get_models_status(_user: dict = Depends(require_auth)) -> list[dict]:
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
        # Preserve an explicit service-unavailable signal so the dashboard can
        # distinguish an empty inventory from an offline Ollama daemon.
        raise HTTPException(
            status_code=503,
            detail="Ollama model inventory is unavailable",
        ) from e


@router.get("/metrics/flow")
async def get_request_flow(_user: dict = Depends(require_auth)) -> dict:
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
async def get_token_timeline(_user: dict = Depends(require_auth)) -> dict:
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
async def get_analytics(request: Request, _user: dict = Depends(require_auth)) -> dict:
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


@router.get("/metrics/usage/overview")
async def get_usage_overview(
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return the durable metrics overview used by the Metrics page.

    Unlike ``/metrics/usage`` (kept for widget compatibility), this endpoint
    includes calendar periods, a 30-day daily series and all-time model usage.
    """
    overview = await asyncio.to_thread(get_token_usage_overview)
    try:
        active_sessions = await _get_active_session_count(request)
        snapshot = await get_metrics_collector().get_snapshot(
            active_sessions=active_sessions,
            queue_depth=0,
        )
        overview["current"] = {
            "tokens_per_second": snapshot.tokens_per_second,
            "active_model": snapshot.active_model,
            "timestamp": snapshot.timestamp,
        }
    except Exception:
        overview["current"] = {
            "tokens_per_second": 0.0,
            "active_model": None,
            "timestamp": time.time(),
        }
    return overview


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
        providers: dict[str, dict[str, Any]] = {}
        for idx, prov in enumerate([llm_client.primary] + llm_client.fallbacks):
            name = prov.__class__.__name__.replace("Provider", "").lower() or f"provider_{idx}"
            breaker = all_breakers().get(name, {})
            quota = getattr(prov, "quota_available", None)
            reason = getattr(prov, "eligibility_reason", "")
            free_only = bool(getattr(llm_client, "free_only", False))
            eligible = not free_only or (
                quota is True and bool(getattr(prov, "validated_at", None))
                and reason not in {"", "not checked"}
            )
            providers[name] = {
                "healthy": eligible and not bool(getattr(prov, "simulation", False)),
                "latency": 0.0,
                "last_check": 0.0,
                "eligibility_reason": reason,
                "quota_available": quota,
                "validated_at": getattr(prov, "validated_at", None),
                "circuit_breaker": breaker,
            }
        return {
            "providers": providers,
            "breakers": all_breakers(),
        }

    name = llm_client.__class__.__name__.replace("Provider", "").lower()
    if name:
        breaker = all_breakers().get(name, {})
        quota = getattr(llm_client, "quota_available", None)
        reason = getattr(llm_client, "eligibility_reason", "")
        free_only = bool(getattr(llm_client, "free_only", False))
        eligible = not free_only or (
            quota is True and bool(getattr(llm_client, "validated_at", None))
            and reason not in {"", "not checked"}
        )
        return {
            "providers": {
                name: {
                    "healthy": eligible and not bool(getattr(llm_client, "simulation", False)),
                    "latency": 0.0,
                    "last_check": 0.0,
                    "eligibility_reason": reason,
                    "quota_available": quota,
                    "validated_at": getattr(llm_client, "validated_at", None),
                    "circuit_breaker": breaker,
                }
            },
            "breakers": all_breakers(),
        }

    # Keep the endpoint total for truly unknown custom objects.
    return {
        "providers": {},
        "breakers": all_breakers(),
        "note": f"Unsupported LLM client: {llm_client.__class__.__name__}",
    }
