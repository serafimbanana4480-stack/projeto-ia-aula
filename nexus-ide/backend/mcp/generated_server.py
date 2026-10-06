"""Safe, manifest-driven MCP server used by MCP Builder artifacts.

Generated MCPs are declarative HTTP adapters. The model never supplies
executable Python: this fixed runtime maps a validated manifest to a bounded
set of HTTP operations on one explicitly supplied base URL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

logger = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES = 1_000_000
_MAX_TEXT_CHARS = 12_000
_PATH_PARAMETER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _tool_annotations(method: str) -> ToolAnnotations:
    read_only = method in {"GET", "HEAD"}
    return ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=not read_only,
        openWorldHint=True,
    )


def _request_url(base_url: str, operation: dict[str, Any], arguments: dict[str, Any]) -> str:
    path = str(operation["path"])
    for parameter in operation.get("pathParams", []):
        if parameter not in arguments:
            raise ValueError(f"Falta o parâmetro de caminho '{parameter}'")
        path = path.replace("{" + parameter + "}", quote(str(arguments[parameter]), safe=""))
    if _PATH_PARAMETER.search(path):
        raise ValueError("O caminho contém um parâmetro sem valor")
    return base_url.rstrip("/") + path


async def execute_operation(
    manifest: dict[str, Any],
    operation: dict[str, Any],
    arguments: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
    env: dict[str, str] | None = None,
) -> Any:
    """Execute one validated operation; ``client`` enables isolated contract checks."""
    if not isinstance(arguments, dict):
        raise ValueError("Os argumentos da tool têm de ser um objeto")

    headers: dict[str, str] = {"Accept": "application/json"}
    auth = manifest.get("auth") or {}
    env_name = str(auth.get("env_var") or "")
    if env_name:
        token = (env or os.environ).get(env_name, "")
        if not token:
            raise RuntimeError(f"Falta configurar a variável de ambiente {env_name}")
        headers[str(auth.get("header") or "Authorization")] = str(auth.get("prefix") or "") + token

    body_parameter = operation.get("bodyParam")
    body = arguments.get(body_parameter) if body_parameter else None
    query = {
        name: arguments[name]
        for name in operation.get("queryParams", [])
        if name in arguments and arguments[name] is not None
    }
    method = str(operation["method"]).upper()
    url = _request_url(str(manifest["base_url"]), operation, arguments)

    async def send(active_client: httpx.AsyncClient) -> Any:
        request = active_client.build_request(
            method,
            url,
            params=query,
            json=body if method not in {"GET", "HEAD"} else None,
            headers=headers,
        )
        response = await active_client.send(request, stream=True)
        try:
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > _MAX_RESPONSE_BYTES:
                raise RuntimeError("A resposta excede o limite de 1 MB")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    raise RuntimeError("A resposta excede o limite de 1 MB")
                chunks.append(chunk)
            payload = b"".join(chunks)
            if response.is_error:
                raise RuntimeError(f"A API respondeu HTTP {response.status_code}")
            if not payload:
                return {"status_code": response.status_code, "body": None}
            try:
                value: Any = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                value = payload.decode("utf-8", errors="replace")[:_MAX_TEXT_CHARS]
            if isinstance(value, str):
                value = value[:_MAX_TEXT_CHARS]
            return {"status_code": response.status_code, "body": value}
        finally:
            await response.aclose()

    if client is not None:
        return await send(client)
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False, trust_env=False) as active:
        return await send(active)


def build_server(manifest: dict[str, Any]) -> Server:
    """Build an MCP protocol server from a previously validated manifest."""
    server = Server(str(manifest.get("name") or "nexus-built-mcp"))
    operations = {str(item["name"]): item for item in manifest.get("tools", [])}

    @server.list_tools()  # type: ignore[untyped-decorator, no-untyped-call]
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=name,
                description=str(operation.get("description") or name),
                inputSchema=operation["inputSchema"],
                annotations=_tool_annotations(str(operation["method"]).upper()),
            )
            for name, operation in operations.items()
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        operation = operations.get(name)
        if operation is None:
            return CallToolResult(
                content=[TextContent(type="text", text="Tool MCP desconhecida")],
                isError=True,
            )
        try:
            payload = await execute_operation(manifest, operation, arguments)
            text = json.dumps(payload, ensure_ascii=False, default=str)
            return CallToolResult(content=[TextContent(type="text", text=text[:_MAX_TEXT_CHARS])])
        except Exception as exc:  # noqa: BLE001 - returned as an MCP tool error
            logger.warning("Generated MCP operation failed (%s): %s", name, type(exc).__name__)
            detail = (
                str(exc)
                if isinstance(exc, (RuntimeError, ValueError))
                else f"Falha de transporte HTTP ({type(exc).__name__})"
            )
            return CallToolResult(
                content=[TextContent(type="text", text=f"Falha na operação MCP: {detail[:300]}")],
                isError=True,
            )

    return server


async def _serve(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    server = build_server(manifest)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_manifest(manifest_path: Path) -> None:
    asyncio.run(_serve(manifest_path))


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXUS manifest-driven MCP server")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    run_manifest(args.manifest)


if __name__ == "__main__":
    main()
