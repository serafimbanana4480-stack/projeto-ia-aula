"""Metrics endpoints for dashboard.

Provides real-time metrics streaming and historical data.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.observability.metrics_collector import get_metrics_collector
from backend.observability.metrics_store import get_metrics_store
from backend.orchestrator.context_manager import ContextStore

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/metrics/current")
async def get_current_metrics() -> dict:
    """Get current metrics snapshot."""
    collector = get_metrics_collector()
    
    # Get active sessions from context store
    # Note: This is a simple count, in production we'd need a real session registry
    active_sessions = 1  # Placeholder for now
    
    snapshot = await collector.get_snapshot(active_sessions=active_sessions, queue_depth=0)
    
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
    }


@router.get("/metrics/history")
async def get_metrics_history(seconds: int = 3600, metric: str = "tokens_per_second") -> list[dict]:
    """Get historical metrics for timeline charts."""
    store = get_metrics_store()
    return await store.get_timeline(seconds=seconds, metric=metric)


@router.get("/metrics/history/multi")
async def get_metrics_history_multi(seconds: int = 3600) -> dict:
    """Get historical metrics for multiple metrics."""
    store = get_metrics_store()
    return await store.get_timeline_multi(seconds=seconds)


@router.get("/dashboard/stream")
async def dashboard_stream() -> StreamingResponse:
    """Stream real-time metrics via SSE.

    Returns a Server-Sent Events stream with periodic metric snapshots.
    """
    collector = get_metrics_collector()
    store = get_metrics_store()

    async def event_generator() -> AsyncIterator[str]:
        """Generate SSE events with metric snapshots."""
        while True:
            # Get current metrics
            active_sessions = 1  # Placeholder
            snapshot = await collector.get_snapshot(active_sessions=active_sessions, queue_depth=0)
            
            # Store for history
            await store.add_snapshot(snapshot)
            
            # Format as SSE event
            metrics = {
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
            }
            yield f"data: {json.dumps(metrics)}\n\n"
            await asyncio.sleep(1)  # Update every second

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


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
                models.append({
                    "id": model.get("name"),
                    "size_bytes": model.get("size", 0),
                    "modified_at": model.get("modified_at"),
                    "details": model.get("details", {}),
                    "status": "available",
                })
            
            return models
    except Exception as e:
        logger.warning(f"Failed to fetch models from Ollama: {e}")
        # Return fallback data
        return [
            {
                "id": "qwen3.6:latest",
                "size_bytes": 23938333577,
                "modified_at": "2026-04-22T16:47:38.797374615+01:00",
                "details": {},
                "status": "available",
            }
        ]


@router.get("/metrics/flow")
async def get_request_flow() -> dict:
    """Return request flow data for visualization.
    
    Shows the flow of requests through the system:
    User → Router → Agent → LLM → Response
    """
    collector = get_metrics_collector()
    
    # Get current metrics
    active_sessions = 1
    snapshot = await collector.get_snapshot(active_sessions=active_sessions, queue_depth=0)
    
    # Mock flow data - in production this would be collected from actual request tracing
    flow_data = {
        "nodes": [
            {
                "id": "user",
                "label": "User",
                "type": "source",
                "value": snapshot.requests_total,
                "color": "#5eead4",
            },
            {
                "id": "router",
                "label": "Router",
                "type": "process",
                "value": snapshot.requests_total,
                "color": "#a78bfa",
            },
            {
                "id": "agent",
                "label": "Agent",
                "type": "process",
                "value": snapshot.requests_successful,
                "color": "#fbbf24",
            },
            {
                "id": "llm",
                "label": "LLM",
                "type": "destination",
                "value": snapshot.requests_successful,
                "color": "#f87171",
            },
        ],
        "links": [
            {
                "source": "user",
                "target": "router",
                "value": snapshot.requests_total,
                "latency_ms": snapshot.avg_latency_ms * 0.1,
            },
            {
                "source": "router",
                "target": "agent",
                "value": snapshot.requests_total,
                "latency_ms": snapshot.avg_latency_ms * 0.3,
            },
            {
                "source": "agent",
                "target": "llm",
                "value": snapshot.requests_successful,
                "latency_ms": snapshot.avg_latency_ms * 0.6,
            },
        ],
        "summary": {
            "total_requests": snapshot.requests_total,
            "successful_requests": snapshot.requests_successful,
            "failed_requests": snapshot.requests_failed,
            "avg_latency_ms": snapshot.avg_latency_ms,
            "throughput_tps": snapshot.tokens_per_second,
        },
    }
    
    return flow_data


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
            "avg_tokens_per_second": sum(item.get("value", 0) for item in timeline) / len(timeline) if timeline else 0,
        }
    }


@router.get("/analytics")
async def get_analytics() -> dict:
    """Return analytics data for the dashboard.
    
    Provides comprehensive analytics including usage patterns, performance metrics,
    and system health indicators.
    """
    collector = get_metrics_collector()
    store = get_metrics_store()
    
    # Get current metrics
    active_sessions = 1
    snapshot = await collector.get_snapshot(active_sessions=active_sessions, queue_depth=0)
    
    # Get historical data
    history = await store.get_timeline_multi(seconds=3600)
    
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
        "summary": {
            "total_requests": snapshot.requests_total,
            "successful_requests": snapshot.requests_successful,
            "failed_requests": snapshot.requests_failed,
            "uptime_hours": snapshot.uptime_seconds / 3600,
        }
    }
