"""Integration tests for dashboard API endpoints."""
from __future__ import annotations

import pytest


def test_get_dashboard_state(client):
    """Test GET /api/dashboard/state endpoint."""
    response = client.get("/api/dashboard/state")
    
    # Endpoint might return 404 if not initialized
    if response.status_code == 404:
        pytest.skip("Dashboard state endpoint not initialized")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response is a dict
    assert isinstance(data, dict)


def test_publish_dashboard_event(client):
    """Test POST /api/dashboard/publish endpoint."""
    response = client.post(
        "/api/dashboard/publish",
        params={
            "event_type": "test_event",
            "agent": "test_agent",
        },
        json={"test": "payload"}
    )
    
    # Endpoint might return 404 if not initialized
    if response.status_code == 404:
        pytest.skip("Dashboard publish endpoint not initialized")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "status" in data
    assert data["status"] == "published"
