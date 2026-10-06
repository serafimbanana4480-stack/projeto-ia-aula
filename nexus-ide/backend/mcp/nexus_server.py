"""NEXUS IDE as an MCP server — exposes the internal tool registry to other AI clients.

Run (stdio):

    .venv\\Scripts\\python.exe -m backend.mcp.nexus_server

Client configuration (LM Studio, Claude Desktop, opencode, ...):

    {
      "mcpServers": {
        "nexus-ide": {
          "command": "C:\\Users\\rodri\\Desktop\\nexus\\nexus-ide\\.venv\\Scripts\\python.exe",
          "args": ["-m", "backend.mcp.nexus_server"],
          "cwd": "C:\\Users\\rodri\\Desktop\\nexus\\nexus-ide"
        }
      }
    }

For opencode: add the same block under ``"mcp"`` in ``opencode.json`` (or use
``opencode mcp add``). For Claude Desktop put it in ``claude_desktop_config.json``.
For LM Studio use the ``mcpServers`` entry of ``~/.lmstudio/mcp.json``.

Safety: only tools matching the safe allow-list (read_/list_/search_/git-read,
write_file, append_file, run_tests, run_lint, type_check, format_code, get_*)
are exported by default. Tools that require confirmation (git_push, deletes,
absolute writes, browser, ...) are never exported. ``run_shell``/``execute_shell``
are only exported when the environment variable ``NEXUS_MCP_ALLOW_SHELL=1`` is
set for the server process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

logger = logging.getLogger(__name__)

SERVER_NAME = "nexus-ide"

#: Name recorded in tool_executions for calls that arrive through this server.
MCP_SESSION_ID = "mcp_server"

#: Stems considered safe to export to external MCP clients.
_SAFE_TOOL_STEMS: tuple[str, ...] = ("read_", "list_", "search_", "get_")

#: Exact names considered safe even without a safe stem.
_SAFE_EXACT_TOOLS: frozenset[str] = frozenset(
    {
        "write_file",
        "append_file",
        "run_tests",
        "run_lint",
        "type_check",
        "format_code",
        "git_status",
        "get_commit_history",
        "get_commit_statistics",
    }
)

#: Never exported, even when the shell gate is open.
_BLOCKED_TOOLS: frozenset[str] = frozenset(
    {
        "run_shell",
        "execute_shell",
        "git_push",
        "git_operation",
        "install_dependency",
    }
)

#: Only exported when ``NEXUS_MCP_ALLOW_SHELL=1``.
_SHELL_TOOLS: frozenset[str] = frozenset({"run_shell", "execute_shell"})


def _shell_allowed() -> bool:
    return os.environ.get("NEXUS_MCP_ALLOW_SHELL") == "1"


def is_exportable_tool(spec: Any) -> bool:
    """Return whether a registry ToolSpec may be exported to external MCP clients."""
    name = getattr(spec, "name", "")
    if not name:
        return False
    if not (getattr(spec, "enabled", False) and getattr(spec, "available", False)):
        return False
    if getattr(spec, "handler", None) is None:
        return False
    if getattr(spec, "risk_level", "low") in {"high", "critical"}:
        return False
    if name in _SHELL_TOOLS:
        return _shell_allowed()
    if name in _BLOCKED_TOOLS:
        return False
    from backend.tools.registry import tool_requires_confirmation

    if tool_requires_confirmation(spec):
        return False
    return name in _SAFE_EXACT_TOOLS or name.startswith(_SAFE_TOOL_STEMS)


def exportable_tools() -> list[Any]:
    """ToolSpecs from the registry that this server exports."""
    from backend.tools.registry import list_tools

    return [spec for spec in list_tools(enabled_only=True) if is_exportable_tool(spec)]


def _tool_definition(spec: Any) -> Tool:
    schema = spec.schema or {"type": "object", "properties": {}}
    return Tool(
        name=spec.name,
        description=spec.description or spec.name,
        inputSchema=schema,
    )


def _json_text(payload: Any) -> TextContent:
    return TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))


async def _call_exported_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run only tools this MCP server actually advertises.

    MCP clients can call a tool by name without first asking for the catalog,
    so filtering ``list_tools`` alone is not an authorization boundary.
    Confirmation remains enabled as a second check if export policy changes.
    """
    spec = next((candidate for candidate in exportable_tools() if candidate.name == name), None)
    if spec is None:
        return {
            "tool": name,
            "ok": False,
            "error": f"Tool '{name}' was not found or is not exposed by the NEXUS MCP server.",
            "error_category": "not_exported",
        }

    from backend.tools.registry import execute_tool

    return await execute_tool(
        name,
        MCP_SESSION_ID,
        arguments if isinstance(arguments, dict) else {},
        enforce_confirmation=True,
    )


def build_server() -> Server:
    """Build the low-level MCP server wired to the NEXUS tool registry."""
    server: Server = Server(SERVER_NAME)

    @server.list_tools()  # type: ignore[untyped-decorator, no-untyped-call]
    async def _list_tools() -> list[Tool]:
        return [_tool_definition(spec) for spec in exportable_tools()]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        response = await _call_exported_tool(name, arguments)
        payload = response.get("result")
        ok = bool(response.get("ok"))
        body: dict[str, Any] = payload if isinstance(payload, dict) else {"value": payload}
        if not ok:
            body = {
                key: response[key]
                for key in (
                    "error",
                    "error_category",
                    "confirmation_required",
                    "confirmation_id",
                    "unsupported_arguments",
                    "valid_arguments",
                )
                if key in response
            }
            if isinstance(payload, dict):
                body.update(payload)
        return CallToolResult(
            content=[_json_text(body)],
            isError=not ok,
        )

    return server


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    tools = exportable_tools()
    logger.info("NEXUS MCP server ready: %d exportable tools", len(tools))
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
