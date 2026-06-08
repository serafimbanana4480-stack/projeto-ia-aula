"""Integration tests for main API endpoints."""

import pytest
from fastapi.testclient import TestClient

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app


@pytest.fixture
def client() -> TestClient:
    token = create_access_token({"sub": "test-user", "email": "test@test.com"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.mark.integration
class TestHealthEndpoint:
    """Test health endpoint."""

    def test_health_check(self, client: TestClient) -> None:
        """Test that health endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


@pytest.mark.integration
class TestChatEndpoint:
    """Test chat endpoint integration."""

    def test_chat_endpoint_requires_message(self, client: TestClient) -> None:
        """Test that chat endpoint requires message."""
        response = client.post("/api/chat", json={})
        assert response.status_code == 422  # Validation error


@pytest.mark.integration
class TestFilesEndpoint:
    """Test files endpoint integration."""

    def test_files_read_requires_path(self, client: TestClient) -> None:
        """Test that files read requires path."""
        response = client.post("/api/files/read", json={})
        assert response.status_code == 422  # Validation error

    def test_files_write_requires_path_and_content(self, client: TestClient) -> None:
        """Test that files write requires path and content."""
        response = client.post("/api/files/write", json={"path": "test.txt"})
        assert response.status_code == 422  # Validation error


@pytest.mark.integration
class TestTerminalEndpoint:
    """Test terminal endpoint integration."""

    def test_terminal_execute_requires_command(self, client: TestClient) -> None:
        """Test that terminal execute requires command."""
        response = client.post("/api/terminal/execute", json={})
        assert response.status_code == 422  # Validation error

    def test_terminal_timeout_bounds(self, client: TestClient) -> None:
        """Test that terminal timeout is within bounds."""
        response = client.post(
            "/api/terminal/execute",
            json={"command": "ls", "timeout_seconds": 1000},
        )
        assert response.status_code == 422  # Validation error


@pytest.mark.integration
class TestProjectsEndpoint:
    """Test projects endpoint integration."""

    def test_projects_create_requires_name_and_path(self, client: TestClient) -> None:
        """Test that projects create requires name and path."""
        response = client.post("/api/projects", json={})
        assert response.status_code == 422  # Validation error
