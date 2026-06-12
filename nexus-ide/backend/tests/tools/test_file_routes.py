"""End-to-end tests for the file API routes (POST /api/files/*).

Validates read, list and write endpoints with path-safety guards.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app


@pytest.fixture(autouse=True)
def mock_propose_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock propose_change to avoid database dependency on sessions."""
    from unittest.mock import MagicMock

    monkeypatch.setattr("backend.tools.file_ops.propose_change", MagicMock())


@pytest.fixture
def client() -> TestClient:
    token = create_access_token({"sub": "test-user", "email": "test@test.com"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


class TestReadFileRoute:
    def test_read_existing_relative_file(self, client: TestClient, tmp_path: Path) -> None:
        (tmp_path / "hello.py").write_text("print('hello')", encoding="utf-8")
        response = client.post(
            "/api/files/read",
            json={"path": "hello.py", "project_path": str(tmp_path)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["content"] == "print('hello')"
        assert body["path"].endswith("hello.py")

    def test_read_nonexistent_file(self, client: TestClient, tmp_path: Path) -> None:
        response = client.post(
            "/api/files/read",
            json={"path": "missing.py", "project_path": str(tmp_path)},
        )
        assert response.status_code == 200
        assert "error" in response.json()

    def test_read_blocked_path(self, client: TestClient) -> None:
        response = client.post(
            "/api/files/read",
            json={"path": "/etc/passwd", "project_path": "."},
        )
        assert response.status_code == 200
        assert "error" in response.json()


class TestListFilesRoute:
    def test_list_directory(self, client: TestClient, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        (tmp_path / "sub").mkdir()

        response = client.post(
            "/api/files/list",
            json={"path": ".", "project_path": str(tmp_path), "recursive": False},
        )
        assert response.status_code == 200
        body = response.json()
        names = {i["name"] for i in body["items"]}
        assert {"a.py", "b.py", "sub"}.issubset(names)
        assert body["count"] >= 3

    def test_list_directory_recursive_builds_tree(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        (tmp_path / "root.txt").write_text("root")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested")

        response = client.post(
            "/api/files/list",
            json={"path": ".", "project_path": str(tmp_path), "recursive": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["tree"]) > 0
        tree_names = {n["name"] for n in body["tree"]}
        assert "root.txt" in tree_names
        assert "sub" in tree_names

    def test_list_blocked_path(self, client: TestClient) -> None:
        response = client.post(
            "/api/files/list",
            json={"path": "/etc", "project_path": ".", "recursive": False},
        )
        assert response.status_code == 200
        assert "error" in response.json()


class TestWriteFileRoute:
    def test_write_new_relative_file(self, client: TestClient, tmp_path: Path) -> None:
        response = client.post(
            "/api/files/write",
            json={
                "path": "new.py",
                "content": "x = 1",
                "project_path": str(tmp_path),
                "session_id": "test-session",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body.get("written") is True
        assert (tmp_path / "new.py").read_text(encoding="utf-8") == "x = 1"

    def test_write_creates_parent_directories(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        response = client.post(
            "/api/files/write",
            json={
                "path": "src/utils/helpers.py",
                "content": "def helper(): pass",
                "project_path": str(tmp_path),
            },
        )
        assert response.status_code == 200
        assert (tmp_path / "src" / "utils" / "helpers.py").exists()

    def test_write_blocked_executable_extension(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        response = client.post(
            "/api/files/write",
            json={
                "path": "malicious.exe",
                "content": "binary",
                "project_path": str(tmp_path),
            },
        )
        assert response.status_code == 200
        assert "error" in response.json()

    def test_write_outside_project_blocked(self, client: TestClient, tmp_path: Path) -> None:
        response = client.post(
            "/api/files/write",
            json={
                "path": "../outside.py",
                "content": "x",
                "project_path": str(tmp_path),
            },
        )
        assert response.status_code == 200
        assert "error" in response.json()
