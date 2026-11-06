"""Integration tests for main API endpoints."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.middleware.auth import create_access_token, require_admin
from backend.orchestrator.main import app


@pytest.fixture
def client() -> TestClient:
    token = create_access_token({"sub": "test-user", "email": "test@test.com"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def admin_client(client: TestClient) -> Generator[TestClient, None, None]:
    """Use an authorized principal for terminal behavior tests."""
    previous_override = client.app.dependency_overrides.get(require_admin)
    client.app.dependency_overrides[require_admin] = lambda: {"user_id": "test-admin"}
    try:
        yield client
    finally:
        if previous_override is None:
            client.app.dependency_overrides.pop(require_admin, None)
        else:
            client.app.dependency_overrides[require_admin] = previous_override


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

    def test_files_read_accepts_a_subdirectory_of_a_registered_project(
        self, client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The editor can use a project subdirectory as its workspace preset."""
        from backend.orchestrator.routes import files
        from backend.persistence.db import create_project

        project = tmp_path / "project-with-frontend"
        frontend = project / "frontend"
        frontend.mkdir(parents=True)
        create_project(name="files subdirectory test", path=str(project.resolve()))
        calls: list[tuple[str, str]] = []

        async def fake_read_file(path: str, project_path: str) -> dict[str, str]:
            calls.append((path, project_path))
            return {"path": path, "content": "export {};"}

        monkeypatch.setattr(files, "read_file", fake_read_file)
        response = client.post(
            "/api/files/read",
            json={"path": "src/index.ts", "project_path": str(frontend)},
        )

        assert response.status_code == 200, response.text
        assert len(calls) == 1
        assert Path(calls[0][0]) == Path("src/index.ts")
        assert calls[0][1] == str(frontend.resolve())


@pytest.mark.integration
class TestTerminalEndpoint:
    """Test terminal endpoint integration."""

    def test_terminal_execute_requires_command(self, admin_client: TestClient) -> None:
        """Test that terminal execute requires command."""
        response = admin_client.post("/api/terminal/execute", json={})
        assert response.status_code == 422  # Validation error

    def test_terminal_timeout_bounds(self, admin_client: TestClient) -> None:
        """Test that terminal timeout is within bounds."""
        response = admin_client.post(
            "/api/terminal/execute",
            json={"command": "ls", "timeout_seconds": 1000},
        )
        assert response.status_code == 422  # Validation error

    def test_terminal_rejects_unregistered_project_path(
        self, admin_client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The terminal cannot choose an arbitrary host directory as its cwd."""
        from backend.orchestrator.routes import terminal

        async def unexpected_execution(*args, **kwargs):
            pytest.fail("terminal command ran for an unregistered project path")

        monkeypatch.setattr(terminal, "execute_shell", unexpected_execution)
        outside = tmp_path / "unregistered-project"
        outside.mkdir()

        response = admin_client.post(
            "/api/terminal/execute",
            json={"command": "pwd", "project_path": str(outside)},
        )

        assert response.status_code == 400
        assert "project this instance knows" in response.json()["detail"]

    def test_terminal_uses_the_registered_project_root(
        self, admin_client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The selected registered workspace is passed through as the cwd."""
        from backend.orchestrator.routes import terminal
        from backend.persistence.db import create_project

        project = tmp_path / "registered-project"
        project.mkdir()
        create_project(name="terminal route test", path=str(project.resolve()))
        calls: list[tuple[str, str | None, int]] = []

        async def fake_execute_shell(
            command: str,
            *,
            cwd: str | None,
            timeout: int,
        ) -> dict[str, object]:
            calls.append((command, cwd, timeout))
            return {"stdout": "", "stderr": "", "exit_code": 0}

        monkeypatch.setattr(terminal, "execute_shell", fake_execute_shell)
        response = admin_client.post(
            "/api/terminal/execute",
            json={"command": "pwd", "project_path": str(project), "timeout_seconds": 12},
        )

        assert response.status_code == 200
        assert calls == [("pwd", str(project.resolve()), 12)]

    @pytest.mark.parametrize("folder_name", ["frontend", "backend", "config"])
    def test_terminal_accepts_a_registered_project_subdirectory(
        self,
        admin_client: TestClient,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
        folder_name: str,
    ) -> None:
        """Editor presets may use a subdirectory of the registered project."""
        from backend.orchestrator.routes import terminal
        from backend.persistence.db import create_project

        project = tmp_path / "project-with-subdirectory"
        selected_folder = project / folder_name
        selected_folder.mkdir(parents=True)
        create_project(name="terminal subdirectory test", path=str(project.resolve()))
        calls: list[tuple[str, str | None, int]] = []

        async def fake_execute_shell(
            command: str,
            *,
            cwd: str | None,
            timeout: int,
        ) -> dict[str, object]:
            calls.append((command, cwd, timeout))
            return {"stdout": "", "stderr": "", "exit_code": 0}

        monkeypatch.setattr(terminal, "execute_shell", fake_execute_shell)
        response = admin_client.post(
            "/api/terminal/execute",
            json={
                "command": "pwd",
                "project_path": str(selected_folder),
                "timeout_seconds": 12,
            },
        )

        assert response.status_code == 200, response.text
        assert calls == [("pwd", str(selected_folder.resolve()), 12)]

    def test_terminal_rejects_prefix_confusion_outside_registered_project(
        self, admin_client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sibling with the project name as a string prefix is still outside."""
        from backend.orchestrator.routes import terminal
        from backend.persistence.db import create_project

        project = tmp_path / "registered-project"
        sibling = tmp_path / "registered-project-evil"
        project.mkdir()
        sibling.mkdir()
        create_project(name="registered project", path=str(project.resolve()))

        async def unexpected_execution(*args, **kwargs):
            pytest.fail("terminal command ran outside the registered project")

        monkeypatch.setattr(terminal, "execute_shell", unexpected_execution)
        response = admin_client.post(
            "/api/terminal/execute",
            json={"command": "pwd", "project_path": str(sibling)},
        )

        assert response.status_code == 400
        assert "inside a project" in response.json()["detail"]


@pytest.mark.integration
class TestProjectsEndpoint:
    """Test projects endpoint integration."""

    def test_projects_create_requires_name_and_path(self, client: TestClient) -> None:
        """Test that projects create requires name and path."""
        response = client.post("/api/projects", json={})
        assert response.status_code == 422  # Validation error
