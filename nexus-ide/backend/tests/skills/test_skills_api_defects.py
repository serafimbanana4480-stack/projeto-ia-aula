"""REST-surface defects of the skills API.

Covers the routes that discarded the submitted fields, the missing request
models, the lifecycle routes that could not reach a store-backed skill, the
unvalidated ``limit`` and the DELETE that answered 200 for an unknown id.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core import skills_store as skills_store_module
from backend.core.skills_store import SkillsStore
from backend.middleware import auth as auth_module
from backend.orchestrator.main import app
from backend.orchestrator.routes import skills as skills_routes

AUTH = {"Authorization": "Bearer test-bypass"}


async def _fake_user() -> dict:
    return {"user_id": "test", "email": "t@t"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client bound to an isolated skills store."""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(skills_store_module, "SKILLS_DIR", skill_dir)
    monkeypatch.setattr(skills_store_module, "SKILLS_INDEX", skill_dir / "_index.json")
    monkeypatch.setenv("NEXUS_SKILLS_LIFECYCLE_DIR", str(tmp_path / "lifecycle"))
    store = SkillsStore()
    monkeypatch.setattr(SkillsStore, "_instance", store)
    monkeypatch.setattr(skills_routes, "_store", store)
    app.dependency_overrides[auth_module.require_auth] = _fake_user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(auth_module.require_auth, None)


def _create_skill(client: TestClient, **overrides: object) -> dict:
    payload: dict[str, object] = {
        "name": "Audit routine",
        "type": "workflow",
        "description": "Audit the repository",
        "trigger_pattern": "audit repository",
        "steps": ["Read the project", "Report the findings"],
        "verification": "Every finding cites a file",
        "tags": ["audit"],
    }
    payload.update(overrides)
    response = client.post("/api/skills", json=payload, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def test_update_skill_persists_the_fields(client: TestClient) -> None:
    """``PUT`` must write the submitted fields, not just answer "updated"."""
    created = _create_skill(client)
    skill_id = created["id"]

    response = client.put(
        f"/api/skills/{skill_id}",
        json={
            "name": "Renamed routine",
            "description": "A different description",
            "steps": ["Step one", "Step two", "Step three"],
            "tags": ["audit", "review"],
            "trigger_pattern": "renamed trigger",
            "verification": "Check the report",
            "auto_apply": True,
        },
        headers=AUTH,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "updated"
    assert body["skill"]["name"] == "Renamed routine"
    assert body["skill"]["description"] == "A different description"
    assert body["skill"]["steps"] == ["Step one", "Step two", "Step three"]
    assert body["skill"]["tags"] == ["audit", "review"]
    assert body["skill"]["trigger_pattern"] == "renamed trigger"
    assert body["skill"]["verification"] == "Check the report"
    assert body["skill"]["auto_apply"] is True

    # The change is persisted, not only echoed.
    stored = client.get(f"/api/skills/{skill_id}", headers=AUTH).json()
    assert stored["name"] == "Renamed routine"
    assert stored["steps"] == ["Step one", "Step two", "Step three"]
    assert stored["tags"] == ["audit", "review"]
    assert stored["trigger_pattern"] == "renamed trigger"
    assert stored["auto_apply"] is True


def test_update_skill_reports_not_found_for_an_unknown_id(client: TestClient) -> None:
    response = client.put(
        "/api/skills/skill_does_not_exist",
        json={"name": "Nothing"},
        headers=AUTH,
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Skill not found"


def test_delete_unknown_skill_returns_404(client: TestClient) -> None:
    response = client.delete("/api/skills/skill_does_not_exist", headers=AUTH)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Skill not found"


def test_store_created_skill_can_be_promoted(client: TestClient) -> None:
    """A skill created through the API follows the same lifecycle."""
    created = _create_skill(client)
    skill_id = created["id"]

    response = client.post(
        f"/api/skills/{skill_id}/promote",
        json={"reason": "reviewed by the operator"},
        headers=AUTH,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["from"] == "draft"
    assert body["to"] == "active"
    assert client.get(f"/api/skills/{skill_id}", headers=AUTH).json()["status"] == "active"


def test_store_created_skill_can_be_deprecated(client: TestClient) -> None:
    created = _create_skill(client)
    skill_id = created["id"]
    promoted = client.post(
        f"/api/skills/{skill_id}/promote",
        json={"reason": "reviewed by the operator"},
        headers=AUTH,
    )
    assert promoted.status_code == 200, promoted.text

    response = client.post(
        f"/api/skills/{skill_id}/deprecate",
        json={"reason": "superseded by a better routine"},
        headers=AUTH,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["from"] == "active"
    assert body["to"] == "deprecated"
    stored = client.get(f"/api/skills/{skill_id}", headers=AUTH).json()
    assert stored["status"] == "deprecated"


def test_store_created_skill_can_be_disabled(client: TestClient) -> None:
    created = _create_skill(client)
    skill_id = created["id"]

    response = client.post(
        f"/api/skills/{skill_id}/disable",
        json={"reason": "unsafe procedure"},
        headers=AUTH,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["to"] == "disabled"
    stored = client.get(f"/api/skills/{skill_id}", headers=AUTH).json()
    assert stored["status"] == "disabled"


def test_create_skill_rejects_a_string_for_steps(client: TestClient) -> None:
    """``steps`` is a list; a bare string used to be persisted as a string."""
    response = client.post(
        "/api/skills",
        json={"name": "Bad steps", "steps": "a,b,c"},
        headers=AUTH,
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/skills", headers=AUTH).json()["count"] == 0


def test_skill_limit_must_be_positive(client: TestClient) -> None:
    """``limit=-1`` used to mean "all but the last one"."""
    _create_skill(client, name="One")
    _create_skill(client, name="Two")

    rejected = client.get("/api/skills", params={"limit": -1}, headers=AUTH)
    zero = client.get("/api/skills", params={"limit": 0}, headers=AUTH)
    accepted = client.get("/api/skills", params={"limit": 1}, headers=AUTH)

    assert rejected.status_code == 422, rejected.text
    assert zero.status_code == 422, zero.text
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["count"] == 1


def test_lifecycle_routes_are_scoped_to_the_skill_owner(client: TestClient) -> None:
    """A skill owned by somebody else cannot be transitioned."""

    async def _other_user() -> dict:
        return {"user_id": "other", "email": "other@t"}

    created = _create_skill(client)
    skill_id = created["id"]

    client.app.dependency_overrides[auth_module.require_auth] = _other_user
    response = client.post(
        f"/api/skills/{skill_id}/disable",
        json={"reason": "not my skill"},
        headers=AUTH,
    )

    assert response.status_code == 404, response.text

    client.app.dependency_overrides[auth_module.require_auth] = _fake_user
    stored = client.get(f"/api/skills/{skill_id}", headers=AUTH)
    assert stored.status_code == 200, stored.text
    assert stored.json()["status"] == "draft"
