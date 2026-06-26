"""Integration tests for metrics API endpoints."""
from __future__ import annotations


def test_get_current_metrics(client):
    """Test GET /api/metrics/current endpoint."""
    response = client.get("/api/metrics/current")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "tokens_per_second" in data
    assert "active_model" in data
    assert "active_sessions" in data
    assert "queue_depth" in data
    assert "ram_used_bytes" in data
    assert "ram_total_bytes" in data
    assert "ram_percent" in data
    assert "cpu_percent" in data
    assert "disk_used_bytes" in data
    assert "disk_total_bytes" in data
    assert "disk_percent" in data
    assert "uptime_seconds" in data
    assert "requests_total" in data
    assert "requests_successful" in data
    assert "requests_failed" in data
    assert "avg_latency_ms" in data
    assert "timestamp" in data
    
    # Verify data types
    assert isinstance(data["tokens_per_second"], (int, float))
    assert isinstance(data["active_model"], str)
    assert isinstance(data["active_sessions"], int)
    assert isinstance(data["queue_depth"], int)
    assert isinstance(data["ram_used_bytes"], int)
    assert isinstance(data["ram_total_bytes"], int)
    assert isinstance(data["ram_percent"], (int, float))
    assert isinstance(data["cpu_percent"], (int, float))
    assert isinstance(data["uptime_seconds"], (int, float))
    assert isinstance(data["requests_total"], int)
    assert isinstance(data["timestamp"], (int, float))


def test_get_metrics_history(client):
    """Test GET /api/metrics/history endpoint."""
    response = client.get("/api/metrics/history?seconds=3600&metric=tokens_per_second")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response is a list
    assert isinstance(data, list)


def test_get_metrics_history_multi(client):
    """Test GET /api/metrics/history/multi endpoint."""
    response = client.get("/api/metrics/history/multi?seconds=3600")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response is a dict
    assert isinstance(data, dict)


def test_get_models_status(client):
    """Test GET /api/models/status endpoint."""
    response = client.get("/api/models/status")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response is a list
    assert isinstance(data, list)
    
    # If data is not empty, verify structure
    if data:
        model = data[0]
        assert "id" in model
        assert "size_bytes" in model
        assert "status" in model


def test_get_request_flow(client):
    """Test GET /api/metrics/flow endpoint."""
    response = client.get("/api/metrics/flow")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert isinstance(data, dict)
