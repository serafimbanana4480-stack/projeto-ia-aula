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
        assert response.json() == {"status": "ok"}

    def test_app_metadata(self) -> None:
        assert app.title == "NEXUS IDE Orchestrator"
        assert app.version == "0.1.0"
