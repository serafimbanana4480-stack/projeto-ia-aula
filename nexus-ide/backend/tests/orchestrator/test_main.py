"""Tests for backend.orchestrator.main — FastAPI app lifecycle and /health."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.orchestrator.main import app


class TestHealthEndpoint:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_health_returns_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert set(payload["disk_pressure"]) >= {
            "status",
            "snapshot",
            "warning_threshold_percent",
            "critical_threshold_percent",
            "write_blocked",
        }
        assert payload["disk_pressure"]["snapshot"]["free_percent"] >= 0

    def test_app_metadata(self) -> None:
        assert app.title == "NEXUS IDE Orchestrator"
        assert app.version == "0.1.0"
