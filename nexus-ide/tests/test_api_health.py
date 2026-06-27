"""Basic API health tests."""
import pytest
from fastapi.testclient import TestClient

def test_health_endpoint(client):
    """Test that health endpoint returns ok."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
