"""Integration tests for agents API endpoints."""
from __future__ import annotations


def test_get_agents_topology(client):
    """Test GET /api/agents/topology endpoint."""
    response = client.get("/api/agents/topology")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "nodes" in data
    assert "links" in data
    
    # Verify nodes structure
    assert isinstance(data["nodes"], list)
    if data["nodes"]:
        node = data["nodes"][0]
        assert "id" in node
        assert "label" in node
        assert "x" in node
        assert "y" in node
        assert "color" in node
        assert "status" in node
        assert "size" in node
        assert "cpu" in node
        assert "memory" in node
    
    # Verify links structure
    assert isinstance(data["links"], list)
    if data["links"]:
        link = data["links"][0]
        assert "source" in link
        assert "target" in link
        assert "value" in link
        assert "active" in link


def test_get_agents_registry(client):
    """Test GET /api/agents/registry endpoint."""
    response = client.get("/api/agents/registry")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response is a list
    assert isinstance(data, list)
    
    # Verify agent structure (be flexible with field names)
    if data:
        agent = data[0]
        # Check for common fields that might exist
        assert "name" in agent or "id" in agent
        assert "status" in agent


def test_get_agents_status(client):
    """Test GET /api/agents/status endpoint."""
    response = client.get("/api/agents/status")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response is a dict with summary + agents list
    assert isinstance(data, dict)
    assert "total" in data
    assert "active" in data
    assert "idle" in data
    assert "agents" in data
    assert isinstance(data["agents"], list)
    
    # Verify simplified structure
    if data["agents"]:
        agent = data["agents"][0]
        assert "name" in agent
        assert "status" in agent
        assert "role" in agent


def test_get_agents_list(client):
    """Test GET /api/agents/list endpoint."""
    response = client.get("/api/agents/list")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure (can be list or dict)
    assert isinstance(data, (list, dict))
