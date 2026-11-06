"""Authorization boundary for direct workspace execution endpoints."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware import auth as auth_module
from backend.orchestrator.routes import files as files_routes
from backend.orchestrator.routes import terminal as terminal_routes
from backend.orchestrator.routes import workspace as workspace_routes

_EXECUTION_ROUTES = (
    (
        "/api/workspace/terminal/shell",
        {"command": "echo safe", "project_path": "C:/workspace/project"},
        "workspace",
        "execute_shell",
    ),
    (
        "/api/workspace/terminal/python",
        {"code": "print('safe')", "project_path": "C:/workspace/project"},
        "workspace",
        "execute_python",
    ),
    (
        "/api/workspace/terminal/script",
        {"path": "safe.py", "project_path": "C:/workspace/project"},
        "workspace",
        "execute_script",
    ),
    (
        "/api/terminal/execute",
        {"command": "python safe.py", "project_path": ".", "timeout_seconds": 30},
        "terminal",
        "execute_shell",
    ),
)


def _client() -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.include_router(workspace_routes.router, prefix="/api")
    app.include_router(terminal_routes.router, prefix="/api")
    return app, TestClient(app)


def _executor_module(module_name: str) -> ModuleType:
    if module_name == "terminal":
        return terminal_routes
    return workspace_routes


@pytest.mark.parametrize(("path", "payload", "module_name", "executor_name"), _EXECUTION_ROUTES)
def test_unauthenticated_user_cannot_execute_workspace_commands(
    path: str, payload: dict[str, object], module_name: str, executor_name: str
) -> None:
    app, client = _client()
    try:
        response = client.post(path, json=payload)
        assert response.status_code == 401
    finally:
        client.close()


@pytest.mark.parametrize(("path", "payload", "module_name", "executor_name"), _EXECUTION_ROUTES)
def test_non_admin_is_rejected_before_workspace_executor(
    path: str,
    payload: dict[str, object],
    module_name: str,
    executor_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, client = _client()
    calls: list[dict[str, object]] = []

    async def fake_executor(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append({"args": args, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(_executor_module(module_name), executor_name, fake_executor)
    monkeypatch.setattr(
        auth_module.get_auth_service(), "is_admin", lambda _user_id: False, raising=False
    )
    app.dependency_overrides[auth_module.require_auth] = lambda: {"user_id": "ordinary-user"}
    try:
        response = client.post(path, json=payload)
        assert response.status_code == 403
        assert calls == []
    finally:
        client.close()


@pytest.mark.parametrize(("path", "payload", "module_name", "executor_name"), _EXECUTION_ROUTES)
def test_admin_can_still_use_workspace_execution(
    path: str,
    payload: dict[str, object],
    module_name: str,
    executor_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app, client = _client()
    calls: list[dict[str, object]] = []

    async def fake_executor(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append({"args": args, **kwargs})
        if module_name == "terminal":
            return {"stdout": "safe", "stderr": "", "exit_code": 0}
        return {"ok": True}

    monkeypatch.setattr(_executor_module(module_name), executor_name, fake_executor)
    monkeypatch.setattr(
        auth_module.get_auth_service(), "is_admin", lambda _user_id: True, raising=False
    )
    app.dependency_overrides[auth_module.require_auth] = lambda: {"user_id": "admin-user"}
    if module_name == "terminal":
        monkeypatch.setattr(
            files_routes, "_resolve_project_root", lambda *_args: tmp_path
        )
    try:
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        assert len(calls) == 1
        if module_name == "terminal":
            assert response.json()["stdout"] == "safe"
        else:
            assert response.json() == {"ok": True}
            assert calls[0]["cwd"] == "C:/workspace/project"
    finally:
        client.close()
