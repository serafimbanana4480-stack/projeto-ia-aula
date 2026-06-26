"""Integration tests for health API endpoints."""
from __future__ import annotations


def test_health_check(client):
    """Test GET /api/health endpoint."""
    response = client.get("/api/health")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "status" in data
    assert data["status"] == "healthy"


def test_readiness_check(client):
    """Test GET /api/ready endpoint."""
    response = client.get("/api/ready")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "status" in data
    assert "dependencies" in data


def test_system_health_check(client):
    """Test GET /api/system/health endpoint."""
    response = client.get("/api/system/health")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "status" in data
    assert "timestamp" in data
    assert "components" in data
    assert "summary" in data
    
    # Verify components structure
    assert isinstance(data["components"], dict)
    
    # Verify summary structure
    assert "total" in data["summary"]
    assert "healthy" in data["summary"]
    assert "degraded" in data["summary"]
    assert "unhealthy" in data["summary"]
    
    # Verify data types
    assert isinstance(data["summary"]["total"], int)
    assert isinstance(data["summary"]["healthy"], int)
    assert isinstance(data["summary"]["degraded"], int)
    assert isinstance(data["summary"]["unhealthy"], int)


def test_root_health(client):
    """Test GET /health endpoint (root level)."""
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "status" in data
    assert data["status"] == "ok"
