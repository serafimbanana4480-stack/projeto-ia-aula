"""The MCP Builder route must answer with a typed error, not an opaque 500.

The builder imports the MCP SDK, so it can be unavailable in a broken
runtime. The route used to import it outside the ``try`` that maps
``MCPBuilderError`` to a 4xx, so a missing dependency surfaced as
"Internal Server Error" instead of the designed 503/422.
"""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from backend.middleware.auth import create_access_token, require_admin
from backend.orchestrator.main import app


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token({"sub": "test-mcp-builder", "email": "builder@test.com"})
    return {"Authorization": f"Bearer {token}"}


def test_builder_route_returns_a_typed_error_not_a_500(auth_headers, monkeypatch):
    """A missing MCP dependency is a 503 with a typed payload."""
    monkeypatch.setitem(app.dependency_overrides, require_admin, lambda: {"user_id": "admin"})
    # ``None`` in sys.modules makes the import fail the way a broken
    # runtime does (the SDK is not installed).
    monkeypatch.setitem(sys.modules, "backend.mcp.builder", None)

    client = TestClient(app)
    response = client.post(
        "/api/mcp/builder/build",
        headers=auth_headers,
        json={
            "description": "Listar as issues abertas de um repositório",
            "base_url": "https://api.example.com",
        },
    )

    assert response.status_code != 500
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["category"] == "dependency_unavailable"
    assert "MCP Builder" in detail["message"]
