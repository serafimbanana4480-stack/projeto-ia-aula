"""Health and readiness endpoints."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.orchestrator.routes.auth import get_current_user

from backend.core.disk_guard import disk_pressure_status

_RUNTIME_ROOT = Path(__file__).resolve().parents[3]


def _disk_pressure_payload() -> dict[str, Any]:
    return disk_pressure_status(_RUNTIME_ROOT)
router = APIRouter()


class ComponentHealth(BaseModel):
    "Health status of a single component."

    status: str
    connected: bool | None = None
    message: str


class SystemHealth(BaseModel):
    "Overall system health status."

    status: str
    timestamp: float
    components: dict[str, ComponentHealth]
    summary: dict[str, int]
    disk_pressure: dict[str, Any] | None = None

# Dependency checkers
dependencies: dict[str, Any] = {}


def register_dependency(name: str, checker: Any) -> None:
    "Register a dependency checker callable."
    dependencies[name] = checker


@router.get("/health")
async def health_check() -> dict[str, Any]:
    "Liveness probe — always returns 200 if the process is running."
    return {
        "status": "healthy",
        "service": "nexus-omega",
        "disk_pressure": _disk_pressure_payload(),
    }


@router.get("/deep", dependencies=[Depends(get_current_user)])
async def deep_health_check() -> dict[str, Any]:
    """Deep health check — requires authentication.

    Performs health checks on all major system components including
    Redis, Qdrant, AgentPool, and WorkflowTracker. Returns detailed
    status for each component and an overall system health status.
    """
    components: dict[str, Any] = {}
    overall_status = "healthy"
    degraded_count = 0
    unhealthy_count = 0

    # Check Redis
    try:
        from backend.knowledge.redis_backend import RedisBackend, REDIS_AVAILABLE

        if REDIS_AVAILABLE:
            redis = RedisBackend()
            if redis.is_connected:
                components["redis"] = {
                    "status": "healthy",
                    "connected": True,
                    "message": "Redis connection active",
                }
            else:
                components["redis"] = {
                    "status": "unhealthy",
                    "connected": False,
                    "message": "Redis connection failed",
                }
                unhealthy_count += 1
        else:
            components["redis"] = {
                "status": "degraded",
                "connected": False,
                "message": "Redis not available",
            }
            degraded_count += 1
    except Exception as e:
        components["redis"] = {
            "status": "unhealthy",
            "connected": False,
            "message": f"Redis check failed: {str(e)}",
        }
        unhealthy_count += 1

    # Check Qdrant
    try:
        from backend.knowledge.qdrant_backend import QdrantBackend, QDRANT_AVAILABLE

        if QDRANT_AVAILABLE:
            qdrant = QdrantBackend()
            collections = qdrant._client.get_collections().collections
            components["qdrant"] = {
                "status": "healthy",
                "connected": True,
                "collections": len(collections),
                "message": f"Qdrant connection active ({len(collections)} collections)",
            }
        else:
            components["qdrant"] = {
                "status": "degraded",
                "connected": False,
                "message": "Qdrant not available",
            }
            degraded_count += 1
    except Exception as e:
        components["qdrant"] = {
            "status": "unhealthy",
            "connected": False,
            "message": f"Qdrant check failed: {str(e)}",
        }
        unhealthy_count += 1

    # Check AgentPool
    try:
        from backend.agents.agent_pool import AgentPool  # noqa: F401

        components["agent_pool"] = {"status": "healthy", "message": "AgentPool available"}
    except Exception as e:
        components["agent_pool"] = {
            "status": "degraded",
            "message": f"AgentPool check failed: {str(e)}",
        }
        degraded_count += 1

    # Check WorkflowTracker
    try:
        from backend.observability.routes.workflows import get_workflow_tracker

        tracker = get_workflow_tracker()
        tracker.list_workflows(limit=1)
        components["workflow_tracker"] = {
            "status": "healthy",
            "message": "WorkflowTracker operational",
        }
    except Exception as e:
        components["workflow_tracker"] = {
            "status": "degraded",
            "message": f"WorkflowTracker check failed: {str(e)}",
        }
        degraded_count += 1

    if unhealthy_count > 0:
        overall_status = "unhealthy"
    elif degraded_count > 0:
        overall_status = "degraded"

    return {
        "status": overall_status,
        "timestamp": time.time(),
        "components": components,
        "summary": {
            "total": len(components),
            "healthy": len([c for c in components.values() if c["status"] == "healthy"]),
            "degraded": degraded_count,
            "unhealthy": unhealthy_count,
        },
        "disk_pressure": _disk_pressure_payload(),
    }


@router.get("/ready")
async def readiness_check() -> dict[str, Any]:
    "Readiness probe — checks all registered dependencies."
    results: dict[str, str] = {}
    all_ready = True

    for name, checker in dependencies.items():
        try:
            if asyncio.iscoroutinefunction(checker):
                result = await checker()
            else:
                result = checker()
            results[name] = "ready" if result else "not_ready"
            if not result:
                all_ready = False
        except Exception as exc:
            results[name] = f"error: {exc}"
            all_ready = False
    status = "ready" if all_ready else "not_ready"

    return {
        "status": status,
        "dependencies": results,
        "disk_pressure": _disk_pressure_payload(),
    }


@router.get("/system/health", response_model=SystemHealth, tags=["health"])
async def system_health_check() -> dict[str, Any]:
    "Alias for deep health info."
    return await deep_health_check()
