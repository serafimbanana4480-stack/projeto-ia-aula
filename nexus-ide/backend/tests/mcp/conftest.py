"""Shared fixtures for the MCP subsystem regression tests.

The MCP runtime talks to a real MCP server over stdio. These fixtures
install a fake ``mcp`` client so the tests can drive the runtime (session
cache, handshake, tool call) without spawning a server process.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from backend.mcp import runtime as mcp_runtime
from backend.mcp import store as store_module


class FakeTool:
    """Minimal stand-in for ``mcp.types.Tool``."""

    def __init__(
        self,
        name: str,
        *,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        annotations: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.title = name
        self.description = description
        self.inputSchema = (
            input_schema if input_schema is not None else {"type": "object", "properties": {}}
        )
        self.annotations = annotations or {}


class FakeSession:
    """Minimal stand-in for ``mcp.ClientSession``."""

    def __init__(
        self,
        tools: list[FakeTool] | None = None,
        *,
        result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        self._tools = list(tools or [])
        self._result = result
        self._error = error
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> Any:
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, arguments))
        if self._error is not None:
            raise self._error
        if self._result is None:
            return SimpleNamespace(isError=False, content=[], structuredContent=None)
        return self._result


def install_fake_mcp(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: Callable[[], FakeSession],
) -> None:
    """Route the runtime's stdio transport to a fake MCP session."""
    @contextlib.asynccontextmanager
    async def fake_stdio_client(params: Any, errlog: Any = None) -> Any:
        yield (object(), object())

    class _SessionContext:
        def __init__(self, read: Any, write: Any) -> None:
            self._session = session_factory()

        async def __aenter__(self) -> FakeSession:
            return self._session

        async def __aexit__(self, *exc: Any) -> bool:
            return False

    monkeypatch.setattr("mcp.client.stdio.stdio_client", fake_stdio_client)
    monkeypatch.setattr("mcp.ClientSession", _SessionContext)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """A throwaway connector store + an empty runtime session cache."""
    monkeypatch.setattr(store_module, "MCP_STORE_FILE", tmp_path / "mcp_connectors.json")
    monkeypatch.setattr(store_module, "MCP_ACTIVITY_FILE", tmp_path / "mcp_activity.jsonl")
    original_connectors = store_module.mcp_store._connectors
    original_activity = store_module.mcp_store._activity_events
    store_module.mcp_store._connectors = {}
    store_module.mcp_store._activity_events = {}
    mcp_runtime._sessions.clear()
    mcp_runtime._session_locks.clear()
    yield store_module.mcp_store
    store_module.mcp_store._connectors = original_connectors
    store_module.mcp_store._activity_events = original_activity
    mcp_runtime._sessions.clear()
    mcp_runtime._session_locks.clear()
