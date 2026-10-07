"""Focused checks for declarative MCP generation and activation gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.agents.nexus_primary import NexusPrimaryAgent
from backend.mcp import builder, runtime
from backend.mcp import store as store_module
from backend.mcp.builder import MCPBuilderError, build_from_description
from backend.mcp.store import MCPConnector, MCPConnectorStore
from backend.tools import mcp_tools as mcp_tools_module
from backend.tools.mcp_tools import mcp_call_readonly_tool
from backend.tools.registry import get_tool, tool_requires_confirmation


class _FakeLLM:
    def __init__(self, auth: dict[str, str] | None = None):
        self.auth = auth

    async def chat_complete(self, *, model: str, messages: list[dict[str, str]], options: dict[str, Any]) -> str:
        assert model
        assert messages[0]["role"] == "system"
        assert options["temperature"] == 0.1
        return json.dumps(
            {
                "name": "Example API",
                "description": "Read items from the Example API",
                "auth": self.auth,
                "tools": [
                    {
                        "name": "get_item",
                        "description": "Read one item by id",
                        "method": "GET",
                        "path": "/items/{item_id}",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"item_id": {"type": "string"}},
                            "required": ["item_id"],
                            "additionalProperties": False,
                        },
                        "pathParams": ["item_id"],
                        "queryParams": [],
                        "bodyParam": None,
                    }
                ],
            }
        )


@pytest.fixture
def isolated_builder(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "MCP_BUILD_DIR", tmp_path / "built")
    monkeypatch.setattr(store_module, "MCP_STORE_FILE", tmp_path / "mcp_connectors.json")
    monkeypatch.setattr(store_module, "MCP_ACTIVITY_FILE", tmp_path / "mcp_activity.jsonl")
    original = store_module.mcp_store._connectors
    original_activity = store_module.mcp_store._activity_events
    store_module.mcp_store._connectors = {}
    store_module.mcp_store._activity_events = {}
    runtime._sessions.clear()
    runtime._session_locks.clear()
    yield store_module.mcp_store
    store_module.mcp_store._connectors = original
    store_module.mcp_store._activity_events = original_activity
    runtime._sessions.clear()
    runtime._session_locks.clear()


async def test_builder_generates_tests_handshakes_then_registers(isolated_builder):
    result = await build_from_description(
        description="Read items from the API by their item id.",
        base_url="https://api.example.com/v1",
        llm_client=_FakeLLM(),
    )

    connector = isolated_builder.get_connector(result["connector"]["id"])
    assert result["status"] == "available"
    assert result["validation"]["generated_tests"]["unittest"] == "passed"
    assert result["validation"]["mcp_handshake"] == "passed"
    assert result["validation"]["available_to_agent"] is True
    assert connector is not None and connector.enabled is True
    assert connector.last_test_status == "ok"
    assert connector.tools[0]["name"] == "get_item"
    assert connector.tools[0]["annotations"]["readOnlyHint"] is True
    assert all(
        path.endswith(("server.py", "manifest.json", "schemas.json", "mcp-config.json", "test_manifest.py", "README.md"))
        for path in result["generated_files"].values()
    )


async def test_builder_accepts_and_encrypts_ui_credential(isolated_builder):
    secret = "token-that-must-not-leak"
    result = await build_from_description(
        description="Read items from the authenticated API by their item id.",
        base_url="https://api.example.com/v1",
        llm_client=_FakeLLM(
            auth={"env_var": "NEXUS_MCP_API_TOKEN", "header": "Authorization", "prefix": "Bearer "}
        ),
        auth_secret=secret,
    )

    connector = isolated_builder.get_connector(result["connector"]["id"])
    assert connector is not None
    assert connector.env["NEXUS_MCP_API_TOKEN"] == secret
    assert result["connector"]["env"]["NEXUS_MCP_API_TOKEN"] == "••••••••"
    assert secret not in Path(result["generated_files"]["config"]).read_text(encoding="utf-8")
    assert "<set NEXUS_MCP_API_TOKEN in the MCP host environment>" in Path(
        result["generated_files"]["config"]
    ).read_text(encoding="utf-8")
    store_contents = store_module.MCP_STORE_FILE.read_text(encoding="utf-8")
    activity_contents = store_module.MCP_ACTIVITY_FILE.read_text(encoding="utf-8")
    assert secret not in store_contents
    assert secret not in activity_contents
    assert "nexus-fernet:v1:" in store_contents
    assert secret not in json.dumps(isolated_builder.export_connector(connector.id))


def test_mcp_activity_is_append_only_and_stores_only_safe_summaries(isolated_builder, tmp_path):
    secret = "sensitive-query-value"
    arguments = {"query": secret}
    event_id = isolated_builder.start_activity(
        tool="search",
        kind="tool_call",
        source="agent",
        connector_id="mcp_activity_test",
        connector_name="Activity test",
        argument_names=list(arguments),
        detail="A chamar a tool MCP",
    )
    isolated_builder.update_activity(
        event_id,
        status="ok",
        phase="complete",
        detail="Resultado MCP recebido",
        result_shape="1 content item(s); types: text",
        duration_ms=8.5,
    )

    activity_text = store_module.MCP_ACTIVITY_FILE.read_text(encoding="utf-8")
    assert secret not in activity_text
    assert '"argument_names":["query"]' in activity_text
    latest = MCPConnectorStore().list_activity(limit=1)[0]
    assert latest["id"] == event_id
    assert latest["status"] == "ok"
    assert latest["duration_ms"] == 8.5
    assert len(activity_text.splitlines()) == 2


def test_builder_rejects_public_http_and_url_userinfo():
    with pytest.raises(MCPBuilderError, match="HTTPS"):
        builder._validate_base_url("http://api.example.com")
    with pytest.raises(MCPBuilderError, match="credenciais"):
        builder._validate_base_url("https://user:password@api.example.com")


def test_builder_rejects_external_paths_and_unknown_schema_keywords():
    payload = {
        "name": "unsafe",
        "description": "A tool",
        "method": "GET",
        "path": "https://other.example/path",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "pathParams": [],
        "queryParams": [],
        "bodyParam": None,
    }
    with pytest.raises(ValidationError):
        builder.MCPBuildTool.model_validate(payload)
    with pytest.raises(MCPBuilderError, match="não suportadas"):
        builder._validate_schema({"type": "object", "properties": {}, "$ref": "https://evil/schema"})


def test_connector_store_encrypts_secrets_at_rest(isolated_builder, tmp_path):
    connector = MCPConnector(
        id="mcp_secret_storage",
        name="Secret storage",
        template_id="custom",
        command="python",
        args=["--connection", "postgresql://user:db-secret@localhost/db"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp-never-store-plaintext"},
        secret_arg_indexes=[1],
    )
    isolated_builder.register_connector(connector)
    contents = (tmp_path / "mcp_connectors.json").read_text(encoding="utf-8")
    public = connector.to_public_dict()

    assert "ghp-never-store-plaintext" not in contents
    assert "db-secret" not in contents
    assert "nexus-fernet:v1:" in contents
    assert public["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "••••••••"
    assert public["args"][1] == "••••••••"


def test_connector_cipher_refuses_public_development_key(monkeypatch):
    from types import SimpleNamespace

    from backend.config import settings as settings_module

    monkeypatch.delenv("NEXUS_MCP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(
        settings_module,
        "get_settings",
        lambda: SimpleNamespace(secret_key="development-secret-key-change-in-production"),
    )

    assert store_module._secret_cipher() is None


def test_tool_error_does_not_mark_the_mcp_handshake_unhealthy(isolated_builder):
    connector = MCPConnector(
        id="mcp_activity_state",
        name="Activity state",
        template_id="custom",
        command="python",
        last_test_status="ok",
    )
    isolated_builder.register_connector(connector)

    isolated_builder.record_tool_call(connector.id, "search", 9.5, success=False)

    assert connector.last_test_status == "ok"
    assert connector.last_activity_status == "error"


async def test_readonly_passthrough_checks_live_server_annotation(isolated_builder, monkeypatch):
    connector = MCPConnector(
        id="mcp_untrusted",
        name="Untrusted",
        template_id="custom",
        command="python",
        enabled=True,
        last_test_status="ok",
    )
    isolated_builder._connectors[connector.id] = connector

    async def list_tools(_connector, *, timeout=35.0):
        return [{"name": "write_data", "annotations": {"readOnlyHint": False, "destructiveHint": True}}]

    monkeypatch.setattr(runtime, "list_connector_tools", list_tools)
    with pytest.raises(runtime.MCPRuntimeError, match="aprovação"):
        await mcp_call_readonly_tool(connector.id, "write_data", {})


async def test_readonly_call_needs_explicit_schema_bound_permission(isolated_builder, monkeypatch):
    connector = MCPConnector(
        id="mcp_user_approved",
        name="Approved read server",
        template_id="custom",
        command="python",
        enabled=True,
        last_test_status="ok",
        tools=[
            {
                "name": "search_items",
                "description": "Search items",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            }
        ],
    )
    isolated_builder.register_connector(connector)
    live_tools = list(connector.tools)

    async def list_tools(_connector, *, timeout=35.0):
        return live_tools

    async def call_tool(connector_id, tool_name, arguments):
        return {"connector_id": connector_id, "tool": tool_name}

    monkeypatch.setattr(runtime, "list_connector_tools", list_tools)
    monkeypatch.setattr(mcp_tools_module, "call_connector_tool", call_tool)

    recommendation = await mcp_tools_module.mcp_recommend_tools("search items")
    assert recommendation["matches"][0]["risk"] == "approval_required"
    with pytest.raises(runtime.MCPRuntimeError, match="ainda não foi aprovada"):
        await mcp_call_readonly_tool(connector.id, "search_items", {"query": "private value"})

    isolated_builder.set_approved_readonly_tools(connector.id, ["search_items"])
    recommendation = await mcp_tools_module.mcp_recommend_tools("search items")
    assert recommendation["matches"][0]["risk"] == "user_approved_read_only"
    result = await mcp_call_readonly_tool(connector.id, "search_items", {"query": "private value"})
    assert result["tool"] == "search_items"

    live_tools = [{**live_tools[0], "description": "Changed server contract"}]
    with pytest.raises(runtime.MCPRuntimeError, match="ainda não foi aprovada"):
        await mcp_call_readonly_tool(connector.id, "search_items", {"query": "private value"})


def test_stdio_child_environment_does_not_inherit_unlisted_credentials(monkeypatch):
    connector = MCPConnector(
        id="mcp_env",
        name="Environment boundary",
        template_id="custom",
        command="python",
        pass_through_env=["NEXUS_MCP_ALLOWED"],
    )
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-forward")
    monkeypatch.setenv("NEXUS_MCP_ALLOWED", "allowed")
    params = runtime._server_parameters(connector)
    assert params.env is not None
    assert "OPENAI_API_KEY" not in params.env
    assert params.env["NEXUS_MCP_ALLOWED"] == "allowed"


def test_primary_agent_exposes_discovery_call_and_builder_actions():
    names = {
        item["function"]["name"]
        for item in (NexusPrimaryAgent()._openai_tool_schemas() or [])
    }
    assert {
        "mcp_list_tools",
        "mcp_recommend_tools",
        "mcp_call_readonly_tool",
        "mcp_call_tool",
        "mcp_builder",
    } <= names
    assert tool_requires_confirmation(get_tool("mcp_call_tool"))
    assert tool_requires_confirmation(get_tool("mcp_builder"))
