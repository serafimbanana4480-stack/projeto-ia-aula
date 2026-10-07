"""Curated, read-only ProjectMind MCP tools for Nexus agents."""

from __future__ import annotations

import re
from typing import Any

from backend.mcp.runtime import MCPRuntimeError, call_connector_tool
from backend.mcp.store import mcp_store
from backend.mcp.store import tool_permission_fingerprint
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
    session_id: str = "",
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
        from backend.tools.sequential_thinking_tool import sequential_thinking as _local

        return await _local(
            thought=thought,
            thought_number=thought_number,
            total_thoughts=total_thoughts,
            next_thought_needed=next_thought_needed,
            session_id=session_id,
        )
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
def _validated_connector(connector_id: str):
    """Return the connector only when it is enabled AND test-validated."""
    connector = mcp_store.get_connector(connector_id)
    if connector is None:
        raise MCPRuntimeError(f"Connector MCP '{connector_id}' não encontrado")
    if not connector.enabled:
        raise MCPRuntimeError(f"Connector MCP desativado: {connector.name}")
    if connector.last_test_status != "ok":
        raise MCPRuntimeError(
            f"Connector MCP '{connector.name}' não está validado "
            f"(last_test_status={connector.last_test_status!r}); corre o teste de ligação primeiro"
        )
    return connector


async def mcp_list_tools(connector_id: str = "") -> dict[str, Any]:
    """List tools of one validated connector, or of every validated connector."""
    from backend.mcp.runtime import list_connector_tools

    if connector_id.strip():
        targets = [_validated_connector(connector_id.strip())]
    else:
        targets = [
            c for c in mcp_store._connectors.values()  # noqa: SLF001
            if c.enabled and c.last_test_status == "ok"
        ]
    out = []
    for connector in targets:
        activity_id = mcp_store.start_activity(
            connector_id=connector.id,
            tool="List MCP tools",
            kind="tool_discovery",
            source="agent",
            phase="tools_list",
            detail="A pedir tools e schemas ao servidor MCP",
        )
        try:
            tools = await list_connector_tools(connector)
        except MCPRuntimeError as exc:
            mcp_store.update_activity(
                activity_id,
                status="error",
                phase="tools_list",
                detail=f"Descoberta falhou ({type(exc).__name__})",
            )
            out.append({"connector_id": connector.id, "connector": connector.name, "error": str(exc)})
            continue
        mcp_store.update_activity(
            activity_id,
            status="ok",
            phase="complete",
            detail=f"{len(tools)} tools descobertas com schema atual",
            result_shape=f"tools: {', '.join(str(item.get('name') or '') for item in tools[:8])}"[:200],
        )
        out.append({"connector_id": connector.id, "connector": connector.name, "tools": tools})
    return {"connectors": out}


async def mcp_call_tool(
    connector_id: str, tool_name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call any tool on any validated MCP connector (generic MCP passthrough)."""
    connector = _validated_connector(connector_id)
    return await call_connector_tool(
        connector.id,
        str(tool_name)[:128],
        arguments if isinstance(arguments, dict) else {},
    )


async def mcp_call_readonly_tool(
    connector_id: str, tool_name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call a tool only when its live MCP declaration marks it read-only."""
    from backend.mcp.runtime import list_connector_tools

    connector = _validated_connector(connector_id)
    tools = await list_connector_tools(connector)
    selected = next((item for item in tools if item.get("name") == tool_name), None)
    if selected is None:
        raise MCPRuntimeError(f"Tool MCP '{tool_name}' não está disponível em {connector.name}")
    annotations = selected.get("annotations") or {}
    if annotations.get("readOnlyHint") is not True or annotations.get("destructiveHint") is True:
        raise MCPRuntimeError(
            f"Tool MCP '{tool_name}' não declarou uma operação só de leitura; usa mcp_call_tool com aprovação"
        )
    approved_fingerprint = connector.readonly_tool_fingerprints.get(tool_name)
    if approved_fingerprint != tool_permission_fingerprint(selected):
        raise MCPRuntimeError(
            f"Tool MCP '{tool_name}' ainda não foi aprovada para chamadas sem confirmação; aprova-a no Control Center ou usa mcp_call_tool"
        )
    return await call_connector_tool(
        connector.id,
        str(tool_name)[:128],
        arguments if isinstance(arguments, dict) else {},
    )


def _recommendation_tokens(value: str) -> set[str]:
    stop_words = {
        "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos", "e", "em", "for",
        "from", "fazer", "me", "na", "nas", "no", "nos", "o", "os", "para", "por", "que",
        "the", "to", "um", "uma", "using", "via", "and", "or", "of", "in", "on",
    }
    return {token for token in re.findall(r"[a-z0-9_]+", value.lower()) if len(token) > 1 and token not in stop_words}


async def mcp_recommend_tools(task: str, limit: int = 5) -> dict[str, Any]:
    """Rank validated MCP tools by deterministic name/description overlap."""
    query = str(task).strip()[:2_000]
    if len(query) < 2:
        raise ValueError("Descreve a tarefa para procurar ferramentas MCP.")
    activity_id = mcp_store.start_activity(
        tool="Recommend MCP tools",
        kind="recommendation",
        source="agent",
        phase="ranking",
        detail="A comparar a tarefa com os nomes e descrições das tools disponíveis",
    )
    terms = _recommendation_tokens(query)
    ranked: list[tuple[int, dict[str, Any]]] = []
    connectors = [
        connector
        for connector in mcp_store._connectors.values()  # noqa: SLF001
        if connector.enabled and connector.last_test_status == "ok"
    ]
    for connector in connectors:
        for tool in connector.tools:
            name = str(tool.get("name") or "")
            description = str(tool.get("description") or tool.get("title") or "")
            searchable = _recommendation_tokens(
                " ".join((connector.name, connector.description, name.replace("_", " "), description))
            )
            score = sum(3 if term in searchable else 0 for term in terms)
            if not score:
                continue
            annotations = tool.get("annotations") or {}
            read_only = annotations.get("readOnlyHint") is True and annotations.get("destructiveHint") is not True
            approved = (
                read_only
                and connector.readonly_tool_fingerprints.get(name) == tool_permission_fingerprint(tool)
            )
            ranked.append((score, {
                "connector_id": connector.id,
                "connector": connector.name,
                "tool_name": name,
                "description": description,
                "input_schema": tool.get("inputSchema") or {"type": "object", "properties": {}},
                "risk": "user_approved_read_only" if approved else "approval_required",
                "call_tool": "mcp_call_readonly_tool" if approved else "mcp_call_tool",
            }))
    ranked.sort(key=lambda item: (-item[0], item[1]["connector"], item[1]["tool_name"]))
    matches = [item for _, item in ranked[: max(1, min(int(limit), 10))]]
    mcp_store.update_activity(
        activity_id,
        status="ok" if matches else "warning",
        phase="complete",
        detail=f"{len(connectors)} connectors pesquisados · {len(matches)} recomendações",
        result_shape="; ".join(f"{item['connector']} / {item['tool_name']}" for item in matches[:4]),
    )
    return {
        "query": query,
        "matches": matches,
        "available_connectors": len(connectors),
        "ranking": "lexical name/description match; read_only_hint is server-declared metadata",
    }


async def mcp_build_from_description(description: str, base_url: str) -> dict[str, Any]:
    """Agent-facing MCP Builder entry point; install is approval-gated in ToolSpec."""
    from backend.mcp.builder import build_from_description
    from backend.orchestrator.main import app

    client = getattr(app.state, "llm_client", None)
    return await build_from_description(description=description, base_url=base_url, llm_client=client)


register_tool(ToolSpec(
    name="mcp_list_tools",
    description="List the tools exposed by validated MCP connectors (one specific, or all of them).",
    tags=["mcp", "discovery", "read"], category="mcp", risk_level="low",
    when_to_use="Before the first MCP call against a connector, to see which tools are actually available.",
    schema={"type": "object", "properties": {
        "connector_id": {"type": "string", "maxLength": 64, "description": "Omit to list every validated connector."},
    }, "additionalProperties": False},
    handler=mcp_list_tools, timeout_seconds=45,
))
register_tool(ToolSpec(
    name="mcp_call_tool",
    description="Call any tool on any validated MCP connector (generic passthrough beyond the curated wrappers).",
    tags=["mcp", "generic", "call", "external"], category="mcp", risk_level="high",
    requires_confirmation=True,
    when_to_use="Call a validated MCP tool that can write, send, execute, or whose effects are unknown; approval is required.",
    schema={"type": "object", "properties": {
        "connector_id": {"type": "string", "maxLength": 64},
        "tool_name": {"type": "string", "maxLength": 128},
        "arguments": {"type": "object", "description": "Arguments forwarded verbatim to the MCP server."},
    }, "required": ["connector_id", "tool_name"], "additionalProperties": False},
    handler=mcp_call_tool, timeout_seconds=55,
))
register_tool(ToolSpec(
    name="mcp_call_readonly_tool",
    description="Call a validated MCP tool only when its live readOnlyHint schema fingerprint has been explicitly approved in the Control Center.",
    tags=["mcp", "read", "discovery"], category="mcp", risk_level="low",
    when_to_use="For a user-approved MCP read tool; live read-only annotations and the approved schema fingerprint are checked again.",
    schema={"type": "object", "properties": {
        "connector_id": {"type": "string", "maxLength": 64},
        "tool_name": {"type": "string", "maxLength": 128},
        "arguments": {"type": "object"},
    }, "required": ["connector_id", "tool_name"], "additionalProperties": False},
    handler=mcp_call_readonly_tool, timeout_seconds=55,
))
register_tool(ToolSpec(
    name="mcp_recommend_tools",
    description="Find the best validated MCP tools for a task using local name/description matching; does not call them.",
    tags=["mcp", "discovery", "recommendation"], category="mcp", risk_level="low",
    when_to_use="Before choosing an MCP tool, especially when several connectors expose similar capabilities.",
    schema={"type": "object", "properties": {
        "task": {"type": "string", "maxLength": 2000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
    }, "required": ["task"], "additionalProperties": False},
    handler=mcp_recommend_tools, timeout_seconds=10,
))
register_tool(ToolSpec(
    name="mcp_builder",
    description="Generate a declarative REST MCP from a natural-language need, create server/schema/config/tests, validate it, then register it only after all gates pass.",
    tags=["mcp", "builder", "code_generation", "integration"], category="mcp", risk_level="high",
    requires_confirmation=True,
    when_to_use="When no validated MCP already covers the task and the user supplied a specific HTTP/S API base URL.",
    schema={"type": "object", "properties": {
        "description": {"type": "string", "minLength": 8, "maxLength": 4000},
        "base_url": {"type": "string", "minLength": 8, "maxLength": 500},
    }, "required": ["description", "base_url"], "additionalProperties": False},
    handler=mcp_build_from_description, timeout_seconds=120,
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
        "session_id": {"type": "string", "description": "Optional session id to scope the thinking chain.", "default": ""},
    }, "required": ["thought", "thought_number", "total_thoughts"], "additionalProperties": False},
    handler=mcp_sequential_thinking, timeout_seconds=55,
))
