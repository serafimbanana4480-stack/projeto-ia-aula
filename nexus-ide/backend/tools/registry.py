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
    tags: list[str] = field(default_factory=list)
    risk_level: str = "low"
    requires_confirmation: bool = False
    when_to_use: str = ""
    examples: list[dict] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Awaitable[Any]] | None = None
    enabled: bool = True
    # --- Discovery metadata (used by AI agents and dashboard) ---
    tags: list[str] = field(default_factory=list)
    risk_level: str = "low"  # "low" | "medium" | "high"
    requires_confirmation: bool = False
    when_to_use: str = ""
    examples: list[dict[str, Any]] = field(default_factory=list)
    category: str = ""  # file, web, code, git, docker, system, data, etc.


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


# ---------------------------------------------------------------------------
# Discovery helpers (used by AI agents, dashboard, and the orchestrator)
# ---------------------------------------------------------------------------
def list_tools_by_category(enabled_only: bool = True) -> dict[str, list[ToolSpec]]:
    """Group enabled tools by category. Categories with no tools are omitted."""
    out: dict[str, list[ToolSpec]] = {}
    for tool in list_tools(enabled_only=enabled_only):
        cat = tool.category or "uncategorised"
        out.setdefault(cat, []).append(tool)
    return out


def list_tools_by_tag(tag: str, enabled_only: bool = True) -> list[ToolSpec]:
    """Return tools that have the given tag."""
    return [t for t in list_tools(enabled_only=enabled_only) if tag in t.tags]


def search_tools(query: str, enabled_only: bool = True) -> list[ToolSpec]:
    """Fuzzy search tools by name, description, tag, or category.

    Args:
        query: Free-text search string. Case-insensitive.

    Returns:
        Tools whose name, description, tags, or category contain the query.
        Sorted by relevance (name match > description > tag > category).
    """
    if not query:
        return []
    q = query.lower().strip()
    scored: list[tuple[int, ToolSpec]] = []
    for tool in list_tools(enabled_only=enabled_only):
        score = 0
        if q in tool.name.lower():
            score += 10
        if q in tool.description.lower():
            score += 5
        for tag in tool.tags:
            if q in tag.lower():
                score += 3
        if tool.category and q in tool.category.lower():
            score += 2
        if score > 0:
            scored.append((score, tool))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored]


def get_tools_for_agent(agent_name: str) -> list[ToolSpec]:
    """Return tools relevant to a given agent type.

    Mapping is loose: the agent name is matched against tool tags, the category,
    and the tool name. Returns the union of matches.
    """
    if not agent_name:
        return list_tools()
    agent = agent_name.upper()
    matched: set[str] = set()
    for tool in list_tools():
        # Check tags
        for tag in tool.tags:
            if tag.upper() in agent or agent in tag.upper():
                matched.add(tool.name)
        # Check category
        if tool.category and tool.category.upper() in agent:
            matched.add(tool.name)
        # Check name
        if agent in tool.name.upper():
            matched.add(tool.name)
    return [t for t in list_tools() if t.name in matched] or list_tools()


def get_tool_descriptions_for_llm(
    agent_name: str | None = None,
    include_examples: bool = True,
    include_risk: bool = True,
    max_tools: int | None = None,
) -> str:
    """Return a formatted text block describing tools, suitable for system prompts.

    Args:
        agent_name: If provided, filter to tools relevant to that agent.
        include_examples: Include 1 example per tool.
        include_risk: Include risk level annotation.
        max_tools: Limit the number of tools (useful for small-context models).

    Returns:
        A multi-line text block ready to be appended to a system prompt.
    """
    tools = get_tools_for_agent(agent_name) if agent_name else list_tools()
    if max_tools is not None:
        tools = tools[:max_tools]
    lines: list[str] = ["# Available Tools", ""]
    current_cat = None
    for tool in tools:
        if tool.category and tool.category != current_cat:
            current_cat = tool.category
            lines.append(f"## {current_cat.title()}")
            lines.append("")
        risk = f" [RISK: {tool.risk_level}]" if include_risk and tool.risk_level != "low" else ""
        conf = " [requires confirmation]" if tool.requires_confirmation else ""
        lines.append(f"- `{tool.name}`{risk}{conf} — {tool.description}")
        if tool.when_to_use:
            lines.append(f"  - When: {tool.when_to_use}")
        if include_examples and tool.examples:
            ex = tool.examples[0]
            ex_args = ", ".join(f"{k}={v!r}" for k, v in ex.items())
            lines.append(f"  - Example: `{tool.name}({ex_args})`")
    return "\n".join(lines)


def get_tool_stats() -> dict[str, Any]:
    """Return summary statistics about the registered tools."""
    tools = list_tools()
    by_cat: dict[str, int] = {}
    by_risk: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    confirmation_count = 0
    for t in tools:
        by_cat[t.category or "uncategorised"] = by_cat.get(t.category or "uncategorised", 0) + 1
        by_risk[t.risk_level] = by_risk.get(t.risk_level, 0) + 1
        if t.requires_confirmation:
            confirmation_count += 1
    return {
        "total": len(tools),
        "by_category": by_cat,
        "by_risk": by_risk,
        "requires_confirmation": confirmation_count,
    }


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
