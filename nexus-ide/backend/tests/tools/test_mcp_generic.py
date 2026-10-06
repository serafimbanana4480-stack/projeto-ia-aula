"""Tests for the generic MCP passthrough tools and the NEXUS MCP server."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from backend.mcp import nexus_server
from backend.mcp import runtime as mcp_runtime
from backend.mcp import store as store_module
from backend.mcp.store import MCPConnector
from backend.tools.mcp_tools import mcp_call_tool, mcp_list_tools
from backend.tools.registry import ToolSpec, get_tool


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Fresh connector store + empty session cache per test."""
    monkeypatch.setattr(store_module, "MCP_STORE_FILE", tmp_path / "mcp_connectors.json")
    monkeypatch.setattr(store_module, "MCP_ACTIVITY_FILE", tmp_path / "mcp_activity.jsonl")
    original = store_module.mcp_store._connectors
    original_activity = store_module.mcp_store._activity_events
    store_module.mcp_store._connectors = {}
    store_module.mcp_store._activity_events = {}
    mcp_runtime._sessions.clear()
    mcp_runtime._session_locks.clear()
    yield store_module.mcp_store
    store_module.mcp_store._connectors = original
    store_module.mcp_store._activity_events = original_activity
    mcp_runtime._sessions.clear()
    mcp_runtime._session_locks.clear()


def _make_connector(store, *, status: str, enabled: bool = True) -> MCPConnector:
    connector = MCPConnector(
        id="mcp_testgeneric",
        name="Generic Test",
        template_id="custom",
        command="python",
        args=["-c", "pass"],
        enabled=enabled,
        last_test_status=status,
    )
    store._connectors[connector.id] = connector
    return connector


# ── (a) Validation gate on the generic tools ────────────────────────────────


async def test_mcp_call_tool_rejects_connector_without_ok_test(isolated_store):
    connector = _make_connector(isolated_store, status="error")
    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_call_tool(connector.id, "ping", {})
    assert "não está validado" in str(excinfo.value)


async def test_mcp_call_tool_rejects_disabled_connector(isolated_store):
    connector = _make_connector(isolated_store, status="ok", enabled=False)
    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_call_tool(connector.id, "ping", {})
    assert "desativado" in str(excinfo.value)


async def test_mcp_call_tool_rejects_unknown_connector(isolated_store):
    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_call_tool("mcp_missing", "ping", {})
    assert "não encontrado" in str(excinfo.value)


async def test_mcp_list_tools_rejects_connector_without_ok_test(isolated_store):
    connector = _make_connector(isolated_store, status="warning")
    with pytest.raises(mcp_runtime.MCPRuntimeError):
        await mcp_list_tools(connector.id)


async def test_mcp_list_tools_all_skips_unvalidated_connectors(isolated_store):
    _make_connector(isolated_store, status="error")
    _make_connector(isolated_store, status="ok", enabled=False)
    listing = await mcp_list_tools()
    assert listing == {"connectors": []}


async def test_mcp_list_tools_returns_validated_connector_tools(isolated_store, monkeypatch):
    connector = _make_connector(isolated_store, status="ok")

    async def fake_list(conn, *, timeout=35.0):
        return [{"name": "ping", "title": "Ping", "description": "", "inputSchema": {}}]

    monkeypatch.setattr(mcp_runtime, "list_connector_tools", fake_list)
    listing = await mcp_list_tools(connector.id)
    assert listing["connectors"][0]["connector_id"] == connector.id
    assert listing["connectors"][0]["tools"][0]["name"] == "ping"


async def test_mcp_list_tools_reports_connector_error_instead_of_crashing(isolated_store, monkeypatch):
    connector = _make_connector(isolated_store, status="ok")

    async def failing_list(conn, *, timeout=35.0):
        raise mcp_runtime.MCPRuntimeError("MCP em baixo")

    monkeypatch.setattr(mcp_runtime, "list_connector_tools", failing_list)
    listing = await mcp_list_tools()
    entry = listing["connectors"][0]
    assert entry["connector_id"] == connector.id
    assert "MCP em baixo" in entry["error"]


# ── (b) Session cache ────────────────────────────────────────────────────────


class _FakeSession:
    def __init__(self, created: list[_FakeSession], read: Any, write: Any) -> None:
        created.append(self)
        self.calls: list[str] = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def initialize(self) -> None:
        self.calls.append("initialize")

    async def list_tools(self) -> Any:
        self.calls.append("list_tools")
        tool = SimpleNamespace(name="ping", title="Ping", description="", inputSchema={})
        return SimpleNamespace(tools=[tool])

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append(f"call_tool:{name}")
        return SimpleNamespace(isError=False, content=[{"ok": True}], structuredContent=None)


def _install_mcp_fakes(monkeypatch: pytest.MonkeyPatch) -> list[_FakeSession]:
    created: list[_FakeSession] = []

    def fake_stdio_client(params: Any, errlog: Any = None) -> Any:
        holder: dict[str, Any] = {}

        class _StreamCtx:
            async def __aenter__(self) -> Any:
                holder["streams"] = (object(), object())
                return holder["streams"]

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        return _StreamCtx()

    class _SessionCtx:
        def __init__(self, read: Any, write: Any) -> None:
            self._read = read
            self._write = write

        async def __aenter__(self) -> _FakeSession:
            session = _FakeSession(created, self._read, self._write)
            self._session = session
            return session

        async def __aexit__(self, *exc: Any) -> bool:
            return False

    def fake_client_session(read: Any, write: Any) -> _SessionCtx:
        return _SessionCtx(read, write)

    monkeypatch.setattr("mcp.client.stdio.stdio_client", fake_stdio_client)
    monkeypatch.setattr("mcp.ClientSession", fake_client_session)
    return created


async def test_session_cache_reuses_live_session(isolated_store, monkeypatch):
    created = _install_mcp_fakes(monkeypatch)
    connector = _make_connector(isolated_store, status="ok")

    first = await mcp_runtime.call_connector_tool(connector.id, "ping", {})
    second = await mcp_runtime.call_connector_tool(connector.id, "ping", {})

    assert len(created) == 1
    assert first["result"]["isError"] is False
    assert second["result"]["isError"] is False
    assert created[0].calls == ["initialize", "list_tools", "call_tool:ping", "list_tools", "call_tool:ping"]


async def test_session_cache_respawns_dead_session(isolated_store, monkeypatch):
    created = _install_mcp_fakes(monkeypatch)
    connector = _make_connector(isolated_store, status="ok")

    await mcp_runtime.call_connector_tool(connector.id, "ping", {})
    entry = mcp_runtime._sessions[connector.id]
    entry.session = None  # simulate a dead process/session

    await mcp_runtime.call_connector_tool(connector.id, "ping", {})

    assert len(created) == 2
    assert created[1].calls == ["initialize", "list_tools", "call_tool:ping"]


def test_session_expired_after_ttl(isolated_store, monkeypatch):
    monkeypatch.setattr(mcp_runtime, "SESSION_IDLE_TTL", 0.0)
    connector = _make_connector(isolated_store, status="ok")
    entry = mcp_runtime._PersistentSession(connector)
    assert entry.expired is True


# ── (c) NEXUS MCP server ─────────────────────────────────────────────────────


def _fake_registry_specs() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            name="read_file", description="Read a file", tags=["file"], risk_level="low",
            requires_confirmation=False, schema={"type": "object", "properties": {}},
            enabled=True, available=True, handler=lambda: None,
        ),
        SimpleNamespace(
            name="run_shell", description="Run a shell command", tags=[], risk_level="low",
            requires_confirmation=True, schema={"type": "object", "properties": {}},
            enabled=True, available=True, handler=lambda: None,
        ),
        SimpleNamespace(
            name="execute_shell", description="Execute a shell command", tags=[], risk_level="low",
            requires_confirmation=True, schema={"type": "object", "properties": {}},
            enabled=True, available=True, handler=lambda: None,
        ),
        SimpleNamespace(
            name="git_push", description="Push to remote", tags=[], risk_level="low",
            requires_confirmation=True, schema={"type": "object", "properties": {}},
            enabled=True, available=True, handler=lambda: None,
        ),
        SimpleNamespace(
            name="write_file_absolute", description="Absolute write", tags=[], risk_level="low",
            requires_confirmation=True, schema={"type": "object", "properties": {}},
            enabled=True, available=True, handler=lambda: None,
        ),
        SimpleNamespace(
            name="broken_tool", description="No handler", tags=[], risk_level="low",
            requires_confirmation=False, schema={"type": "object", "properties": {}},
            enabled=True, available=True, handler=None,
        ),
        SimpleNamespace(
            name="heavy_tool", description="High risk", tags=[], risk_level="high",
            requires_confirmation=False, schema={"type": "object", "properties": {}},
            enabled=True, available=True, handler=lambda: None,
        ),
    ]


def _patch_registry(monkeypatch: pytest.MonkeyPatch, executor: Any) -> None:
    monkeypatch.setattr("backend.tools.registry.list_tools", lambda enabled_only=True: _fake_registry_specs())
    monkeypatch.setattr("backend.tools.registry.execute_tool", executor)


async def test_nexus_server_lists_and_calls_registry_tools(monkeypatch):
    calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def executor(name: str, session_id: Any, args: dict, **kwargs: Any) -> dict[str, Any]:
        calls.append((name, args, kwargs))
        return {"tool": name, "ok": True, "result": {"called": name, "args": args}}

    _patch_registry(monkeypatch, executor)
    server = nexus_server.build_server()
    async with create_connected_server_and_client_session(server) as session:
        tools = await session.list_tools()
        names = sorted(tool.name for tool in tools.tools)
        assert names == ["read_file"]
        result = await session.call_tool("read_file", {"path": "backend"})
        assert result.isError is False
        assert '"called": "read_file"' in result.content[0].text
        assert calls == [
            ("read_file", {"path": "backend"}, {"enforce_confirmation": True})
        ]


async def test_nexus_server_returns_clear_error_for_unknown_tool(monkeypatch):
    async def executor(name: str, session_id: Any, args: dict, **kwargs: Any) -> dict[str, Any]:
        return {"tool": name, "ok": False, "error": f"Tool '{name}' not found", "error_category": "unknown_tool"}

    _patch_registry(monkeypatch, executor)
    server = nexus_server.build_server()
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("does_not_exist", {})
        assert result.isError is True
        assert "not found" in result.content[0].text


async def test_nexus_server_rejects_unadvertised_tool_calls(monkeypatch):
    calls: list[str] = []

    async def executor(name: str, session_id: Any, args: dict, **kwargs: Any) -> dict[str, Any]:
        calls.append(name)
        return {"tool": name, "ok": True, "result": {"called": name}}

    monkeypatch.delenv("NEXUS_MCP_ALLOW_SHELL", raising=False)
    _patch_registry(monkeypatch, executor)
    server = nexus_server.build_server()
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("git_push", {"remote": "origin"})
        assert result.isError is True
        assert "not exposed" in result.content[0].text

    assert calls == []


def test_nexus_server_blocks_shell_by_default(monkeypatch):
    monkeypatch.delenv("NEXUS_MCP_ALLOW_SHELL", raising=False)
    _patch_registry(monkeypatch, None)
    exported = {spec.name for spec in nexus_server.exportable_tools()}
    assert "read_file" in exported
    assert "run_shell" not in exported
    assert "execute_shell" not in exported
    assert "git_push" not in exported
    assert "write_file_absolute" not in exported
    assert "heavy_tool" not in exported
    assert "broken_tool" not in exported


def test_nexus_server_exports_shell_with_env_flag(monkeypatch):
    monkeypatch.setenv("NEXUS_MCP_ALLOW_SHELL", "1")
    _patch_registry(monkeypatch, None)
    exported = {spec.name for spec in nexus_server.exportable_tools()}
    assert {"run_shell", "execute_shell"} <= exported
    assert "git_push" not in exported


def test_nexus_server_tool_definition_uses_registry_schema(monkeypatch):
    _patch_registry(monkeypatch, None)
    specs = nexus_server.exportable_tools()
    definition = nexus_server._tool_definition(specs[0])
    assert definition.name == "read_file"
    assert definition.inputSchema == {"type": "object", "properties": {}}


def test_generic_mcp_tools_are_registered():
    for name in ("mcp_list_tools", "mcp_call_tool"):
        spec: ToolSpec | None = get_tool(name)
        assert spec is not None, name
        assert spec.handler is not None
        assert spec.schema.get("type") == "object"
