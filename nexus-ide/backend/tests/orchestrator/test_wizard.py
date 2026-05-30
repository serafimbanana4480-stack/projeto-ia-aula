"""Tests for Project Wizard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.orchestrator.routes.wizard import router
from backend.orchestrator.main import app

app.include_router(router, prefix="/api")
client = TestClient(app)


def test_list_templates():
    response = client.get("/api/wizard/templates")
    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert len(data["templates"]) > 0


def test_get_template():
    response = client.get("/api/wizard/templates/python")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "python"


def test_get_template_not_found():
    response = client.get("/api/wizard/templates/nonexistent")
    assert response.status_code == 404


def test_wizard_start():
    response = client.post("/api/wizard/start", json={"objective": "Create a Python API"})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["status"] == "asking"
    assert "questions" in data


def test_wizard_answer_and_generate(tmp_path):
    # Start wizard
    start = client.post("/api/wizard/start", json={"objective": "Create a CLI app"})
    session_id = start.json()["session_id"]

    # Answer questions
    answer = client.post(
        "/api/wizard/answer",
        json={
            "session_id": session_id,
            "answers": {
                "project_name": "my-cli",
                "description": "A test CLI",
                "template": "cli_python",
            },
        },
    )
    assert answer.status_code == 200
    assert answer.json()["status"] == "ready"

    # Generate project
    generate = client.post(
        "/api/wizard/generate",
        json={"session_id": session_id, "project_path": str(tmp_path)},
    )
    assert generate.status_code == 200
    data = generate.json()
    assert data["status"] == "done"
    assert data["count"] > 0
    assert (tmp_path / "my-cli" / "pyproject.toml").exists()
