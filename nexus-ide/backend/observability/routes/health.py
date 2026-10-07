"""Health and readiness endpoints.

Liveness vs readiness, stated explicitly (audit P1-5):

* ``GET /api/health`` — **liveness, cheap and unauthenticated.**  It performs no
  dependency I/O, so an orchestrator probe cannot be locked out by an auth
  outage or a slow Redis.  It answers "is this process serving requests?".
* ``GET /api/deep`` and ``GET /api/system/health`` — **authenticated**.  They
  report internal topology (Redis, Qdrant, agent pool, workflow tracker) and
  must not be reachable anonymously.  ``/api/system/health`` used to *call*
  ``deep_health_check()`` while dropping the dependency entirely, so it was a
  strictly-less-protected alias of a protected endpoint.
* ``GET /api/ready`` — **readiness**, cheap and unauthenticated (it is a probe).
  It is now actually able to fail: the dependency probes are registered by
  default, whereas ``register_dependency`` used to be called from nowhere and
  the empty dict made the endpoint unconditionally ``ready``.

Liveness being open is a deliberate trade-off, not an oversight: exposing
"process is up" costs nothing, and gating it would make k8s/Docker restart a
healthy pod whenever the auth database is briefly unreachable.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.core.disk_guard import disk_pressure_status
from backend.middleware.auth import require_auth

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


# Dependency checkers for the readiness probe.
dependencies: dict[str, Any] = {}


def register_dependency(name: str, checker: Any) -> None:
    """Register a readiness checker callable (sync or async)."""
    dependencies[name] = checker


# ---------------------------------------------------------------------------
# Default readiness probes
# ---------------------------------------------------------------------------
def _check_database_ready() -> bool:
    """The persistence layer must accept a trivial read."""
    try:
        from backend.persistence.db import get_session

        get_session("__readiness_probe__")
        return True
    except Exception:
        return False


def _check_disk_ready() -> bool:
    """Readiness fails when the volume is critically full.

    A process that cannot write is not ready to accept work, and NEXUS writes a
    checkpoint on nearly every operation.
    """
    payload = _disk_pressure_payload()
    snapshot = payload.get("snapshot", {}) if isinstance(payload, dict) else {}
    status = payload.get("status") if isinstance(payload, dict) else ""
    if status == "critical":
        return False
    free_percent = snapshot.get("free_percent")
    return not isinstance(free_percent, (int, float)) or free_percent > 1.0


def _check_workflow_tracker_ready() -> bool:
    try:
        from backend.observability.routes.workflows import get_workflow_tracker

        return get_workflow_tracker() is not None
    except Exception:
        return False


def _check_agent_pool_ready() -> bool:
    """The agent pool must be importable and constructible.

    Replaces the old ``from backend.agents.agent_pool import AgentPool`` probe,
    which imported a module that does not exist and therefore reported
    ``degraded`` on every single call — a permanently false health signal.
    The real class lives in :mod:`backend.orchestrator.agent_pool`.
    """
    try:
        from backend.orchestrator.agent_pool import get_agent_pool

        return get_agent_pool() is not None
    except Exception:
        return False


#: Registered at import so ``/api/ready`` can actually fail.  Additional probes
#: can be added by the app with :func:`register_dependency`.
_DEFAULT_DEPENDENCIES: dict[str, Callable[[], Any]] = {
    "database": _check_database_ready,
    "disk": _check_disk_ready,
    "agent_pool": _check_agent_pool_ready,
    "workflow_tracker": _check_workflow_tracker_ready,
}
for _name, _checker in _DEFAULT_DEPENDENCIES.items():
    dependencies.setdefault(_name, _checker)


@router.get("/health")
async def health_check() -> dict[str, Any]:
    "Liveness probe — always returns 200 if the process is running."
    return {
        "status": "healthy",
        "service": "nexus-omega",
        "disk_pressure": _disk_pressure_payload(),
    }


@router.get("/deep", dependencies=[Depends(require_auth)])
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
        from backend.knowledge.redis_backend import REDIS_AVAILABLE, RedisBackend

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
                "message": "Redis not available (optional dependency)",
            }
            degraded_count += 1
    except Exception as e:
        components["redis"] = {
            "status": "unhealthy",
            "connected": False,
            "message": f"Redis check failed: {str(e)[:200]}",
        }
        unhealthy_count += 1

    # Check Qdrant
    try:
        from backend.knowledge.qdrant_backend import QDRANT_AVAILABLE, QdrantBackend

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
                "message": "Qdrant not available (optional dependency)",
            }
            degraded_count += 1
    except Exception as e:
        components["qdrant"] = {
            "status": "unhealthy",
            "connected": False,
            "message": f"Qdrant check failed: {str(e)[:200]}",
        }
        unhealthy_count += 1

    # Check AgentPool — the real module is backend.orchestrator.agent_pool.
    # The previous probe imported backend.agents.agent_pool, which does not
    # exist, so agent_pool reported "degraded" forever and dragged the whole
    # report to "degraded" on every call.
    if _check_agent_pool_ready():
        components["agent_pool"] = {"status": "healthy", "message": "AgentPool available"}
    else:
        components["agent_pool"] = {
            "status": "degraded",
            "message": "AgentPool unavailable",
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
            "message": f"WorkflowTracker check failed: {str(e)[:200]}",
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


# ``response_model=None`` is required, not cosmetic: the strict branch returns a
# JSONResponse, and FastAPI 0.140 refuses to build a Pydantic field from a union
# of ``dict`` and a Response subclass. The payload is a plain dict of
# JSON-serialisable values either way, so dropping the inferred model changes no
# response body -- it only stops FastAPI from filtering one that never filtered
# anything out.
@router.get("/ready", response_model=None)
async def readiness_check(strict: bool = False) -> dict[str, Any] | JSONResponse:
    """Readiness probe — checks all registered dependencies.

    Args:
        strict: return HTTP 503 when not ready, for orchestrators that only
            look at the status code.  The default stays HTTP 200 because the
            documented contract (``docs/auditorias/NEXUS_TEST_MATRIX.md``) is
            "200 with the body carrying the verdict", and changing the default
            would break probes that treat 5xx as "the process is dead".

    The return annotation admits ``JSONResponse`` because the strict branch
    returns one.
    """
    results: dict[str, str] = {}
    all_ready = True

    for name, checker in list(dependencies.items()):
        try:
            if asyncio.iscoroutinefunction(checker):
                result = await checker()
            else:
                result = checker()
            results[name] = "ready" if result else "not_ready"
            if not result:
                all_ready = False
        except Exception as exc:
            results[name] = f"error: {str(exc)[:200]}"
            all_ready = False
    status = "ready" if all_ready else "not_ready"

    payload: dict[str, Any] = {
        "status": status,
        "dependencies": results,
        "disk_pressure": _disk_pressure_payload(),
    }
    if strict and not all_ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


@router.get(
    "/system/health",
    response_model=SystemHealth,
    tags=["health"],
    # Audit P1-5: the alias used to call ``deep_health_check()`` with no
    # dependency at all, so the least protected path to internal topology was
    # ``/api/system/health``.  It now enforces the same ``require_auth``.
    dependencies=[Depends(require_auth)],
)
async def system_health_check() -> dict[str, Any]:
    "Alias for deep health info. Requires authentication, like /api/deep."
    return await deep_health_check()
