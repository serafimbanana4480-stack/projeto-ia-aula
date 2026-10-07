"""System health tool — aggregate backend, LLM, MCP, Redis, disk, and memory health.

This module owns the implementation and registers the **single canonical**
health tool, ``get_system_health``.

Audit P1-7: ``system_health`` and ``get_system_health`` were the same tool
registered twice under two names by two modules.  Two entries in the catalog
means the model picks a name at random and the allow-list in
``registry._AUTONOMOUS_READ_ONLY_TOOLS`` only covered one of them.
``get_system_health`` is kept as the canonical name because it is the one
already listed in that read-only allow-list;
:mod:`backend.tools.system_tools` now re-exports this implementation instead of
registering a second copy.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import UTC, datetime
from typing import Any

from backend.config.settings import get_settings
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

#: Canonical tool name.  ``system_health`` is the historical alias and is
#: resolved by ``_TOOL_MODULE_HINTS`` / ``registry.ALIASES`` only.
CANONICAL_TOOL_NAME = "get_system_health"


def _check_backend() -> dict[str, Any]:
    return {"status": "online", "detail": "Backend process is running."}


def _check_llm_providers() -> dict[str, Any]:
    providers: dict[str, Any] = {}
    get_settings()
    try:
        from backend.llm.factory import create_llm_client

        client = create_llm_client()
        provider_name = getattr(client, "provider_name", None) or getattr(client, "name", "unknown")
        providers[provider_name] = {"status": "configured", "detail": "LLM client instantiated."}
    except Exception as exc:
        providers["default"] = {"status": "degraded", "detail": str(exc)}
    return providers


def _check_mcp() -> dict[str, Any]:
    connectors: dict[str, Any] = {}
    try:
        from backend.mcp.store import mcp_store

        for connector_id, connector in mcp_store._connectors.items():
            connectors[connector_id] = {
                "status": "enabled" if connector.enabled else "disabled",
                "template_id": getattr(connector, "template_id", None),
                "last_test_status": getattr(connector, "last_test_status", "unknown"),
            }
    except Exception as exc:
        connectors["error"] = {"status": "unavailable", "detail": str(exc)}
    return connectors


def _check_redis() -> dict[str, Any]:
    try:
        from backend.redis_cache import get_sync_cache

        cache = get_sync_cache()
        cache.ping()
        return {"status": "online"}
    except Exception as exc:
        return {"status": "offline", "detail": str(exc)}


def _check_disk() -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(os.getcwd())
        free_gb = round(usage.free / (1 << 30), 2)
        total_gb = round(usage.total / (1 << 30), 2)
        pct_free = round((usage.free / usage.total) * 100, 1) if usage.total else 0.0
        status = "healthy"
        if pct_free < 10:
            status = "critical"
        elif pct_free < 20:
            status = "warning"
        return {
            "status": status,
            "free_gb": free_gb,
            "total_gb": total_gb,
            "percent_free": pct_free,
        }
    except Exception as exc:
        return {"status": "unknown", "detail": str(exc)}


def _check_memory() -> dict[str, Any]:
    try:
        import psutil

        mem = psutil.virtual_memory()
        return {
            "status": "healthy" if mem.percent < 90 else "warning",
            "total_gb": round(mem.total / (1 << 30), 2),
            "available_gb": round(mem.available / (1 << 30), 2),
            "percent_used": mem.percent,
        }
    except ImportError:
        return {"status": "unknown", "detail": "psutil not installed"}
    except Exception as exc:
        return {"status": "unknown", "detail": str(exc)}


async def system_health() -> dict[str, Any]:
    """Aggregate health from all NEXUS subsystems.

    Returns a dict with per-subsystem status and an overall health verdict.
    """
    backend = _check_backend()
    llm = _check_llm_providers()
    mcp = _check_mcp()
    redis = _check_redis()
    disk = _check_disk()
    memory = _check_memory()

    services = {
        "backend": backend,
        "llm_providers": llm,
        "mcp": mcp,
        "redis": redis,
        "disk": disk,
        "memory": memory,
    }

    def _is_healthy(svc: Any) -> bool:
        if isinstance(svc, dict):
            if "status" in svc:
                return svc["status"] in ("online", "healthy", "configured", "enabled")
            return all(_is_healthy(v) for v in svc.values() if isinstance(v, dict))
        return True

    all_healthy = all(_is_healthy(v) for v in services.values())
    any_offline = any(
        isinstance(v, dict) and v.get("status") == "offline"
        for v in services.values()
        if isinstance(v, dict)
    )

    overall = "healthy" if all_healthy else ("degraded" if not any_offline else "unhealthy")

    return {
        "ok": True,
        "status": overall,
        "timestamp": datetime.now(UTC).isoformat(),
        "services": services,
    }


register_tool(
    ToolSpec(
        name=CANONICAL_TOOL_NAME,
        description=(
            "Aggregate health from all NEXUS subsystems: backend, LLM providers, "
            "MCP connectors, Redis, disk pressure, and memory usage. Returns an "
            "overall health verdict and per-subsystem details."
        ),
        tags=["system", "health", "monitoring"],
        category="system",
        risk_level="low",
        when_to_use="When diagnosing environment issues or verifying that all subsystems are operational.",
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=system_health,
        timeout_seconds=30,
    )
)

#: Backwards-compatible Python alias for the historical name.  Not registered:
#: a second catalog entry for the same code is what the audit flagged.
get_system_health = system_health
