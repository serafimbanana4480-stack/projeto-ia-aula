"""Tool registry - canonical list of executable tools available to agents."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.persistence.db import log_tool_execution

# Tool result cache — best-effort; system works without it
try:
    from backend.cache.tool_result_cache import get_tool_cache

    _HAVE_TOOL_CACHE = True
except ImportError:
    _HAVE_TOOL_CACHE = False

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Awaitable[Any]] | None = None
    enabled: bool = True


_registry: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> ToolSpec:
    _registry[spec.name] = spec
    logger.info("Registered tool: %s", spec.name)
    return spec


def _maybe_register() -> None:
    """Trigger lazy tool registration if it hasn't happened yet."""
    try:
        from backend.tools import _ensure_tools_registered

        _ensure_tools_registered()
    except ImportError:
        pass


def get_tool(name: str) -> ToolSpec | None:
    _maybe_register()
    return _registry.get(name)


def list_tools(enabled_only: bool = True) -> list[ToolSpec]:
    _maybe_register()
    tools = list(_registry.values())
    if enabled_only:
        tools = [t for t in tools if t.enabled]
    return tools


def set_tool_enabled(name: str, enabled: bool) -> None:
    if name in _registry:
        _registry[name].enabled = enabled


def _handler_result_failed(result: Any) -> str | None:
    """Return an error message when a handler result dict indicates failure."""
    if not isinstance(result, dict):
        return None
    if result.get("error"):
        return str(result["error"])
    if result.get("written") is False:
        return str(result.get("error") or "Write operation failed")
    if result.get("deleted") is False:
        return str(result.get("error") or "Delete operation failed")
    if result.get("moved") is False:
        return str(result.get("error") or "Move operation failed")
    return None


async def execute_tool(name: str, session_id: str | None, args: dict) -> dict:
    # Check cache for idempotent tools
    if _HAVE_TOOL_CACHE:
        try:
            cache = get_tool_cache()
            cached = cache.get(name, args)
            if cached is not None:
                logger.debug("[TOOL CACHE] Hit for %s: %s", name, cached.get("_cached_preview", ""))
                return {**cached, "_from_cache": True, "_cache_hit": True}
        except Exception:
            pass  # Cache is best-effort

    _maybe_register()
    spec = get_tool(name)
    if not spec:
        return {"error": f"Tool '{name}' not found"}
    if not spec.enabled:
        return {"error": f"Tool '{name}' is disabled"}
    if not spec.handler:
        return {"error": f"Tool '{name}' has no handler"}

    start = time.time()
    try:
        result = await spec.handler(**args)
        duration_ms = int((time.time() - start) * 1000)
        handler_error = _handler_result_failed(result)
        if handler_error:
            log_tool_execution(
                session_id=session_id,
                tool_name=name,
                args=args,
                result=result,
                success=False,
                error=handler_error,
                duration_ms=duration_ms,
            )
            return {
                "tool": name,
                "error": handler_error,
                "result": result,
                "duration_ms": duration_ms,
            }
        log_tool_execution(
            session_id=session_id,
            tool_name=name,
            args=args,
            result=result,
            success=True,
            duration_ms=duration_ms,
        )
        response = {"tool": name, "result": result, "duration_ms": duration_ms}
        # Store in cache after successful execution
        if _HAVE_TOOL_CACHE:
            try:
                cache = get_tool_cache()
                cache.store(name, args, response)
            except Exception:
                pass  # Cache is best-effort
        return response
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        log_tool_execution(
            session_id=session_id,
            tool_name=name,
            args=args,
            result=None,
            success=False,
            error=str(e),
            duration_ms=duration_ms,
        )
        return {"tool": name, "error": str(e), "duration_ms": duration_ms}
