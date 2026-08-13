"""Bounded MCP client used by the Nexus agent tool registry."""

from __future__ import annotations

import asyncio
import io
import os
from typing import Any

from backend.mcp.store import MCPConnector, mcp_store


class MCPRuntimeError(RuntimeError):
    """A connector could not be used for a real MCP request."""


def _exception_text(exc: BaseException) -> str:
    """Keep nested AnyIO/ExceptionGroup failures useful in the UI."""
    nested = getattr(exc, "exceptions", None)
    if nested:
        details = [_exception_text(item) for item in nested if isinstance(item, BaseException)]
        if details:
            return "; ".join(details)
    return str(exc) or type(exc).__name__


def _tool_payload(tool: Any) -> dict[str, Any]:
    return {
        "name": str(getattr(tool, "name", "")),
        "title": str(getattr(tool, "title", "") or ""),
        "description": str(getattr(tool, "description", "") or ""),
        "inputSchema": getattr(tool, "inputSchema", {}) or {},
    }


def _content_payload(content: Any) -> dict[str, Any]:
    if hasattr(content, "model_dump"):
        try:
            value = content.model_dump(mode="json")
            return value if isinstance(value, dict) else {"value": value}
        except Exception:  # pragma: no cover
            pass
    if isinstance(content, dict):
        return content
    return {"type": type(content).__name__, "text": str(content)}


def _server_parameters(connector: MCPConnector) -> Any:
    try:
        from mcp import StdioServerParameters
    except ImportError as exc:  # pragma: no cover
        raise MCPRuntimeError("Dependência MCP Python não instalada no runtime do Nexus") from exc
    if connector.transport != "stdio":
        raise MCPRuntimeError("O runtime de agentes suporta atualmente apenas MCP stdio")
    if not connector.command:
        raise MCPRuntimeError("Connector MCP sem comando")
    return StdioServerParameters(
        command=connector.command,
        args=list(connector.args),
        env={**os.environ, **{k: v for k, v in connector.env.items() if v}},
        cwd=connector.source_root or None,
    )


async def _with_session(connector: MCPConnector, operation, *, timeout: float) -> Any:
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client
    except ImportError as exc:  # pragma: no cover
        raise MCPRuntimeError("Dependência MCP Python não instalada no runtime do Nexus") from exc

    errlog = io.StringIO()

    async def run() -> Any:
        params = _server_parameters(connector)
        async with (
            stdio_client(params, errlog=errlog) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            return await operation(session)

    try:
        return await asyncio.wait_for(run(), timeout=max(1.0, min(float(timeout), 60.0)))
    except TimeoutError as exc:
        raise MCPRuntimeError(f"MCP excedeu o timeout de {timeout:.0f}s") from exc
    except MCPRuntimeError:
        raise
    except Exception as exc:
        detail = _exception_text(exc)
        stderr = errlog.getvalue().strip().splitlines()
        if stderr:
            detail = f"{detail}; {stderr[-1]}"
        raise MCPRuntimeError(f"Falha no MCP {connector.name}: {detail[:800]}") from exc


async def list_connector_tools(connector: MCPConnector, *, timeout: float = 35.0) -> list[dict[str, Any]]:
    result = await _with_session(connector, lambda session: session.list_tools(), timeout=timeout)
    return [_tool_payload(tool) for tool in getattr(result, "tools", ())]


async def call_connector_tool(
    connector_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    timeout: float = 45.0,
) -> dict[str, Any]:
    connector = mcp_store.get_connector(connector_id)
    if connector is None:
        raise MCPRuntimeError("Connector MCP não encontrado")
    if not connector.enabled:
        raise MCPRuntimeError(f"Connector MCP desativado: {connector.name}")
    started = asyncio.get_running_loop().time()
    args = arguments if isinstance(arguments, dict) else {}

    async def operation(session: Any) -> Any:
        tools = await session.list_tools()
        available = {str(getattr(tool, "name", "")) for tool in getattr(tools, "tools", ())}
        if tool_name not in available:
            raise MCPRuntimeError(f"Tool MCP '{tool_name}' não está disponível em {connector.name}")
        return await session.call_tool(tool_name, arguments=args)

    recorded = False
    try:
        result = await _with_session(connector, operation, timeout=timeout)
        elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000
        payload = {
            "isError": bool(getattr(result, "isError", False)),
            "content": [_content_payload(item) for item in getattr(result, "content", ())],
            "structuredContent": getattr(result, "structuredContent", None),
        }
        ok = not payload["isError"]
        mcp_store.record_tool_call(connector_id, tool_name, elapsed_ms, success=ok)
        recorded = True
        if not ok:
            raise MCPRuntimeError(f"Tool MCP '{tool_name}' devolveu isError=true")
        return {"connector_id": connector_id, "connector": connector.name, "tool": tool_name, "latency_ms": round(elapsed_ms, 1), "result": payload}
    except Exception:
        elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000
        if not recorded:
            mcp_store.record_tool_call(connector_id, tool_name, elapsed_ms, success=False)
        raise
