"""Integration tests for metrics API endpoints."""
from __future__ import annotations

import httpx
import pytest

from backend.llm import multi_llm_manager
from backend.observability.routes import metrics as metrics_routes


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


def test_get_usage_returns_real_tracker_usage_by_provider(client, monkeypatch: pytest.MonkeyPatch):
    tracker = multi_llm_manager.TokenTracker()
    manager = multi_llm_manager.MultiLLMManager()
    manager._tracker = tracker
    manager.register_provider("openai", object())
    monkeypatch.setattr(multi_llm_manager, "_compute_cost", lambda **_kwargs: 0.0042)
    monkeypatch.setattr(
        "backend.llm.cost_governor.get_cost_governor",
        lambda: type("GovernorStub", (), {"daily_budget_usd": 0, "record": lambda *_a, **_k: None})(),
    )
    manager._record_usage(
        provider_name="openai",
        model="gpt-mini",
        messages=[{"role": "user", "content": "track these input tokens"}],
        output_text="track this response",
    )
    monkeypatch.setattr(metrics_routes, "_get_usage_tracker", lambda: tracker)

    response = client.get("/api/metrics/usage?range=7d")

    assert response.status_code == 200
    data = response.json()
    assert data["total_tokens"] > 0
    assert data["total_tokens_in"] > 0
    assert data["total_tokens_out"] > 0
    assert data["total_cost"] == 0.0042
    assert data["cost_is_estimated"] is True
    assert data["source"] == "token_tracker_in_memory"
    assert data["by_model"]["gpt-mini"]["total_tokens"] == data["total_tokens"]
    assert data["by_model"]["gpt-mini"]["cost"] == 0.0042
    assert data["by_provider"] == {"openai": data["total_tokens"]}
    assert "by_agent" not in data


def test_get_models_status(client, monkeypatch: pytest.MonkeyPatch):
    """Test GET /api/models/status endpoint."""
    monkeypatch.setattr(metrics_routes, "_configured_local_model_provider", lambda: "ollama")
    monkeypatch.setattr(
        metrics_routes,
        "_model_inventory_request",
        lambda _provider: ("http://ollama.test/api/tags", {}, {}),
    )

    async def successful_get(
        _client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen-local", "size": 100, "details": {}}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", successful_get)

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
        assert model["provider"] == "ollama"


def test_get_request_flow(client):
    """Test GET /api/metrics/flow endpoint."""
    response = client.get("/api/metrics/flow")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert isinstance(data, dict)
