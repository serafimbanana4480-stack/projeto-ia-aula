"""Tool registry - canonical list of executable tools available to agents."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.persistence.db import log_tool_execution

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


def get_tool(name: str) -> ToolSpec | None:
    return _registry.get(name)


def list_tools(enabled_only: bool = True) -> list[ToolSpec]:
    tools = list(_registry.values())
    if enabled_only:
        tools = [t for t in tools if t.enabled]
    return tools


def set_tool_enabled(name: str, enabled: bool) -> None:
    if name in _registry:
        _registry[name].enabled = enabled


async def execute_tool(name: str, session_id: str | None, args: dict) -> dict:
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
        log_tool_execution(
            session_id=session_id,
            tool_name=name,
            args=args,
            result=result,
            success=True,
            duration_ms=duration_ms,
        )
        return {"tool": name, "result": result, "duration_ms": duration_ms}
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
