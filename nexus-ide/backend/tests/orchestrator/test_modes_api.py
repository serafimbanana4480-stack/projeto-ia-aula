"""Tenant-isolation contracts for GET /api/db/stats.

The stats endpoint is authenticated (``require_auth``), not public and not
admin-only, so every row it returns has to be the caller's own. These tests pin
that: a session created by user A must not appear in user B's stats, no
ownership column may ride along in the payload, and the message aggregate must
count only the caller's sessions.
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
    """Function-scoped client with a fresh, isolated SQLite database."""
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


def test_db_stats_never_returns_another_users_session(client) -> None:
    """A session is visible only to the user who created it."""
    mine = client.post(
        "/api/sessions", json={"title": "tenant A private plan"}, headers=AUTH
    ).json()

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    theirs = client.post(
        "/api/sessions", json={"title": "tenant B private plan"}, headers=AUTH
    ).json()

    client.app.dependency_overrides[auth_module.require_auth] = _fake_user
    my_stats = client.get("/api/db/stats", headers=AUTH)
    assert my_stats.status_code == 200, my_stats.text
    my_sessions = my_stats.json()["recent_sessions"]
    assert [row["id"] for row in my_sessions] == [mine["id"]]
    assert [row["title"] for row in my_sessions] == ["tenant A private plan"]
    # The other tenant's row is gone, ownership column included.
    assert all(row["id"] != theirs["id"] for row in my_sessions)
    assert "tenant B private plan" not in my_stats.text
    assert "other" not in [
        value
        for row in my_sessions
        for value in row.values()
        if isinstance(value, str)
    ]

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    their_stats = client.get("/api/db/stats", headers=AUTH)
    assert their_stats.status_code == 200, their_stats.text
    assert [row["id"] for row in their_stats.json()["recent_sessions"]] == [theirs["id"]]


def test_db_stats_session_rows_carry_no_ownership_metadata(client) -> None:
    """The useful presentation fields stay; the raw tenant columns do not."""
    from backend.persistence.db import add_message, get_db

    session_id = client.post("/api/sessions", json={"title": "Stats row"}, headers=AUTH).json()["id"]
    add_message(session_id, "user", "hello")
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET context_json = ? WHERE id = ?",
            ('{"secret": "cobalt-harbor"}', session_id),
        )

    row = client.get("/api/db/stats", headers=AUTH).json()["recent_sessions"][0]

    assert row["id"] == session_id
    assert row["title"] == "Stats row"
    assert row["message_count"] == 1
    assert row["started_at"] and row["last_active_at"]
    for leaked in ("user_id", "context_json"):
        assert leaked not in row
    assert "cobalt-harbor" not in str(row)


def test_db_stats_message_statistics_count_only_the_callers_messages(client) -> None:
    """The aggregate is honest and scoped, not global and not faked."""
    from backend.persistence.db import add_message

    mine = client.post("/api/sessions", json={"title": "Mine"}, headers=AUTH).json()["id"]
    for turn in range(3):
        add_message(mine, "user" if turn % 2 == 0 else "assistant", f"mine-{turn}")

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    theirs = client.post("/api/sessions", json={"title": "Theirs"}, headers=AUTH).json()["id"]
    add_message(theirs, "user", "theirs-0")
    add_message(theirs, "assistant", "theirs-1")

    client.app.dependency_overrides[auth_module.require_auth] = _fake_user
    stats = client.get("/api/db/stats", headers=AUTH).json()["message_stats"]

    assert stats["total_messages"] == 3
    assert stats["sessions_with_messages"] == 1
    assert stats["user_messages"] == 2
    assert stats["assistant_messages"] == 1

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    other_stats = client.get("/api/db/stats", headers=AUTH).json()["message_stats"]
    assert other_stats["total_messages"] == 2
    assert other_stats["user_messages"] == 1
    assert other_stats["assistant_messages"] == 1


def test_db_stats_recent_tool_executions_are_the_callers_only(client) -> None:
    """`tool_executions.session_id` joins to `sessions.user_id`: no global list."""
    from backend.persistence.db import log_tool_execution

    mine = client.post("/api/sessions", json={"title": "Mine"}, headers=AUTH).json()["id"]
    log_tool_execution(
        mine, "tenant_a_only_tool", {"path": "a"}, {"ok": True}, duration_ms=11
    )

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    theirs = client.post("/api/sessions", json={"title": "Theirs"}, headers=AUTH).json()["id"]
    log_tool_execution(
        theirs, "tenant_b_secret_tool", {"path": "b"}, {"ok": True}, duration_ms=99
    )

    client.app.dependency_overrides[auth_module.require_auth] = _fake_user
    response = client.get("/api/db/stats", headers=AUTH)
    assert response.status_code == 200, response.text
    rows = response.json()["recent_tool_executions"]

    assert [row["tool_name"] for row in rows] == ["tenant_a_only_tool"]
    assert set(rows[0]) == {"tool_name", "success", "duration_ms", "created_at"}
    # The other tenant's tool name, argument and timing are nowhere in the body.
    assert "tenant_b_secret_tool" not in response.text

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    other_response = client.get("/api/db/stats", headers=AUTH)
    other_rows = other_response.json()["recent_tool_executions"]
    assert [row["tool_name"] for row in other_rows] == ["tenant_b_secret_tool"]
    assert "tenant_a_only_tool" not in other_response.text


def test_db_stats_recent_routing_decisions_are_the_callers_only(client) -> None:
    """`routing_decisions.session_id` joins to `sessions.user_id` as well."""
    from backend.persistence.db import log_routing_decision

    mine = client.post("/api/sessions", json={"title": "Mine"}, headers=AUTH).json()["id"]
    log_routing_decision(
        mine,
        "tenant a prompt",
        tier_chosen="deep",
        reason="tenant-a-route",
        confidence=0.9,
        decision_ms=5,
    )

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    theirs = client.post("/api/sessions", json={"title": "Theirs"}, headers=AUTH).json()["id"]
    log_routing_decision(
        theirs,
        "tenant b prompt",
        tier_chosen="fast",
        reason="tenant-b-secret-route",
        confidence=0.1,
        decision_ms=77,
    )

    client.app.dependency_overrides[auth_module.require_auth] = _fake_user
    response = client.get("/api/db/stats", headers=AUTH)
    assert response.status_code == 200, response.text
    rows = response.json()["recent_routing_decisions"]

    assert [row["reason"] for row in rows] == ["tenant-a-route"]
    assert [row["tier_chosen"] for row in rows] == ["deep"]
    assert set(rows[0]) == {
        "tier_chosen",
        "reason",
        "confidence",
        "decision_ms",
        "created_at",
    }
    # The other tenant's tier, reason and decision time are nowhere in the body.
    assert "tenant-b-secret-route" not in response.text

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    other_response = client.get("/api/db/stats", headers=AUTH)
    other_rows = other_response.json()["recent_routing_decisions"]
    assert [row["reason"] for row in other_rows] == ["tenant-b-secret-route"]
    assert "tenant-a-route" not in other_response.text


def test_db_stats_table_counts_are_tenant_scoped(client) -> None:
    """Scoped where an owner column exists; explicitly unknown where none does."""
    from backend.persistence.db import add_message

    mine = client.post("/api/sessions", json={"title": "Mine"}, headers=AUTH).json()["id"]
    add_message(mine, "user", "mine-0")
    add_message(mine, "assistant", "mine-1")

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    theirs = client.post("/api/sessions", json={"title": "Theirs"}, headers=AUTH).json()["id"]
    for turn in range(5):
        add_message(theirs, "user", f"theirs-{turn}")

    client.app.dependency_overrides[auth_module.require_auth] = _fake_user
    counts = client.get("/api/db/stats", headers=AUTH).json()["table_counts"]

    # The key set the frontend renders is unchanged...
    assert set(counts) == {
        "users",
        "projects",
        "sessions",
        "messages",
        "tool_executions",
        "routing_decisions",
        "proposed_changes",
    }
    # ...the scopable ones count this tenant only (1 session / 2 messages, not
    # 2 sessions / 7 messages), ...
    assert counts["sessions"] == 1
    assert counts["messages"] == 2
    # ...and the two tables with no owner column report nothing rather than the
    # global figure, which would disclose the tenant count and the project count.
    assert counts["users"] is None
    assert counts["projects"] is None
    for table in ("tool_executions", "routing_decisions", "proposed_changes"):
        assert counts[table] == 0


def test_db_stats_pending_changes_count_only_the_callers(client) -> None:
    """`proposed_changes` is reachable from `sessions.user_id`, so it is scoped."""
    from backend.persistence.db import get_db

    mine = client.post("/api/sessions", json={"title": "Mine"}, headers=AUTH).json()["id"]
    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    theirs = client.post("/api/sessions", json={"title": "Theirs"}, headers=AUTH).json()["id"]
    with get_db() as conn:
        conn.execute(
            "INSERT INTO proposed_changes (id, session_id, file_path, operation) "
            "VALUES (?, ?, ?, 'modify')",
            ("pc-mine", mine, "a.py"),
        )
        conn.execute(
            "INSERT INTO proposed_changes (id, session_id, file_path, operation) "
            "VALUES (?, ?, ?, 'modify')",
            ("pc-theirs", theirs, "b.py"),
        )

    client.app.dependency_overrides[auth_module.require_auth] = _other_fake_user
    theirs_stats = client.get("/api/db/stats", headers=AUTH).json()
    client.app.dependency_overrides[auth_module.require_auth] = _fake_user
    my_stats = client.get("/api/db/stats", headers=AUTH).json()

    assert my_stats["pending_changes"] == 1
    assert theirs_stats["pending_changes"] == 1


def test_db_stats_response_shape_is_unchanged(client) -> None:
    """The frontend contract depends on these keys existing."""
    body = client.get("/api/db/stats", headers=AUTH).json()

    assert set(body) == {
        "table_counts",
        "message_stats",
        "recent_sessions",
        "pending_changes",
        "recent_tool_executions",
        "recent_routing_decisions",
    }
    assert set(body["message_stats"]) == {
        "total_messages",
        "sessions_with_messages",
        "user_messages",
        "assistant_messages",
        "tokens_in_total",
        "tokens_out_total",
        "cost_usd_total",
        "avg_latency_ms",
        "last_message_at",
    }