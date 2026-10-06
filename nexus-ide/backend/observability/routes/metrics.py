"""Metrics endpoints for dashboard.

Provides real-time metrics streaming and historical data.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.config.settings import get_settings  # noqa: E402
from backend.llm import model_catalog  # noqa: E402
from backend.llm.circuit_breaker import all_breakers  # noqa: E402
from backend.middleware.auth import require_auth  # noqa: E402
from backend.observability.metrics_collector import get_metrics_collector  # noqa: E402
from backend.observability.metrics_store import get_metrics_store  # noqa: E402
from backend.persistence.db import (  # noqa: E402
    count_pending_changes,
    get_agent_activity,
    get_change_statistics,
    get_message_statistics,
    get_token_usage_overview,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_usage_tracker():
    """Return the tracker written by the LLM manager (loaded lazily)."""
    from backend.llm.multi_llm_manager import get_token_tracker

    return get_token_tracker()


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
    """Return the live model inventory for the selected local provider."""
    provider = _configured_local_model_provider()
    if provider not in {"ollama", "lmstudio"}:
        raise HTTPException(
            status_code=503,
            detail="The selected provider does not expose a local model inventory",
        )

    try:
        import httpx

        url, headers, params = _model_inventory_request(provider)
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers, params=params or None)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected model inventory response")
        return _normalise_model_inventory(provider, data)
    except Exception as e:
        logger.warning("Failed to fetch models from %s: %s", provider, e)
        raise HTTPException(
            status_code=503,
            detail=f"{provider} model inventory is unavailable",
        ) from e


def _configured_local_model_provider() -> str:
    """Resolve the same runtime provider choice used by the LLM factory."""
    runtime = model_catalog._runtime_overrides()
    settings = get_settings()
    provider = str(
        runtime.get("llm_provider")
        or getattr(settings, "llm_provider", "")
        or getattr(settings, "default_provider", "")
    ).strip().lower()
    return "ollama" if provider == "local" else provider


def _model_inventory_request(provider: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """Build a live catalog request using the provider's configured URL/key."""
    api_key, base_url = model_catalog.resolve_credentials(provider)
    request = model_catalog._build_request(provider, api_key, base_url)
    return cast(tuple[str, dict[str, str], dict[str, str]], request)


def _normalise_model_inventory(provider: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a consistent dashboard shape without inventing unknown metadata."""
    entries = payload.get("models", []) if provider == "ollama" else payload.get("data", [])
    if not isinstance(entries, list):
        raise ValueError("Unexpected model inventory entries")

    models: list[dict[str, Any]] = []
    for entry in entries:
        if provider == "ollama":
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            raw_size = entry.get("size")
            size_bytes = (
                raw_size
                if isinstance(raw_size, int) and not isinstance(raw_size, bool) and raw_size >= 0
                else None
            )
            details = entry.get("details")
            models.append(
                {
                    "id": str(entry["name"]),
                    "size_bytes": size_bytes,
                    "modified_at": entry.get("modified_at"),
                    "details": details if isinstance(details, dict) else {},
                    "provider": provider,
                    "status": "available",
                }
            )
            continue

        if isinstance(entry, str):
            model_id = entry
        elif isinstance(entry, dict) and entry.get("id"):
            model_id = str(entry["id"])
        else:
            continue
        # OpenAI-compatible model-list APIs do not promise local weight sizes
        # or modification times. Keep those fields explicitly unknown.
        models.append(
            {
                "id": model_id,
                "size_bytes": None,
                "modified_at": None,
                "details": {},
                "provider": provider,
                "status": "available",
            }
        )
    return models


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
    """Return usage recorded by the LLM manager's in-memory token tracker.

    Costs are estimates from configured model pricing, not billing records.
    The tracker records provider and model, but not the calling agent.
    """
    range_map = {"24h": 86400, "7d": 604800, "30d": 2592000}
    seconds = range_map.get(range, 86400)
    generated_at = time.time()
    snapshot = _get_usage_tracker().snapshot(since=generated_at - seconds)
    return {
        "range": range if range in range_map else "24h",
        "range_seconds": seconds,
        "generated_at": generated_at,
        "source": "token_tracker_in_memory",
        "total_tokens": snapshot.total_input_tokens + snapshot.total_output_tokens,
        "total_tokens_in": snapshot.total_input_tokens,
        "total_tokens_out": snapshot.total_output_tokens,
        "total_cost": snapshot.total_cost_usd,
        "cost_is_estimated": True,
        "cost_basis": "configured_model_pricing",
        "currency": "USD",
        "call_count": snapshot.call_count,
        "by_model": {
            model: {
                "total_tokens": tokens,
                "cost": snapshot.cost_by_model.get(model, 0.0),
            }
            for model, tokens in snapshot.by_model.items()
        },
        "by_provider": dict(snapshot.by_provider),
    }


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
                quota is True
                and bool(getattr(prov, "validated_at", None))
                and reason not in {"", "not checked"}
            )
            observed_at = (
                float(getattr(llm_client, "last_provider_at", 0.0) or 0.0)
                if prov is getattr(llm_client, "last_provider", None)
                else 0.0
            )
            observed_real_success = observed_at > 0 and not bool(getattr(prov, "simulation", False))
            health_status = (
                "healthy"
                if observed_real_success
                else "unknown"
                if eligible and not bool(getattr(prov, "simulation", False))
                else "unavailable"
            )
            providers[name] = {
                "healthy": (
                    True
                    if observed_real_success
                    else None
                    if health_status == "unknown"
                    else False
                ),
                "status": health_status,
                "health_basis": "runtime_observation" if observed_real_success else "eligibility",
                "latency": (
                    getattr(llm_client, "last_provider_latency_ms", None) if observed_at else None
                ),
                "last_check": observed_at or None,
                "eligibility_reason": reason,
                "quota_available": quota,
                "validated_at": getattr(prov, "validated_at", None),
                "circuit_breaker": breaker,
                "runtime_observed": observed_real_success,
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
            quota is True
            and bool(getattr(llm_client, "validated_at", None))
            and reason not in {"", "not checked"}
        )
        return {
            "providers": {
                name: {
                    "healthy": (
                        None
                        if eligible and not bool(getattr(llm_client, "simulation", False))
                        else False
                    ),
                    "status": (
                        "unknown"
                        if eligible and not bool(getattr(llm_client, "simulation", False))
                        else "unavailable"
                    ),
                    "health_basis": "eligibility_only",
                    "latency": 0.0,
                    "last_check": 0.0,
                    "eligibility_reason": reason,
                    "quota_available": quota,
                    "validated_at": getattr(llm_client, "validated_at", None),
                    "circuit_breaker": breaker,
                    "runtime_observed": False,
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
