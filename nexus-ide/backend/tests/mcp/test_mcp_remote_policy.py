"""A remote MCP connector must obey the public-address policy.

The rest of NEXUS refuses to talk to loopback, private, link-local, or
otherwise non-public addresses (``backend/tools/safe_http.py``). A remote
MCP connector is an outbound request made by the NEXUS host, so it follows
the same policy — otherwise a connector could be pointed at the NEXUS
backend itself or at the cloud metadata service.
"""

from __future__ import annotations

import pytest

from backend.mcp import runtime as mcp_runtime
from backend.mcp.store import MCPConnector


def _http_connector(url: str) -> MCPConnector:
    return MCPConnector(
        id="mcp_remote_policy",
        name="Remote",
        template_id="http-remote",
        transport="http",
        url=url,
    )


def test_remote_connector_rejects_loopback(isolated_store):
    """A loopback URL is refused when the connector is created."""
    with pytest.raises(ValueError) as excinfo:
        isolated_store.create_connector(
            name="Loopback",
            template_id="http-remote",
            params={"url": "http://127.0.0.1:8000/api/health"},
        )
    assert "inválido" in str(excinfo.value)


async def test_remote_connector_rejects_loopback_at_handshake(isolated_store):
    """A connector that already carries a loopback URL is never dialled."""
    connector = _http_connector("http://127.0.0.1/api/health")
    isolated_store._connectors[connector.id] = connector

    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_runtime.list_connector_tools(connector)

    assert "públic" in str(excinfo.value)


def test_remote_connector_rejects_cloud_metadata(isolated_store):
    """The cloud metadata service is not a public address."""
    with pytest.raises(ValueError) as excinfo:
        isolated_store.create_connector(
            name="Metadata",
            template_id="http-remote",
            params={"url": "http://169.254.169.254/latest/meta-data/iam/security-credentials/"},
        )
    assert "inválido" in str(excinfo.value)


async def test_remote_connector_rejects_cloud_metadata_at_handshake(isolated_store):
    """A connector pointing at the metadata service is never dialled."""
    connector = _http_connector("http://169.254.169.254/latest/meta-data/iam/security-credentials/")
    isolated_store._connectors[connector.id] = connector

    with pytest.raises(mcp_runtime.MCPRuntimeError) as excinfo:
        await mcp_runtime.list_connector_tools(connector)

    assert "públic" in str(excinfo.value)


def test_remote_connector_accepts_a_public_host(isolated_store):
    """A public HTTPS host is a valid remote MCP connector."""
    connector = isolated_store.create_connector(
        name="Public",
        template_id="http-remote",
        params={"url": "https://mcp.example.com/mcp"},
    )
    assert connector.url == "https://mcp.example.com/mcp"
    assert connector.transport == "http"
    # The same URL passes the runtime's own policy check.
    assert mcp_runtime._public_remote_url(connector.url) == connector.url
