"""MCP runtime contracts: real errors, redacted secrets, validated arguments.

These tests cover the failure paths of ``backend/mcp/runtime.py``:

* the stderr tail of a dead MCP child must reach the caller (a missing
  module, ``npx: not found`` or ``spawn ENOENT`` used to be replaced by
  "Handshake MCP de X falhou sem detalhe");
* no connector credential may appear in an error message;
* the error content returned by the server must reach the model;
* model-supplied arguments must be validated against the live schema and
  against the connector's declared root;
* a malformed schema or an illegal tool name must be refused.
"""

from __future__ import annotations

import sys
import tempfile
from types import SimpleNamespace

import pytest

from backend.mcp import runtime as mcp_runtime
from backend.mcp.store import MCPConnector

from .conftest import FakeSession, FakeTool, install_fake_mcp

_SECRET = "ghp_supersecrettoken"


def _connector(**overrides) -> MCPConnector:
    payload = {
        "id": "mcp_runtime_test",
        "name": "Runtime Test",
        "template_id": "github",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": _SECRET},
    }
    payload.update(overrides)
    return MCPConnector(**payload)


# ── stderr tail ─────────────────────────────────────────────────────────────


def test_stderr_tail_with_one_line_does_not_raise():
    """One line of stderr must not raise IndexError (it used to)."""
    session = mcp_runtime._PersistentSession(_connector())
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
        session._errlog = errlog
        errlog.write("ModuleNotFoundError: No module named 'mcp.server'\n")
        tail = session._stderr_tail()
        assert "No module named 'mcp.server'" in tail


def test_stderr_tail_with_two_lines_does_not_raise():
    """Two lines of stderr must not raise IndexError either."""
    session = mcp_runtime._PersistentSession(_connector())
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
        session._errlog = errlog
        errlog.write("npx: not found\n")
        errlog.write("spawn ENOENT\n")
        tail = session._stderr_tail()
        assert "npx: not found" in tail
        assert "spawn ENOENT" in tail


def test_stderr_tail_reaches_the_caller_as_a_failure_detail():
    """The stderr tail must be part of the failure detail, not swallowed."""
    session = mcp_runtime._PersistentSession(_connector())
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
        session._errlog = errlog
        errlog.write("ModuleNotFoundError: No module named 'mcp.server'\n")
        detail = session._failure_detail(RuntimeError("handshake failed"))
        assert "handshake failed" in detail
        assert "No module named 'mcp.server'" in detail


# ── secret redaction ────────────────────────────────────────────────────────


async def test_connector_secret_is_redacted_from_operation_errors(isolated_store, monkeypatch):
    """A connector credential must never appear in an operation error."""
    connector = _connector()
    isolated_store._connectors[connector.id] = connector
    session = FakeSession(
        tools=[FakeTool("read_issue")],
        error=RuntimeError(f"401 Unauthorized: token {_SECRET} rejected"),
    )
    install_fake_mcp(monkeypatch, lambda: session)

    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_runtime.call_connector_tool(connector.id, "read_issue", {})

    message = str(excinfo.value)
    assert _SECRET not in message
    assert "[REDACTED]" in message


# ── server error content ────────────────────────────────────────────────────


async def test_mcp_error_content_reaches_the_caller(isolated_store, monkeypatch):
    """``isError=true`` must carry the server's own reason to the model."""
    connector = _connector()
    isolated_store._connectors[connector.id] = connector
    failure = SimpleNamespace(
        isError=True,
        content=[{"type": "text", "text": "Permission denied: path is outside the allowed root"}],
        structuredContent=None,
    )
    session = FakeSession(tools=[FakeTool("read_issue")], result=failure)
    install_fake_mcp(monkeypatch, lambda: session)

    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_runtime.call_connector_tool(connector.id, "read_issue", {})

    assert "Permission denied: path is outside the allowed root" in str(excinfo.value)
    activity = isolated_store.list_activity(limit=20)
    assert any("Permission denied" in str(item.get("detail") or "") for item in activity)


# ── argument validation ─────────────────────────────────────────────────────


async def test_mcp_tool_arguments_are_validated_against_the_schema(isolated_store, monkeypatch):
    """Arguments are checked against the schema the server advertises now."""
    connector = _connector()
    isolated_store._connectors[connector.id] = connector
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    }
    session = FakeSession(tools=[FakeTool("read_file", input_schema=schema)])
    install_fake_mcp(monkeypatch, lambda: session)

    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_runtime.call_connector_tool(connector.id, "read_file", {"path": 42})

    assert "Argumentos inválidos" in str(excinfo.value)
    assert session.calls == [], "the call must not reach the server"


async def test_mcp_tool_arguments_respect_the_connector_root(isolated_store, monkeypatch, tmp_path):
    """A connector scoped to one directory cannot be used to leave it."""
    root = tmp_path / "project"
    root.mkdir()
    connector = _connector(template_id="filesystem", source_root=str(root))
    isolated_store._connectors[connector.id] = connector
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    session = FakeSession(tools=[FakeTool("read_file", input_schema=schema)])
    install_fake_mcp(monkeypatch, lambda: session)

    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_runtime.call_connector_tool(
            connector.id, "read_file", {"path": str(tmp_path / "outside.txt")}
        )
    assert "raiz" in str(excinfo.value)
    assert session.calls == [], "the call must not reach the server"

    result = await mcp_runtime.call_connector_tool(
        connector.id, "read_file", {"path": "src/app.py"}
    )
    assert result["result"]["isError"] is False
    assert session.calls == [("read_file", {"path": "src/app.py"})]


# ── malformed contracts ─────────────────────────────────────────────────────


async def test_malformed_input_schema_is_rejected(isolated_store, monkeypatch):
    """A tool without a JSON-Schema ``type`` is neither listed nor called."""
    connector = _connector(command=sys.executable, args=["-c", "pass"])
    isolated_store._connectors[connector.id] = connector
    malformed = FakeTool("weird_schema", input_schema={"properties": {"a": {"type": "string"}}})
    valid = FakeTool("good_tool", input_schema={"type": "object", "properties": {}})
    session = FakeSession(tools=[malformed, valid])
    install_fake_mcp(monkeypatch, lambda: session)

    tools = await mcp_runtime.list_connector_tools(connector)
    assert [tool["name"] for tool in tools] == ["good_tool"]

    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_runtime.call_connector_tool(connector.id, "weird_schema", {})
    assert "rejeitada" in str(excinfo.value)
    assert session.calls == []

    # The invalid contract is not persisted either.
    result = await isolated_store.test_connector(connector.id)
    assert result["status"] == "ok"
    assert [tool["name"] for tool in connector.tools] == ["good_tool"]


async def test_illegal_tool_name_is_rejected(isolated_store, monkeypatch):
    """A tool name that is not an identifier is neither listed nor called."""
    connector = _connector()
    isolated_store._connectors[connector.id] = connector
    illegal = FakeTool("weird name with spaces/and-slash")
    session = FakeSession(tools=[illegal])
    install_fake_mcp(monkeypatch, lambda: session)

    tools = await mcp_runtime.list_connector_tools(connector)
    assert tools == []

    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_runtime.call_connector_tool(connector.id, "weird name with spaces/and-slash", {})
    assert "rejeitada" in str(excinfo.value)
    assert session.calls == []
