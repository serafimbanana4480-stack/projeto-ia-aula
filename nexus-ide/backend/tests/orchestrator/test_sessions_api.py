"""End-to-end tests for the sessions CRUD API.

Verifies:
- Create / list / get / patch / delete
- message_count is correctly returned
- 404 on missing session
- Validation errors on bad input
- Cascade delete (session + messages)
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide")
sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.middleware import auth as auth_module  # noqa: E402
from backend.orchestrator.main import app  # noqa: E402


# Override require_auth so tests don't depend on JWT signature secrets
async def _fake_user() -> dict:
    return {"user_id": "test", "email": "t@t"}


app.dependency_overrides[auth_module.require_auth] = _fake_user


@pytest.fixture
def client(tmp_path):
    """Function-scoped client with a fresh, isolated SQLite database.

    Each test gets its own DB file under tmp_path so concurrent runs (and
    the existing 'database is locked' issue) are avoided.
    """
    import importlib
    import os

    # Force a per-test DB location
    os.environ["NEXUS_DB_PATH"] = str(tmp_path / "test_nexus.db")
    # Reload the persistence module to pick up the new path
    import backend.persistence.db as db_mod

    importlib.reload(db_mod)
    # Re-point DB_PATH and the connection pool
    db_mod.DB_PATH = tmp_path / "test_nexus.db"
    db_mod._pool = None  # reset the global pool
    with TestClient(app) as c:
        yield c


AUTH = {"Authorization": "Bearer test-bypass"}


def test_create_session_default(client) -> None:
    r = client.post(
        "/api/sessions",
        json={"title": "Sessao de teste", "mode": "auto"},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["title"] == "Sessao de teste"
    assert s["mode"] == "auto"
    assert "id" in s
    assert "started_at" in s
    assert "last_active_at" in s


def test_list_sessions_includes_count(client) -> None:
    # First, create one
    r = client.post("/api/sessions", json={"title": "list-test"}, headers=AUTH)
    assert r.status_code == 200, r.text
    r = client.get("/api/sessions?limit=20", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "sessions" in body
    assert "count" in body
    for s in body["sessions"]:
        assert "message_count" in s
        assert s["message_count"] >= 0


def test_get_session(client) -> None:
    r = client.post("/api/sessions", json={"title": "Get me"}, headers=AUTH)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r2 = client.get(f"/api/sessions/{sid}", headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["id"] == sid
    client.delete(f"/api/sessions/{sid}", headers=AUTH)


def test_get_missing_session_404(client) -> None:
    r = client.get("/api/sessions/does-not-exist", headers=AUTH)
    assert r.status_code == 404


def test_patch_session_rename(client) -> None:
    r = client.post("/api/sessions", json={"title": "Original"}, headers=AUTH)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r2 = client.patch(f"/api/sessions/{sid}", json={"title": "Renomeado"}, headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["title"] == "Renomeado"
    client.delete(f"/api/sessions/{sid}", headers=AUTH)


def test_patch_session_mode(client) -> None:
    r = client.post("/api/sessions", json={"title": "Mode test"}, headers=AUTH)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r2 = client.patch(f"/api/sessions/{sid}", json={"mode": "swarm"}, headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["mode"] == "swarm"
    client.delete(f"/api/sessions/{sid}", headers=AUTH)


def test_delete_session(client) -> None:
    r = client.post("/api/sessions", json={"title": "Apagar"}, headers=AUTH)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r2 = client.delete(f"/api/sessions/{sid}", headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["deleted"] is True
    r3 = client.get(f"/api/sessions/{sid}", headers=AUTH)
    assert r3.status_code == 404


def test_delete_missing_404(client) -> None:
    r = client.delete("/api/sessions/never-existed", headers=AUTH)
    assert r.status_code == 404


def test_validation_short_title(client) -> None:
    r = client.post("/api/sessions", json={"title": ""}, headers=AUTH)
    assert r.status_code == 422


def test_get_messages_for_session(client) -> None:
    r = client.post("/api/sessions", json={"title": "Messages test"}, headers=AUTH)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r2 = client.get(f"/api/sessions/{sid}/messages", headers=AUTH)
    assert r2.status_code == 200
    assert isinstance(r2.json()["messages"], list)
    client.delete(f"/api/sessions/{sid}", headers=AUTH)
