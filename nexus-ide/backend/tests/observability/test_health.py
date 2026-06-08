"""Tests for backend.observability.health — HealthChecker and /health endpoint."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.observability.health import HealthChecker
from backend.orchestrator.main import app


class TestHealthChecker:
    """Unit tests for :class:`HealthChecker` with mocked app.state."""

    @pytest.fixture
    def mock_state(self) -> MagicMock:
        return MagicMock()

    async def test_database_check(self, mock_state: MagicMock) -> None:
        checker = HealthChecker(mock_state)
        result = await checker._check_database()
        assert result["healthy"] is True
        assert result["status"] == "connected"

    async def test_llm_check_not_initialized(self, mock_state: MagicMock) -> None:
        mock_state.llm_client = None
        checker = HealthChecker(mock_state)
        result = await checker._check_llm()
        assert result["healthy"] is False
        assert result["status"] == "not_initialized"

    async def test_llm_check_with_health_check(self, mock_state: MagicMock) -> None:
        from unittest.mock import AsyncMock

        mock_client = MagicMock()
        mock_client.health_check = AsyncMock(return_value=True)
        mock_state.llm_client = mock_client
        checker = HealthChecker(mock_state)
        result = await checker._check_llm()
        assert result["healthy"] is True
        assert result["status"] == "reachable"

    async def test_dashboard_check_running(self, mock_state: MagicMock) -> None:
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_state.dashboard_monitor_task = mock_task
        checker = HealthChecker(mock_state)
        result = await checker._check_dashboard()
        assert result["healthy"] is True
        assert result["status"] == "running"

    async def test_dashboard_check_stopped(self, mock_state: MagicMock) -> None:
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_state.dashboard_monitor_task = mock_task
        checker = HealthChecker(mock_state)
        result = await checker._check_dashboard()
        assert result["healthy"] is False
        assert result["status"] == "stopped"

    async def test_guardian_check_running(self, mock_state: MagicMock) -> None:
        mock_guardian = MagicMock()
        mock_guardian._running = True
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_state.guardian_agent = mock_guardian
        mock_state.guardian_task = mock_task
        checker = HealthChecker(mock_state)
        result = await checker._check_guardian()
        assert result["healthy"] is True
        assert result["status"] == "running"

    async def test_guardian_check_not_started(self, mock_state: MagicMock) -> None:
        mock_state.guardian_agent = None
        mock_state.guardian_task = None
        checker = HealthChecker(mock_state)
        result = await checker._check_guardian()
        assert result["healthy"] is False
        assert result["status"] == "not_started"

    async def test_auto_correction_check_monitoring(self, mock_state: MagicMock) -> None:
        mock_loop = MagicMock()
        mock_loop._status = {"monitoring": True}
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_loop._task = mock_task
        mock_state.auto_correction = mock_loop
        checker = HealthChecker(mock_state)
        result = await checker._check_auto_correction()
        assert result["healthy"] is True
        assert result["status"] == "monitoring"

    async def test_auto_correction_check_not_started(self, mock_state: MagicMock) -> None:
        mock_state.auto_correction = None
        checker = HealthChecker(mock_state)
        result = await checker._check_auto_correction()
        assert result["healthy"] is False
        assert result["status"] == "not_started"

    async def test_workers_check_all_running(self, mock_state: MagicMock) -> None:
        class _FakeWorker:
            def __init__(self, name: str, status: str) -> None:
                self.name = name
                self.status = status

        mock_manager = MagicMock()
        mock_manager.list_workers.return_value = [
            _FakeWorker("CODE_WATCHER", "running"),
            _FakeWorker("MEMORY_WATCHER", "running"),
        ]
        mock_state.worker_manager = mock_manager
        checker = HealthChecker(mock_state)
        result = await checker._check_workers()
        assert result["healthy"] is True
        assert result["status"] == "all_running"
        assert result["workers"]["CODE_WATCHER"] == "running"

    async def test_workers_check_partial(self, mock_state: MagicMock) -> None:
        class _FakeWorker:
            def __init__(self, name: str, status: str) -> None:
                self.name = name
                self.status = status

        mock_manager = MagicMock()
        mock_manager.list_workers.return_value = [
            _FakeWorker("CODE_WATCHER", "running"),
            _FakeWorker("MEMORY_WATCHER", "stopped"),
        ]
        mock_state.worker_manager = mock_manager
        checker = HealthChecker(mock_state)
        result = await checker._check_workers()
        assert result["healthy"] is False
        assert result["status"] == "partial"

    async def test_workers_check_not_started(self, mock_state: MagicMock) -> None:
        mock_state.worker_manager = None
        checker = HealthChecker(mock_state)
        result = await checker._check_workers()
        assert result["healthy"] is False
        assert result["status"] == "not_started"

    async def test_file_locks_check(self, mock_state: MagicMock) -> None:
        checker = HealthChecker(mock_state)
        result = await checker._check_file_locks()
        assert result["healthy"] is True
        assert result["status"] == "functional"

    async def test_check_all_returns_report(self, mock_state: MagicMock) -> None:
        mock_state.llm_client = None
        mock_state.dashboard_monitor_task = None
        mock_state.guardian_agent = None
        mock_state.guardian_task = None
        mock_state.auto_correction = None
        mock_state.worker_manager = None

        checker = HealthChecker(mock_state)
        report = await checker.check_all()

        assert "status" in report
        assert "checks" in report
        assert "elapsed_ms" in report
        assert report["status"] == "degraded"
        # Database and file_locks should be healthy; the rest degraded
        assert report["checks"]["database"]["healthy"] is True
        assert report["checks"]["file_locks"]["healthy"] is True
        assert report["checks"]["llm"]["healthy"] is False
        assert report["checks"]["dashboard_agent"]["healthy"] is False
        assert report["checks"]["guardian_agent"]["healthy"] is False
        assert report["checks"]["auto_correction"]["healthy"] is False
        assert report["checks"]["background_workers"]["healthy"] is False
        # Total elapsed time should be under 2 seconds
        assert report["elapsed_ms"] < 2000


class TestHealthEndpoint:
    """Integration tests for the ``/health`` route via TestClient."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_health_fast_liveness(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_deep_returns_full_report(self, client: TestClient) -> None:
        response = client.get("/health?deep=true")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded")
        assert "checks" in data
        assert "elapsed_ms" in data
        checks = data["checks"]
        expected_keys = {
            "database",
            "llm",
            "dashboard_agent",
            "guardian_agent",
            "auto_correction",
            "background_workers",
            "file_locks",
        }
        assert set(checks.keys()) == expected_keys
        # Each check must have healthy + status
        for key in expected_keys:
            assert "healthy" in checks[key]
            assert "status" in checks[key]
        # Deep check should complete in under 2 seconds
        assert data["elapsed_ms"] < 2000
