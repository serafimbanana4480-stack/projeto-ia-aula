"""Tests for the MCP Connector Wizard API (backend/orchestrator/routes/mcp.py)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.middleware.auth import create_access_token
from backend.mcp.store import MCPConnectorStore
from backend.orchestrator.main import app


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token({"sub": "test-mcp", "email": "mcp@test.com"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point the singleton store at a throwaway file so tests never touch
    the real data/mcp_connectors.json and never leak state between tests."""
    from backend.mcp import store as store_module

    monkeypatch.setattr(store_module, "MCP_STORE_FILE", tmp_path / "mcp_connectors.json")
    fresh = MCPConnectorStore.__new__(MCPConnectorStore)
    fresh._connectors = {}
    store_module.mcp_store._connectors = {}
    store_module.mcp_store.__dict__.update(fresh.__dict__)
    yield


def test_list_templates(client: TestClient, auth_headers):
    response = client.get("/api/mcp/templates", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert len(data["templates"]) >= 8
    ids = {t["id"] for t in data["templates"]}
    assert "filesystem" in ids
    assert "github" in ids
    assert "custom" in ids


def test_get_template_detail(client: TestClient, auth_headers):
    response = client.get("/api/mcp/templates/filesystem", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["command"] == "npx"
    assert "{root_path}" in data["args"]


def test_get_template_not_found(client: TestClient, auth_headers):
    response = client.get("/api/mcp/templates/nonexistent", headers=auth_headers)
    assert response.status_code == 404


def test_create_list_and_delete_connector(client: TestClient, auth_headers):
    create = client.post(
        "/api/mcp/connectors",
        headers=auth_headers,
        json={
            "name": "Meu Filesystem",
            "template_id": "filesystem",
            "params": {"root_path": "/tmp/project"},
            "env": {},
        },
    )
    assert create.status_code == 200
    connector = create.json()
    assert connector["name"] == "Meu Filesystem"
    assert connector["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/project"]
    connector_id = connector["id"]

    listing = client.get("/api/mcp/connectors", headers=auth_headers)
    assert listing.status_code == 200
    assert any(c["id"] == connector_id for c in listing.json()["connectors"])

    deleted = client.delete(f"/api/mcp/connectors/{connector_id}", headers=auth_headers)
    assert deleted.status_code == 200

    listing_after = client.get("/api/mcp/connectors", headers=auth_headers)
    assert not any(c["id"] == connector_id for c in listing_after.json()["connectors"])


def test_secrets_are_masked_in_public_dict(client: TestClient, auth_headers):
    create = client.post(
        "/api/mcp/connectors",
        headers=auth_headers,
        json={
            "name": "GitHub",
            "template_id": "github",
            "params": {},
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_supersecrettoken"},
        },
    )
    assert create.status_code == 200
    data = create.json()
    assert data["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] != "ghp_supersecrettoken"
    assert data["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "••••••••"


def test_test_connector_reports_missing_required_env(client: TestClient, auth_headers):
    create = client.post(
        "/api/mcp/connectors",
        headers=auth_headers,
        json={"name": "GitHub sem token", "template_id": "github", "params": {}, "env": {}},
    )
    connector_id = create.json()["id"]

    test_resp = client.post(f"/api/mcp/connectors/{connector_id}/test", headers=auth_headers)
    assert test_resp.status_code == 200
    result = test_resp.json()
    assert result["status"] == "error"
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in result["detail"]


def test_export_connector_produces_mcp_json(client: TestClient, auth_headers):
    create = client.post(
        "/api/mcp/connectors",
        headers=auth_headers,
        json={
            "name": "Filesystem Export",
            "template_id": "filesystem",
            "params": {"root_path": "/data"},
            "env": {},
        },
    )
    connector_id = create.json()["id"]

    export = client.get(f"/api/mcp/connectors/{connector_id}/export", headers=auth_headers)
    assert export.status_code == 200
    data = export.json()
    assert "mcpServers" in data
    assert "Filesystem Export" in data["mcpServers"]
    entry = data["mcpServers"]["Filesystem Export"]
    assert entry["command"] == "npx"
    assert entry["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "/data"]


def test_export_all(client: TestClient, auth_headers):
    client.post(
        "/api/mcp/connectors",
        headers=auth_headers,
        json={"name": "A", "template_id": "filesystem", "params": {"root_path": "/a"}, "env": {}},
    )
    client.post(
        "/api/mcp/connectors",
        headers=auth_headers,
        json={"name": "B", "template_id": "filesystem", "params": {"root_path": "/b"}, "env": {}},
    )
    export = client.get("/api/mcp/export", headers=auth_headers)
    assert export.status_code == 200
    servers = export.json()["mcpServers"]
    assert "A" in servers
    assert "B" in servers


def test_create_connector_unknown_template_returns_400(client: TestClient, auth_headers):
    response = client.post(
        "/api/mcp/connectors",
        headers=auth_headers,
        json={"name": "Bad", "template_id": "does-not-exist", "params": {}, "env": {}},
    )
    assert response.status_code == 400


def test_requires_auth(client: TestClient):
    response = client.get("/api/mcp/connectors")
    assert response.status_code in (401, 403)


def test_dashboard_status_includes_mcp_summary(client: TestClient):
    """The main dashboard status endpoint should surface an MCP connector
    summary (see backend/orchestrator/routes/dashboard.py) so the UI can show
    connector health without a second round trip."""
    response = client.get("/api/dashboard/status")
    assert response.status_code == 200
    data = response.json()
    assert "mcp_connectors" in data
    assert set(data["mcp_connectors"].keys()) >= {"total", "enabled", "healthy", "warning", "error", "untested"}
