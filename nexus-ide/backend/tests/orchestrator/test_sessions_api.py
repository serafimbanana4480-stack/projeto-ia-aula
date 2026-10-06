"""End-to-end tests for the sessions CRUD API.

Verifies:
- Create / list / get / patch / delete
- message_count is correctly returned
- 404 on missing session
- Validation errors on bad input
- Cascade delete (session + messages)
"""

from __future__ import annotations

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.middleware import auth as auth_module  # noqa: E402
from backend.orchestrator.main import app  # noqa: E402


# Override require_auth so tests don't depend on JWT signature secrets
async def _fake_user() -> dict:
    return {"user_id": "test", "email": "t@t"}


async def _other_fake_user() -> dict:
    return {"user_id": "other", "email": "other@t"}


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
    db_mod._connection_pool = None  # reset the global pool
    app.dependency_overrides[auth_module.require_auth] = _fake_user
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(auth_module.require_auth, None)


AUTH = {"Authorization": "Bearer test-bypass"}


def test_session_endpoints_are_scoped_to_the_authenticated_user(client) -> None:
    session = client.post(
        "/api/sessions", json={"title": "private session"}, headers=AUTH
    ).json()
    assert session["user_id"] == "test"

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    assert client.get(f"/api/sessions/{session['id']}", headers=AUTH).status_code == 404
    assert client.get(
        f"/api/sessions/{session['id']}/messages", headers=AUTH
    ).status_code == 404
    assert client.patch(
        f"/api/sessions/{session['id']}",
        json={"title": "tampered"},
        headers=AUTH,
    ).status_code == 404
    assert client.delete(
        f"/api/sessions/{session['id']}", headers=AUTH
    ).status_code == 404
    listed = client.get("/api/sessions", headers=AUTH).json()
    assert listed["sessions"] == []
    assert listed["total"] == 0


def test_tool_retry_requires_session_bound_one_time_confirmation(client, tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from backend.tools.registry import get_tool

    session_id = client.post(
        "/api/sessions", json={"title": "Tool retry"}, headers=AUTH
    ).json()["id"]
    target = tmp_path / "approved-tool-output.txt"
    spec = get_tool("write_file_absolute")
    assert spec is not None
    executions: list[tuple[str, str]] = []

    async def write_for_test(*, path: str, content: str, create_dirs: bool = True) -> dict:
        Path(path).write_text(content, encoding="utf-8")
        executions.append((path, content))
        return {"ok": True, "path": path}

    monkeypatch.setattr(spec, "handler", write_for_test)
    args = {"path": str(target), "content": "approved content"}

    # A legacy or forged client boolean is ignored and cannot cross the gate.
    pending = client.post(
        "/api/tools/execute",
        json={
            "tool_name": "write_file_absolute",
            "args": args,
            "session_id": session_id,
            "confirmed": True,
        },
        headers=AUTH,
    )
    assert pending.status_code == 200, pending.text
    confirmation_id = pending.json()["confirmation_id"]
    assert pending.json()["confirmation_required"] is True
    assert not target.exists()
    assert executions == []

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    assert client.post(
        "/api/tools/confirm",
        json={"confirmation_id": confirmation_id, "approved": True},
        headers=AUTH,
    ).status_code == 404
    client.app.dependency_overrides[auth_module.require_auth] = _fake_user

    approved = client.post(
        "/api/tools/confirm",
        json={"confirmation_id": confirmation_id, "approved": True},
        headers=AUTH,
    )
    assert approved.status_code == 200, approved.text

    changed_args = {**args, "content": "changed after approval"}
    changed = client.post(
        "/api/tools/execute",
        json={
            "tool_name": "write_file_absolute",
            "args": changed_args,
            "session_id": session_id,
            "confirmation_id": confirmation_id,
        },
        headers=AUTH,
    )
    assert changed.status_code == 409
    assert executions == []

    executed = client.post(
        "/api/tools/execute",
        json={
            "tool_name": "write_file_absolute",
            "args": args,
            "session_id": session_id,
            "confirmation_id": confirmation_id,
        },
        headers=AUTH,
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["ok"] is True
    assert target.read_text(encoding="utf-8") == "approved content"
    assert executions == [(str(target), "approved content")]

    replayed = client.post(
        "/api/tools/execute",
        json={
            "tool_name": "write_file_absolute",
            "args": args,
            "session_id": session_id,
            "confirmation_id": confirmation_id,
        },
        headers=AUTH,
    )
    assert replayed.status_code == 409
    assert len(executions) == 1


def test_learned_skills_are_scoped_to_their_owner(client, tmp_path, monkeypatch) -> None:
    from backend.core import skills_store as skills_store_module
    from backend.core.skill_runtime import select_skills
    from backend.core.skills_store import SkillsStore
    from backend.orchestrator.routes import skills as skills_routes

    skill_dir = tmp_path / "learned-skills"
    monkeypatch.setattr(skills_store_module, "SKILLS_DIR", skill_dir)
    monkeypatch.setattr(skills_store_module, "SKILLS_INDEX", skill_dir / "_index.json")
    store = SkillsStore()
    monkeypatch.setattr(SkillsStore, "_instance", store)
    monkeypatch.setattr(skills_routes, "_store", store)

    created = client.post(
        "/api/skills",
        json={
            "name": "Private audit routine",
            "type": "workflow",
            "description": "Owner-only audit procedure",
            "trigger_pattern": "private audit",
            "steps": ["Inspect the owner's project"],
            "auto_apply": True,
        },
        headers=AUTH,
    )
    assert created.status_code == 200, created.text
    skill_id = created.json()["id"]
    assert client.get("/api/skills", headers=AUTH).json()["count"] == 1
    assert select_skills(
        "private audit", tmp_path, include_memory=True, user_id="test"
    )["skills"][0]["name"] == "Private audit routine"

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    assert client.get("/api/skills", headers=AUTH).json()["count"] == 0
    assert client.get(f"/api/skills/{skill_id}", headers=AUTH).status_code == 404
    assert client.put(
        f"/api/skills/{skill_id}",
        json={"record_use": True, "success": False},
        headers=AUTH,
    ).status_code == 404
    assert client.delete(f"/api/skills/{skill_id}", headers=AUTH).json()["status"] == "not_found"
    assert select_skills(
        "private audit", tmp_path, include_memory=True, user_id="other"
    )["skills"] == []

    client.app.dependency_overrides[auth_module.require_auth] = _fake_user
    assert client.get(f"/api/skills/{skill_id}", headers=AUTH).status_code == 200


def test_durable_todos_are_read_without_mutating_storage(client, tmp_path, monkeypatch) -> None:
    import asyncio

    from backend.tools import todo_tools

    monkeypatch.setattr(todo_tools, "TODOS_DIR", tmp_path / "todos")
    session_id = client.post("/api/sessions", json={"title": "Tasks"}, headers=AUTH).json()["id"]
    result = asyncio.run(todo_tools.todo_write(
        session_id=session_id, operation="set_all", items=[{"content": "Verify the patch"}]
    ))
    assert result["ok"] is True
    path = todo_tools.TODOS_DIR / f"{session_id}.json"
    before = path.read_bytes()

    response = client.get(f"/api/sessions/{session_id}/todos", headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json()["session_id"] == session_id
    assert response.json()["todos"][0]["content"] == "Verify the patch"
    assert response.json()["counts"]["pending"] == 1
    assert path.read_bytes() == before


def test_corrupt_todos_are_preserved_and_reported(client, tmp_path, monkeypatch) -> None:
    from backend.tools import todo_tools

    monkeypatch.setattr(todo_tools, "TODOS_DIR", tmp_path)
    session_id = client.post("/api/sessions", json={"title": "Corrupt"}, headers=AUTH).json()["id"]
    path = tmp_path / f"{session_id}.json"
    path.write_text("broken data", encoding="utf-8")
    response = client.get(f"/api/sessions/{session_id}/todos", headers=AUTH)
    assert response.status_code == 409
    assert path.read_text(encoding="utf-8") == "broken data"
    assert client.get("/api/sessions/missing/todos", headers=AUTH).status_code == 404


def test_skill_catalog_uses_the_agent_discovery_for_the_resolved_project(
    client, tmp_path, monkeypatch
) -> None:
    from backend.core import skill_runtime

    calls = []
    expected = [{"name": "project-review", "source": "file", "status": "active"}]

    def discover(project_path, *, include_memory, user_id):
        calls.append((project_path, include_memory, user_id))
        return expected

    monkeypatch.setattr(skill_runtime, "list_skill_summaries", discover)
    response = client.get("/api/skills/catalog", params={"project_path": str(tmp_path)}, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json() == {"skills": expected, "count": 1, "source": "runtime_catalog"}
    assert calls == [(str(tmp_path.resolve()), True, "test")]


def test_skill_catalog_rejects_invalid_projects_before_discovery(client, tmp_path, monkeypatch) -> None:
    from backend.core import skill_runtime

    def unexpected_discovery(*args, **kwargs):
        raise AssertionError("Invalid paths must never reach skill discovery")

    monkeypatch.setattr(skill_runtime, "list_skill_summaries", unexpected_discovery)
    response = client.get("/api/skills/catalog", params={"project_path": str(tmp_path / "missing")}, headers=AUTH)
    assert response.status_code == 400


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


def test_list_sessions_paginates_without_repeating_rows(client) -> None:
    for title in ("page-a", "page-b", "page-c", "page-d", "page-e"):
        response = client.post("/api/sessions", json={"title": title}, headers=AUTH)
        assert response.status_code == 200, response.text

    first = client.get("/api/sessions?limit=2&offset=0", headers=AUTH)
    second = client.get("/api/sessions?limit=2&offset=2", headers=AUTH)
    assert first.status_code == second.status_code == 200
    first_body, second_body = first.json(), second.json()
    first_ids = {session["id"] for session in first_body["sessions"]}
    second_ids = {session["id"] for session in second_body["sessions"]}
    assert len(first_ids) == len(second_ids) == 2
    assert first_ids.isdisjoint(second_ids)
    assert first_body["total"] == second_body["total"] == 5
    assert second_body["offset"] == 2


def test_search_sessions_finds_message_text_and_labels_match_type(client) -> None:
    from backend.persistence.db import add_message, create_session

    titled = create_session(title="Release checklist", user_id="test")
    message_match = create_session(title="Untitled conversation", user_id="test")
    add_message(
        message_match["id"],
        "user",
        "The unique search marker is cobalt-harbor in this conversation.",
    )

    response = client.get(
        "/api/sessions/search?q=cobalt-harbor", headers=AUTH
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["sessions"][0]["id"] == message_match["id"]
    assert body["sessions"][0]["match_type"] == "message"
    assert "cobalt-harbor" in body["sessions"][0]["snippet"]

    title_response = client.get("/api/sessions/search?q=Release", headers=AUTH)
    assert title_response.status_code == 200, title_response.text
    assert title_response.json()["sessions"][0]["id"] == titled["id"]
    assert title_response.json()["sessions"][0]["match_type"] == "title"


def test_message_history_cursor_pages_preserve_order_and_reject_foreign_cursor(client) -> None:
    from backend.persistence.db import add_message, create_session

    session = create_session(title="Long conversation", user_id="test")
    other = create_session(title="Other conversation", user_id="test")
    inserted = [
        add_message(session["id"], "user", f"turn-{index}")
        for index in range(5)
    ]

    first = client.get(
        f"/api/sessions/{session['id']}/messages?limit=2", headers=AUTH
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert [message["id"] for message in first_body["messages"]] == [
        inserted[3]["id"], inserted[4]["id"]
    ]
    assert first_body["has_more"] is True
    assert first_body["next_cursor"] == inserted[3]["id"]

    second = client.get(
        f"/api/sessions/{session['id']}/messages?limit=2&before_id={first_body['next_cursor']}",
        headers=AUTH,
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    third = client.get(
        f"/api/sessions/{session['id']}/messages?limit=2&before_id={second_body['next_cursor']}",
        headers=AUTH,
    )
    assert third.status_code == 200, third.text
    assert third.json()["has_more"] is False

    all_ids = [
        message["id"]
        for body in (third.json(), second_body, first_body)
        for message in body["messages"]
    ]
    assert all_ids == [message["id"] for message in inserted]
    foreign = client.get(
        f"/api/sessions/{session['id']}/messages?before_id={other['id']}",
        headers=AUTH,
    )
    assert foreign.status_code == 400


def test_message_history_api_round_trips_more_than_five_hundred_rows(client) -> None:
    """A long transcript stays complete across bounded, tied-timestamp pages."""
    from backend.persistence.db import create_session, get_db

    session = create_session(title="Very long conversation", user_id="test")
    expected_ids = [f"long-message-{index:04d}" for index in range(523)]
    shared_timestamp = "2026-01-01T00:00:00.000Z"
    with get_db() as conn:
        conn.executemany(
            """INSERT INTO messages (id, session_id, role, content, created_at)
               VALUES (?, ?, 'user', ?, ?)""",
            [
                (message_id, session["id"], f"turn-{index:04d}", shared_timestamp)
                for index, message_id in enumerate(expected_ids)
            ],
        )

    pages: list[list[dict[str, object]]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        query = "?limit=100" + (f"&before_id={cursor}" if cursor else "")
        response = client.get(
            f"/api/sessions/{session['id']}/messages{query}", headers=AUTH
        )
        assert response.status_code == 200, response.text
        body = response.json()
        page = body["messages"]
        pages.append(page)
        assert body["count"] == len(page)
        assert len(page) <= 100
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break

        next_cursor = body["next_cursor"]
        assert isinstance(next_cursor, str) and next_cursor
        assert next_cursor not in seen_cursors
        assert next_cursor != cursor
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    chronological_ids = [
        str(message["id"])
        for page in reversed(pages)
        for message in page
    ]
    assert len(pages) == 6
    assert chronological_ids == expected_ids
    assert len(set(chronological_ids)) == len(expected_ids)


def test_run_history_limit_can_reach_runs_older_than_default_page(client) -> None:
    from backend.persistence.db import create_session, upsert_session_run

    session = create_session(title="Long run history", user_id="test")
    for index in range(25):
        upsert_session_run(
            f"run-{index:02d}",
            session["id"],
            status="completed",
            finished=True,
        )

    default_page = client.get(
        f"/api/sessions/{session['id']}/runs", headers=AUTH
    )
    expanded_page = client.get(
        f"/api/sessions/{session['id']}/runs?limit=100", headers=AUTH
    )

    assert default_page.status_code == 200, default_page.text
    assert expanded_page.status_code == 200, expanded_page.text
    assert len(default_page.json()["runs"]) == 20
    assert len(expanded_page.json()["runs"]) == 25


def test_run_history_pages_beyond_one_hundred_without_duplicates(client) -> None:
    from backend.persistence.db import create_session, upsert_session_run

    session = create_session(title="Paged run history", user_id="test")
    expected_ids = [f"paged-run-{index:03d}" for index in range(105)]
    for run_id in expected_ids:
        upsert_session_run(run_id, session["id"], status="completed", finished=True)

    first_page = client.get(
        f"/api/sessions/{session['id']}/runs?limit=100&offset=0", headers=AUTH
    )
    last_page = client.get(
        f"/api/sessions/{session['id']}/runs?limit=100&offset=100", headers=AUTH
    )

    assert first_page.status_code == 200, first_page.text
    assert last_page.status_code == 200, last_page.text
    assert first_page.json()["count"] == 100
    assert first_page.json()["has_more"] is True
    assert first_page.json()["next_offset"] == 100
    assert last_page.json()["count"] == 5
    assert last_page.json()["has_more"] is False
    assert last_page.json()["next_offset"] == 105
    first_ids = [run["id"] for run in first_page.json()["runs"]]
    last_ids = [run["id"] for run in last_page.json()["runs"]]
    assert len(set(first_ids + last_ids)) == 105
    assert set(first_ids + last_ids) == set(expected_ids)


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
