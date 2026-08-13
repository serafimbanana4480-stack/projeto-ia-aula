"""Curated, read-only ProjectMind MCP tools for Nexus agents."""

from __future__ import annotations

from typing import Any

from backend.mcp.runtime import MCPRuntimeError, call_connector_tool
from backend.mcp.store import mcp_store
from backend.tools.registry import ToolSpec, register_tool


def _projectmind_connector():
    candidates = [
        c for c in mcp_store._connectors.values()  # noqa: SLF001
        if c.template_id == "projectmind" and c.enabled and c.last_test_status == "ok"
    ]
    return sorted(candidates, key=lambda item: item.updated_at, reverse=True)[0] if candidates else None


async def _call_projectmind(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    connector = _projectmind_connector()
    if connector is None:
        raise MCPRuntimeError("Nenhum ProjectMind MCP validado está ativo")
    return await call_connector_tool(connector.id, tool_name, arguments)


async def mcp_project_context(task: str, mode: str = "surgical", token_budget: int = 1200, depth: int = 2) -> dict[str, Any]:
    return await _call_projectmind("get_relevant_context", {
        "task": str(task)[:12000],
        "mode": str(mode)[:32],
        "token_budget": max(200, min(int(token_budget), 4000)),
        "depth": max(1, min(int(depth), 4)),
        "include_memory": True,
    })


async def mcp_impact_analysis(node_id_or_diff: str) -> dict[str, Any]:
    return await _call_projectmind("impact_analysis", {"node_id_or_diff": str(node_id_or_diff)[:16000]})


async def mcp_project_status() -> dict[str, Any]:
    return await _call_projectmind("status", {})


def _sequential_connector():
    candidates = [
        c for c in mcp_store._connectors.values()  # noqa: SLF001
        if c.template_id == "sequential-thinking" and c.enabled and c.last_test_status == "ok"
    ]
    return sorted(candidates, key=lambda item: item.updated_at, reverse=True)[0] if candidates else None


async def mcp_sequential_thinking(
    thought: str,
    thought_number: int,
    total_thoughts: int,
    next_thought_needed: bool = True,
    complexity: int = 10,
    architecture: bool = False,
    debugging_attempts: int = 0,
    confidence: float = 0.5,
) -> dict[str, Any]:
    """Use Sequential Thinking only when the task crosses the complexity gate."""
    should_use = (
        int(complexity) >= 7
        or bool(architecture)
        or int(debugging_attempts) >= 2
        or float(confidence) < 0.7
    )
    if not should_use:
        return {"skipped": True, "reason": "complexity/architecture/debugging/confidence gate"}
    connector = _sequential_connector()
    if connector is None:
        raise MCPRuntimeError("Sequential Thinking MCP não está validado e ativo")
    return await call_connector_tool(connector.id, "sequentialthinking", {
        "thought": str(thought)[:6000],
        "thoughtNumber": max(1, min(int(thought_number), 32)),
        "totalThoughts": max(1, min(int(total_thoughts), 32)),
        "nextThoughtNeeded": bool(next_thought_needed),
        "isRevision": False,
    })


register_tool(ToolSpec(
    name="mcp_project_context",
    description="Retrieve token-budgeted semantic project context through validated ProjectMind MCP.",
    tags=["mcp", "projectmind", "semantic", "read"], category="mcp", risk_level="low",
    when_to_use="Before a non-trivial code change when semantic context can replace reading large files.",
    schema={"type": "object", "properties": {
        "task": {"type": "string", "maxLength": 12000}, "mode": {"type": "string", "default": "surgical"},
        "token_budget": {"type": "integer", "minimum": 200, "maximum": 4000, "default": 1200},
        "depth": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2},
    }, "required": ["task"], "additionalProperties": False},
    handler=mcp_project_context, timeout_seconds=55,
))
register_tool(ToolSpec(
    name="mcp_impact_analysis",
    description="Estimate the blast radius of a symbol or unified diff through ProjectMind without writing files.",
    tags=["mcp", "projectmind", "impact", "read"], category="mcp", risk_level="low",
    when_to_use="Before changing a shared symbol or applying a broad diff.",
    schema={"type": "object", "properties": {"node_id_or_diff": {"type": "string", "maxLength": 16000}},
            "required": ["node_id_or_diff"], "additionalProperties": False},
    handler=mcp_impact_analysis, timeout_seconds=55,
))
register_tool(ToolSpec(
    name="mcp_project_status",
    description="Read ProjectMind index, memory, plan, and telemetry counts.",
    tags=["mcp", "projectmind", "health", "read"], category="mcp", risk_level="low",
    when_to_use="When verifying that the semantic MCP index is healthy.",
    schema={"type": "object", "properties": {}, "additionalProperties": False},
    handler=mcp_project_status, timeout_seconds=45,
))
register_tool(ToolSpec(
    name="mcp_sequential_thinking",
    description="Use the validated Sequential Thinking MCP only for complex/architectural/debugging tasks.",
    tags=["mcp", "sequential-thinking", "reasoning"], category="mcp", risk_level="low",
    when_to_use="Only when complexity is at least 7/10, architecture is involved, debugging already failed twice, or confidence is below 0.7.",
    schema={"type": "object", "properties": {
        "thought": {"type": "string", "maxLength": 6000}, "thought_number": {"type": "integer", "minimum": 1, "maximum": 32},
        "total_thoughts": {"type": "integer", "minimum": 1, "maximum": 32}, "next_thought_needed": {"type": "boolean", "default": True},
        "complexity": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10}, "architecture": {"type": "boolean", "default": False},
        "debugging_attempts": {"type": "integer", "minimum": 0, "maximum": 10, "default": 0}, "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
    }, "required": ["thought", "thought_number", "total_thoughts"], "additionalProperties": False},
    handler=mcp_sequential_thinking, timeout_seconds=55,
))
