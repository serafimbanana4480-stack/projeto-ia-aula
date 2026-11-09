"""Authorization boundary for shared MCP connector lifecycle operations."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.mcp.store import MCPConnector
from backend.middleware import auth as auth_module
from backend.orchestrator.routes import mcp as mcp_routes

_MUTATION_ROUTES = (
    (
        "POST",
        "/api/mcp/connectors",
        {
            "name": "Custom command",
            "template_id": "custom",
            "params": {"command": "python", "args": "-c print(1)"},
            "env": {},
        },
        "create_connector",
    ),
    ("PUT", "/api/mcp/connectors/mcp-auth-test", {"enabled": False}, "update_connector"),
    ("DELETE", "/api/mcp/connectors/mcp-auth-test", None, "delete_connector"),
    ("POST", "/api/mcp/connectors/mcp-auth-test/test", None, "test_connector"),
)


def _client() -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.include_router(mcp_routes.router, prefix="/api")
    return app, TestClient(app)


@pytest.mark.parametrize(("method", "path", "payload", "store_method"), _MUTATION_ROUTES)
def test_unauthenticated_user_cannot_mutate_or_start_mcp_connectors(
    method: str, path: str, payload: dict[str, object] | None, store_method: str
) -> None:
    app, client = _client()
    try:
        response = client.request(method, path, json=payload)
        assert response.status_code == 401
    finally:
        client.close()


@pytest.mark.parametrize(("method", "path", "payload", "store_method"), _MUTATION_ROUTES)
def test_non_admin_cannot_mutate_or_start_mcp_connectors(
    method: str,
    path: str,
    payload: dict[str, object] | None,
    store_method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, client = _client()

    def executor_must_not_be_reached(*_args: object, **_kwargs: object) -> None:
        pytest.fail(f"non-admin reached MCP store method {store_method}")

    monkeypatch.setattr(mcp_routes.mcp_store, store_method, executor_must_not_be_reached)
    monkeypatch.setattr(
        auth_module.get_auth_service(), "is_admin", lambda _user_id: False, raising=False
    )
    app.dependency_overrides[auth_module.require_auth] = lambda: {"user_id": "ordinary-user"}
    try:
        response = client.request(method, path, json=payload)
        assert response.status_code == 403
    finally:
        client.close()


@pytest.mark.parametrize(("method", "path", "payload", "store_method"), _MUTATION_ROUTES)
def test_admin_can_manage_and_test_mcp_connectors(
    method: str,
    path: str,
    payload: dict[str, object] | None,
    store_method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, client = _client()
    connector = MCPConnector(
        id="mcp-auth-test",
        name="Authorized test connector",
        template_id="custom",
        command="python",
        args=["-m", "example_mcp"],
    )
    calls: list[str] = []

    def fake_create(**_kwargs: object) -> MCPConnector:
        calls.append("create")
        return connector

    def fake_update(*_args: object, **_kwargs: object) -> MCPConnector:
        calls.append("update")
        return connector

    def fake_delete(_connector_id: str) -> bool:
        calls.append("delete")
        return True

    async def fake_test(_connector_id: str) -> dict[str, str]:
        calls.append("test")
        return {"status": "ok", "detail": "controlled handshake"}

    def fake_get(_connector_id: str) -> MCPConnector:
        return connector

    monkeypatch.setattr(mcp_routes.mcp_store, "create_connector", fake_create)
    monkeypatch.setattr(mcp_routes.mcp_store, "update_connector", fake_update)
    monkeypatch.setattr(mcp_routes.mcp_store, "delete_connector", fake_delete)
    monkeypatch.setattr(mcp_routes.mcp_store, "get_connector", fake_get)
    monkeypatch.setattr(mcp_routes.mcp_store, "test_connector", fake_test)
    monkeypatch.setattr(
        auth_module.get_auth_service(), "is_admin", lambda _user_id: True, raising=False
    )
    app.dependency_overrides[auth_module.require_auth] = lambda: {"user_id": "admin-user"}
    try:
        response = client.request(method, path, json=payload)
        assert response.status_code == 200, response.text
        assert calls == [store_method.removesuffix("_connector")]
    finally:
        client.close()


def test_non_admin_cannot_create_a_shared_connector_with_the_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, client = _client()
    monkeypatch.setattr(
        auth_module.get_auth_service(), "is_admin", lambda _user_id: False, raising=False
    )
    app.dependency_overrides[auth_module.require_auth] = lambda: {"user_id": "ordinary-user"}
    try:
        response = client.post(
            "/api/mcp/builder/build",
            json={
                "description": "Listar tickets de um serviço externo",
                "base_url": "https://api.example.com",
            },
        )
        assert response.status_code == 403
    finally:
        client.close()
