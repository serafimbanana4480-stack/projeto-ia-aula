"""Bounded MCP client used by the Nexus agent tool registry.

Sessions are cached per connector: a stdio server process is spawned once and
reused for every subsequent call until it goes idle for
``NEXUS_MCP_SESSION_TTL`` seconds (default 120) or dies. On Windows the MCP
package's ``stdio_client`` feeds ``errlog`` to the subprocess as ``stderr``,
which requires an object with a real OS file descriptor — a plain
``io.StringIO`` raises ``io.UnsupportedOperation: fileno`` during process
creation, so each session owns a ``tempfile`` (real fd) instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from backend.mcp.store import MCPConnector, mcp_store, redact_connector_secrets
from backend.mcp.validation import (
    is_valid_input_schema,
    is_valid_tool_name,
    root_boundary_violations,
    validate_arguments,
)

logger = logging.getLogger(__name__)

SESSION_IDLE_TTL = float(os.environ.get("NEXUS_MCP_SESSION_TTL", "120"))
_MAX_TIMEOUT = 60.0

_SESSION_TIMEOUT_MESSAGES = (
    "connection closed",
    "closedresourceerror",
    "brokenresourceerror",
    "brokenpipe",
    "anyio.closedresourceerror",
)


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


def _redact_connector_secrets(connector: MCPConnector, text: str) -> str:
    """Remove configured credentials from process and transport error details."""
    return redact_connector_secrets(connector, text)


def _public_remote_url(url: str) -> str:
    """Validate a remote MCP URL against the public-address policy.

    The rest of NEXUS refuses to talk to loopback, private, link-local, or
    otherwise non-public addresses (``backend/tools/safe_http.py``). A remote
    MCP connector is an outbound request too, so it follows the same policy:
    otherwise a connector could be pointed at the NEXUS backend itself or at
    the cloud metadata service.
    """
    from backend.tools.safe_http import normalize_public_http_url

    try:
        return normalize_public_http_url(url)
    except ValueError as exc:
        raise MCPRuntimeError(
            f"URL MCP remoto rejeitada pela política de endereços públicos: {exc}"
        ) from exc


def _validated_tools(result: Any) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Split a ``tools/list`` answer into usable tools and rejected ones.

    A tool whose name is not an identifier, or whose ``inputSchema`` is not a
    JSON-Schema object, cannot be called safely: NEXUS would have to forward
    model-supplied arguments to a contract it cannot check. Those tools are
    refused (and reported) instead of being listed, stored, and called.
    """
    tools: dict[str, dict[str, Any]] = {}
    rejected: dict[str, str] = {}
    for tool in getattr(result, "tools", ()):
        payload = _tool_payload(tool)
        name = payload["name"]
        if not is_valid_tool_name(name):
            rejected[name] = "nome de tool inválido"
            continue
        if not is_valid_input_schema(payload["inputSchema"]):
            rejected[name] = "inputSchema não é um JSON Schema válido"
            continue
        tools[name] = payload
    return tools, rejected


def _tool_payload(tool: Any) -> dict[str, Any]:
    annotations = getattr(tool, "annotations", None)
    if hasattr(annotations, "model_dump"):
        try:
            annotations = annotations.model_dump(mode="json", exclude_none=True)
        except Exception:  # pragma: no cover - future SDK representation
            annotations = {}
    if not isinstance(annotations, dict):
        annotations = {}
    return {
        "name": str(getattr(tool, "name", "")),
        "title": str(getattr(tool, "title", "") or ""),
        "description": str(getattr(tool, "description", "") or ""),
        "inputSchema": getattr(tool, "inputSchema", {}) or {},
        "annotations": annotations,
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
        raise MCPRuntimeError("Parâmetros stdio pedidos para um MCP com outro transporte")
    if not connector.command:
        raise MCPRuntimeError("Connector MCP sem comando")
    # MCP children must not inherit every NEXUS credential. Only standard
    # process-launch variables and explicitly configured connector values cross
    # the boundary; MCP Builder can opt in named NEXUS_MCP_* variables.
    safe_names = (
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "HOME",
    )
    child_env = {name: os.environ[name] for name in safe_names if os.environ.get(name)}
    child_env.update({k: v for k, v in connector.env.items() if v})
    for name in connector.pass_through_env:
        value = os.environ.get(name)
        if value:
            child_env[name] = value
    return StdioServerParameters(
        command=connector.command,
        args=list(connector.args),
        env=child_env,
        cwd=connector.source_root or None,
    )


def _fingerprint(connector: MCPConnector) -> tuple[Any, ...]:
    """Config identity for a cached session: changing it must re-spawn."""
    return (
        connector.transport,
        connector.command,
        tuple(connector.args),
        tuple(sorted((k, v) for k, v in connector.env.items() if v)),
        connector.url,
        tuple((name, os.environ.get(name, "")) for name in connector.pass_through_env),
        connector.source_root,
    )


def _is_transport_failure(exc: BaseException) -> bool:
    lowered = _exception_text(exc).lower()
    return any(token in lowered for token in _SESSION_TIMEOUT_MESSAGES)


class _PersistentSession:
    """One long-lived stdio MCP session, kept warm across tool calls."""

    def __init__(self, connector: MCPConnector) -> None:
        self.connector = connector
        self.fingerprint = _fingerprint(connector)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.session: Any | None = None
        self.last_used = time.monotonic()
        self._failure: MCPRuntimeError | None = None
        self._ready = asyncio.Event()
        self._closed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._errlog: Any = None

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self, *, timeout: float) -> None:
        self.loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._run(), name=f"mcp-session-{self.connector.id}")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=max(1.0, min(float(timeout), _MAX_TIMEOUT)))
        except TimeoutError as exc:
            raise MCPRuntimeError(f"MCP excedeu o timeout de {timeout:.0f}s no handshake") from exc
        if self._failure is not None:
            raise self._failure
        if self.session is None:
            raise MCPRuntimeError(f"Handshake MCP de {self.connector.name} falhou sem detalhe")

    async def _run(self) -> None:
        try:
            from mcp import ClientSession
        except ImportError:  # pragma: no cover
            self._failure = MCPRuntimeError("Dependência MCP Python não instalada no runtime do Nexus")
            self._ready.set()
            return
        try:
            async def run_session(read_stream: Any, write_stream: Any) -> None:
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    self.session = session
                    self._ready.set()
                    await self._closed.wait()

            if self.connector.transport == "http":
                from mcp.client.streamable_http import streamable_http_client

                from backend.tools.safe_http import PublicAddressHTTPTransport

                # The remote URL is re-validated on every handshake: a
                # connector persisted before this policy existed must not be
                # able to reach a local or metadata address.
                url = _public_remote_url(self.connector.url)
                headers: dict[str, str] = {}
                token = self.connector.env.get("AUTH_TOKEN", "")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                # PublicAddressHTTPTransport pins every connection (including
                # redirects) to a public address, so the connector cannot be
                # used as an SSRF pivot into the NEXUS host or the cloud
                # metadata service.
                client = httpx.AsyncClient(
                    transport=PublicAddressHTTPTransport(),
                    headers=headers,
                    timeout=httpx.Timeout(10.0, read=30.0),
                    follow_redirects=True,
                    trust_env=False,
                )
                async with client, streamable_http_client(
                    url,
                    http_client=client,
                    terminate_on_close=True,
                ) as (read_stream, write_stream, _session_id):
                    await run_session(read_stream, write_stream)
            else:
                from mcp.client.stdio import stdio_client

                self._errlog = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")  # noqa: SIM115 — lives as long as the session
                params = _server_parameters(self.connector)
                async with stdio_client(params, errlog=self._errlog) as (read_stream, write_stream):
                    await run_session(read_stream, write_stream)
        except BaseException as exc:  # noqa: BLE001 — must always unblock waiters
            if not self._closed.is_set() and self._failure is None:
                self._failure = MCPRuntimeError(
                    f"Falha no MCP {self.connector.name}: {self._failure_detail(exc)[:800]}"
                )
        finally:
            self._ready.set()
            self.session = None
            if self._errlog is not None:
                with contextlib.suppress(Exception):  # pragma: no cover
                    self._errlog.close()
                self._errlog = None

    def _failure_detail(self, exc: BaseException) -> str:
        """Build the redacted detail of a failed handshake.

        This runs inside an ``except`` block: it must never raise, because an
        exception here would leave ``self._failure`` unset and the caller
        would only see "Handshake MCP de X falhou sem detalhe" — exactly the
        case (missing module, ``npx: not found``, ``spawn ENOENT``) the user
        needs the detail for.
        """
        try:
            detail = _exception_text(exc)
        except Exception:  # pragma: no cover - defensive
            detail = type(exc).__name__
        try:
            stderr_tail = self._stderr_tail()
        except Exception:  # pragma: no cover - defensive
            stderr_tail = ""
        if stderr_tail:
            detail = f"{detail}; {stderr_tail}"
        return _redact_connector_secrets(self.connector, detail)

    def _stderr_tail(self, lines: int = 3) -> str:
        """Return the last *lines* lines the MCP child wrote to stderr."""
        if self._errlog is None:
            return ""
        try:
            self._errlog.flush()
            self._errlog.seek(0)
            content = self._errlog.read().strip().splitlines()
            # A slice, not an index: with one or two lines of stderr an index
            # raises IndexError and destroys the real error message.
            return "\n".join(content[-lines:]) if content else ""
        except (OSError, ValueError, AttributeError):  # pragma: no cover
            return ""

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.last_used) > SESSION_IDLE_TTL

    def is_alive(self) -> bool:
        task = self._task
        return (
            self.session is not None
            and task is not None
            and not task.done()
            and not self._closed.is_set()
            and (self.loop is None or not self.loop.is_closed())
        )

    async def close(self) -> None:
        self._closed.set()
        task = self._task
        if task is None or task.done():
            self._task = None
            return
        same_loop = self.loop is None or self.loop is asyncio.get_running_loop()
        if not same_loop:  # pragma: no cover — stale test loop; nothing to await
            self._task = None
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except Exception:
            task.cancel()
            with contextlib.suppress(BaseException):  # pragma: no cover
                await task
        self._task = None


_sessions: dict[str, _PersistentSession] = {}
_session_locks: dict[str, asyncio.Lock] = {}


async def _discard_session(entry: _PersistentSession) -> None:
    _sessions.pop(entry.connector.id, None)
    with contextlib.suppress(Exception):
        await entry.close()


async def _get_session(connector: MCPConnector, *, timeout: float) -> _PersistentSession:
    lock = _session_locks.setdefault(connector.id, asyncio.Lock())
    async with lock:
        cached = _sessions.get(connector.id)
        if cached is not None and (cached.fingerprint != _fingerprint(connector) or not cached.is_alive()):
            await _discard_session(cached)
            cached = None
        if cached is None:
            entry = _PersistentSession(connector)
            try:
                await entry.start(timeout=timeout)
            except BaseException:
                await entry.close()
                raise
            _sessions[connector.id] = entry
            return entry
        cached.last_used = time.monotonic()
        return cached


async def _sweep_idle_sessions() -> None:
    """Close sessions that have been idle beyond the TTL (called lazily)."""
    for _connector_id, entry in list(_sessions.items()):
        if entry.expired:
            await _discard_session(entry)


async def close_session(connector_id: str) -> None:
    """Terminate the cached MCP session for one connector, if any."""
    entry = _sessions.pop(connector_id, None)
    if entry is not None:
        await entry.close()
    _session_locks.pop(connector_id, None)


async def close_all_sessions() -> None:
    """Terminate every cached MCP session (used at shutdown and in tests)."""
    for entry in list(_sessions.values()):
        await _discard_session(entry)
    _session_locks.clear()


async def _with_session(connector: MCPConnector, operation: Callable[[Any], Awaitable[Any]], *, timeout: float) -> Any:
    """Run ``operation`` against a live (cached) session for *connector*.

    A transport-level failure (process died, pipe broken) invalidates the
    cached session and retries once on a fresh one before surfacing the error.
    """
    await _sweep_idle_sessions()
    for attempt in (1, 2):
        entry = await _get_session(connector, timeout=timeout)
        try:
            return await asyncio.wait_for(
                operation(entry.session),
                timeout=max(1.0, min(float(timeout), _MAX_TIMEOUT)),
            )
        except TimeoutError as exc:
            await _discard_session(entry)
            raise MCPRuntimeError(f"MCP excedeu o timeout de {timeout:.0f}s") from exc
        except MCPRuntimeError:
            raise
        except Exception as exc:  # transport failures may be nested in ExceptionGroups
            if attempt == 1 and (not entry.is_alive() or _is_transport_failure(exc)):
                await _discard_session(entry)
                continue
            # The transport can echo the connector's credentials (an
            # "Unauthorized: <token>" body, a command line in the error),
            # so the detail is redacted before it reaches the model.
            detail = _redact_connector_secrets(connector, _exception_text(exc))
            raise MCPRuntimeError(f"Falha no MCP {connector.name}: {detail[:800]}") from exc
    raise MCPRuntimeError(f"Falha no MCP {connector.name}: sessão indisponível")


async def list_connector_tools(connector: MCPConnector, *, timeout: float = 35.0) -> list[dict[str, Any]]:
    """Return the usable tools advertised by a connector.

    Tools with an illegal name or a malformed ``inputSchema`` are refused:
    NEXUS could not validate the arguments it forwards for them.
    """
    result = await _with_session(connector, lambda session: session.list_tools(), timeout=timeout)
    tools, rejected = _validated_tools(result)
    if rejected:
        logger.warning(
            "MCP connector %s advertised %d invalid tool(s): %s",
            connector.name,
            len(rejected),
            "; ".join(f"{name}: {reason}" for name, reason in list(rejected.items())[:5]),
        )
    return list(tools.values())


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
    activity_id = mcp_store.start_activity(
        connector_id=connector_id,
        tool=tool_name,
        kind="tool_call",
        source="agent",
        phase="protocol_call",
        detail="A chamar a tool MCP",
        argument_names=list(args),
    )

    def _result_shape(payload: dict[str, Any]) -> str:
        content = payload.get("content") or []
        content_kinds = sorted(
            {str(item.get("type") or "content") for item in content if isinstance(item, dict)}
        )
        structured = payload.get("structuredContent")
        structured_keys = sorted(str(key)[:40] for key in structured)[:8] if isinstance(structured, dict) else []
        parts = [f"{len(content)} content item(s)"]
        if content_kinds:
            parts.append("types: " + ", ".join(content_kinds))
        if structured_keys:
            parts.append("structured keys: " + ", ".join(structured_keys))
        return "; ".join(parts)[:200]

    def _error_detail(payload: dict[str, Any]) -> str:
        """Extract the server's own error text from a tool result.

        Without this, every failing MCP tool looks the same ("isError=true")
        and the reason never reaches the model or the activity log.
        """
        parts: list[str] = []
        for item in payload.get("content") or []:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        if not parts:
            structured = payload.get("structuredContent")
            if isinstance(structured, dict) and structured:
                parts.append(str(structured))
        return "; ".join(parts)[:600]

    async def operation(session: Any) -> Any:
        tools = await session.list_tools()
        available, rejected = _validated_tools(tools)
        if tool_name in rejected:
            raise MCPRuntimeError(
                f"Tool MCP '{tool_name}' foi rejeitada pelo NEXUS: {rejected[tool_name]}"
            )
        if tool_name not in available:
            raise MCPRuntimeError(f"Tool MCP '{tool_name}' não está disponível em {connector.name}")
        # The model-supplied arguments are validated against the schema the
        # server is advertising right now, exactly like NEXUS' own tools.
        violations = validate_arguments(available[tool_name]["inputSchema"], args)
        if violations:
            raise MCPRuntimeError(
                f"Argumentos inválidos para a tool MCP '{tool_name}': {'; '.join(violations[:5])}"
            )
        # A connector built for one directory must not be able to reach
        # outside it, even if the server itself would allow it.
        root_violations = root_boundary_violations(connector.source_root, tool_name, args)
        if root_violations:
            raise MCPRuntimeError(
                f"Argumentos inválidos para a tool MCP '{tool_name}': {'; '.join(root_violations[:5])}"
            )
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
        error_detail = "" if ok else _redact_connector_secrets(connector, _error_detail(payload))
        if ok:
            call_detail = "Resultado MCP recebido"
        elif error_detail:
            call_detail = f"O servidor devolveu isError=true: {error_detail}"
        else:
            call_detail = "O servidor devolveu isError=true"
        mcp_store.record_tool_call(
            connector_id,
            tool_name,
            elapsed_ms,
            success=ok,
            activity_id=activity_id,
            detail=call_detail,
            result_shape=_result_shape(payload),
        )
        recorded = True
        if not ok:
            if error_detail:
                raise MCPRuntimeError(
                    f"Tool MCP '{tool_name}' devolveu isError=true: {error_detail}"
                )
            raise MCPRuntimeError(f"Tool MCP '{tool_name}' devolveu isError=true")
        return {"connector_id": connector_id, "connector": connector.name, "tool": tool_name, "latency_ms": round(elapsed_ms, 1), "result": payload}
    except BaseException as exc:  # noqa: BLE001 - persist cancellation before propagating
        elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000
        if not recorded:
            if isinstance(exc, asyncio.CancelledError):
                failure_detail = "Chamada cancelada pelo utilizador/runtime"
            elif isinstance(exc, MCPRuntimeError):
                failure_detail = _redact_connector_secrets(connector, str(exc))[:300]
            else:
                failure_detail = f"Falha na chamada MCP ({type(exc).__name__})"
            mcp_store.record_tool_call(
                connector_id,
                tool_name,
                elapsed_ms,
                success=False,
                activity_id=activity_id,
                detail=failure_detail,
            )
        raise
