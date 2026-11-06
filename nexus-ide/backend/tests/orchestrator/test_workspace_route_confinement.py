"""Workspace HTTP routes must not follow a path outside the selected project."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware import auth as auth_module
from backend.orchestrator.routes import workspace as workspace_routes


def _client() -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.include_router(workspace_routes.router, prefix="/api")
    app.dependency_overrides[auth_module.require_auth] = lambda: {"user_id": "explorer"}
    return app, TestClient(app)


def test_workspace_read_refuses_a_path_outside_the_selected_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("private-marker", encoding="utf-8")
    _app, client = _client()
    try:
        response = client.post(
            "/api/workspace/files/read",
            json={"path": str(secret), "project_path": str(project)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["error_category"] == "project_scope_denied"
        assert "private-marker" not in response.text
        assert secret.read_text(encoding="utf-8") == "private-marker"
    finally:
        client.close()


def test_workspace_read_returns_a_file_inside_the_selected_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    visible = project / "visible.txt"
    visible.write_text("inside-marker", encoding="utf-8")
    _app, client = _client()
    try:
        response = client.post(
            "/api/workspace/files/read",
            json={"path": str(visible), "project_path": str(project)},
        )
        assert response.status_code == 200
        assert response.json()["content"] == "inside-marker"
    finally:
        client.close()


def test_workspace_read_without_a_project_asks_for_one(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("private-marker", encoding="utf-8")
    _app, client = _client()
    try:
        response = client.post(
            "/api/workspace/files/read",
            json={"path": str(secret)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["error_category"] == "project_scope_denied"
        assert "project" in body["error"].lower()
        assert "private-marker" not in response.text
    finally:
        client.close()


def test_workspace_write_cannot_leave_the_selected_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("kept", encoding="utf-8")
    _app, client = _client()
    try:
        response = client.post(
            "/api/workspace/files/write",
            json={
                "path": str(outside),
                "content": "overwritten",
                "project_path": str(project),
            },
        )
        assert response.status_code == 200
        assert response.json()["error_category"] == "project_scope_denied"
        assert outside.read_text(encoding="utf-8") == "kept"
    finally:
        client.close()
