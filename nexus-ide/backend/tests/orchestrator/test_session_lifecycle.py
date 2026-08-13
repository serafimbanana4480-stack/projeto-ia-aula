"""Tests for session lifecycle management (garbage collection).

Covers:
- SessionLifecycleManager core logic
- DB-level GC functions
- Admin GC endpoints
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.middleware import auth as auth_module  # noqa: E402
from backend.orchestrator.main import app  # noqa: E402


# Override require_auth and require_admin so tests don't need JWT
async def _fake_user() -> dict:
    return {"user_id": "test", "email": "admin@nexus-ide.com"}


@pytest.fixture
def client(tmp_path):
    """Function-scoped client with a fresh, isolated SQLite database."""
    import importlib
    import os

    os.environ["NEXUS_DB_PATH"] = str(tmp_path / "test_nexus.db")
    import backend.persistence.db as db_mod

    importlib.reload(db_mod)
    db_mod.DB_PATH = tmp_path / "test_nexus.db"
    # Reset pool so get_db() creates a new pool for the fresh DB
    import backend.persistence.db as _db_reload

    _db_reload._connection_pool = None
    app.dependency_overrides[auth_module.require_auth] = _fake_user
    app.dependency_overrides[auth_module.require_admin] = _fake_user
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(auth_module.require_auth, None)
        app.dependency_overrides.pop(auth_module.require_admin, None)


AUTH = {"Authorization": "Bearer test-bypass"}


# ── DB-level tests ──────────────────────────────────────────────────────


def test_ensure_session_gc_schema(client) -> None:
    """Verify that the schema migration adds status and expired_at columns."""
    from backend.persistence.db import (
        _ensure_session_gc_schema,
        get_db,
    )

    _ensure_session_gc_schema()
    with get_db() as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    assert "status" in cols
    assert "expired_at" in cols


def test_mark_session_expired(client) -> None:
    """Verify that a session can be soft-deleted (marked expired)."""
    from backend.persistence.db import (
        create_session,
        get_session,
        mark_session_expired,
    )

    session = create_session(title="Expire me")
    sid = session["id"]

    # Initially not expired
    updated = get_session(sid)
    assert updated is not None
    if "status" in updated:
        assert updated["status"] in ("active", None)

    # Mark as expired
    assert mark_session_expired(sid) is True

    # Verify
    expired = get_session(sid)
    assert expired is not None
    assert expired.get("status") == "expired"
    assert expired.get("expired_at") is not None


def test_list_expired_sessions(client) -> None:
    """Verify list_expired_sessions finds stale sessions."""
    from backend.persistence.db import (
        _now_iso_minus_hours,
        create_session,
        get_db,
    )

    # Create a session, then manually set its last_active_at far in the past
    s = create_session(title="Stale")
    sid = s["id"]
    old_time = _now_iso_minus_hours(48)
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET last_active_at = ? WHERE id = ?",
            (old_time, sid),
        )

    # Should show up as expired (TTL=1 hour)
    from backend.persistence.db import list_expired_sessions

    expired = list_expired_sessions(ttl_hours=1)
    ids = [e["id"] for e in expired]
    assert sid in ids


def test_delete_session_related_data(client) -> None:
    """Verify that FK-referenced data is removed."""
    from backend.persistence.db import (
        _new_id,
        create_session,
        delete_session_related_data,
        get_db,
        log_tool_execution,
        propose_change,
    )

    session = create_session(title="Clean me")
    sid = session["id"]

    # Insert messages directly (add_message has a pre-existing schema issue
    # in test DBs with a missing cost_usd column)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)",
            (_new_id(), sid, "user", "hello"),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)",
            (_new_id(), sid, "assistant", "world"),
        )

    # Log tool execution
    log_tool_execution(session_id=sid, tool_name="test", args={}, result="ok")

    # Propose a change
    propose_change(session_id=sid, project_id=None, file_path="/test.py", operation="modify")

    # Delete related data
    counts = delete_session_related_data(sid)
    assert counts["messages"] >= 2
    assert counts["tool_executions"] >= 1


def test_hard_delete_expired_sessions(client) -> None:
    """Verify hard-delete removes old expired sessions."""
    from backend.persistence.db import (
        create_session,
        get_db,
        get_session,
        hard_delete_expired_sessions,
        mark_session_expired,
    )

    s = create_session(title="Hard delete candidate")
    sid = s["id"]
    mark_session_expired(sid)

    # Manually set expired_at to 10 days ago so it qualifies for hard-delete
    past = (datetime.now(UTC) - timedelta(days=10)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with get_db() as conn:
        conn.execute("UPDATE sessions SET expired_at = ? WHERE id = ?", (past, sid))

    deleted = hard_delete_expired_sessions(before_days=7)
    assert sid in deleted
    assert get_session(sid) is None


def test_get_session_stats(client) -> None:
    """Verify get_session_stats returns correct counters."""
    from backend.persistence.db import (
        create_session,
        get_session_stats,
        mark_session_expired,
    )

    stats = get_session_stats()
    assert "active" in stats
    assert "expired" in stats
    assert "total" in stats

    before = stats["total"]

    # Create a session
    s = create_session(title="Stats test")
    after_create = get_session_stats()
    assert after_create["total"] == before + 1

    # Mark it expired
    mark_session_expired(s["id"])
    after_expire = get_session_stats()
    assert after_expire["expired"] >= 1


# ── SessionLifecycleManager tests ───────────────────────────────────────


def test_session_lifecycle_manager_init() -> None:
    """Verify default init from settings."""
    from backend.orchestrator.session_lifecycle import SessionLifecycleManager

    manager = SessionLifecycleManager(event_bus=None)
    assert manager.ttl_hours == 24  # default from settings
    assert manager.gc_interval_minutes == 60
    assert manager.running is False


@pytest.mark.asyncio
async def test_session_lifecycle_manager_start_stop() -> None:
    """Verify background loop can be started and stopped."""
    from backend.orchestrator.session_lifecycle import SessionLifecycleManager

    manager = SessionLifecycleManager(event_bus=None)
    assert manager.running is False
    manager.start()
    assert manager.running is True
    await manager.stop()
    assert manager.running is False


@pytest.mark.asyncio
async def test_session_lifecycle_run_gc(client) -> None:
    """Verify a full GC cycle works end-to-end."""
    from backend.orchestrator.events import EventBus, EventType, OrchestratorEvent
    from backend.orchestrator.session_lifecycle import SessionLifecycleManager
    from backend.persistence import db as db_mod

    # Create a stale session
    s = db_mod.create_session(title="GC target")
    sid = s["id"]
    old = db_mod._now_iso_minus_hours(48)
    with db_mod.get_db() as conn:
        conn.execute(
            "UPDATE sessions SET last_active_at = ? WHERE id = ?",
            (old, sid),
        )

    event_bus = EventBus()
    collected_events = []

    async def collect(event: OrchestratorEvent) -> None:
        collected_events.append(event)

    await event_bus.subscribe(EventType.SESSION_CLEANUP_COMPLETED.value, collect)

    manager = SessionLifecycleManager(event_bus=event_bus, ttl_hours=1, gc_interval_minutes=999)
    report = await manager.run_gc(allow_destructive=True)

    assert sid in report["expired_sessions"]
    assert "expired_data_counts" in report
    assert "stats" in report

    # Verify event was published
    assert len(collected_events) == 1
    assert collected_events[0].event_type == EventType.SESSION_CLEANUP_COMPLETED
    assert sid in collected_events[0].data.get("expired_sessions", [])


@pytest.mark.asyncio
async def test_background_gc_inventory_does_not_delete_stale_sessions(client) -> None:
    """Default/background GC must never delete user conversation data."""
    from backend.orchestrator.session_lifecycle import SessionLifecycleManager
    from backend.persistence import db as db_mod

    session = db_mod.create_session(title="Preserve me")
    sid = session["id"]
    with db_mod.get_db() as conn:
        conn.execute(
            "UPDATE sessions SET last_active_at = ? WHERE id = ?",
            (db_mod._now_iso_minus_hours(48), sid),
        )

    report = await SessionLifecycleManager(event_bus=None, ttl_hours=1).run_gc()

    assert report["cleanup_skipped"] is True
    assert sid in report["expired_session_candidates"]
    assert db_mod.get_session(sid) is not None


def test_cleanup_temporary_files(client, tmp_path) -> None:
    """Verify temporary files older than 24h are cleaned up."""
    from backend.orchestrator.session_lifecycle import SessionLifecycleManager

    temp_dir = tmp_path / "temp"
    manager = SessionLifecycleManager(event_bus=None, temp_dir=temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Create a fresh file (should NOT be cleaned)
    fresh_file = temp_dir / "fresh.txt"
    fresh_file.write_text("fresh content")

    # Create an old file (should be cleaned)
    old_file = temp_dir / "old.txt"
    old_file.write_text("old content")
    # Set mtime to 48 hours ago
    old_mtime = time.time() - 172800
    os.utime(str(old_file), (old_mtime, old_mtime))

    removed, freed = manager._cleanup_temporary_files()
    assert removed >= 1
    assert freed > 0
    assert fresh_file.exists()  # fresh file should survive
    assert not old_file.exists()  # old file should be gone

    # Cleanup
    fresh_file.unlink(missing_ok=True)


# ── Admin endpoint tests ────────────────────────────────────────────────


def test_admin_gc_stats_endpoint(client) -> None:
    """GET /api/admin/gc/stats returns session stats without error."""
    from backend.orchestrator.session_lifecycle import SessionLifecycleManager

    manager = SessionLifecycleManager(event_bus=None)
    # Inject a mock manager so the endpoint can find it
    import backend.orchestrator.main as main_mod

    main_mod.app.state.session_lifecycle = manager

    r = client.get("/api/admin/gc/stats", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert "stats" in body
    assert "active" in body["stats"]
    assert "total" in body["stats"]


def test_admin_gc_run_endpoint(client) -> None:
    """POST /api/admin/gc/run returns a successful report."""
    from backend.orchestrator.session_lifecycle import SessionLifecycleManager

    manager = SessionLifecycleManager(event_bus=None)
    import backend.orchestrator.main as main_mod

    main_mod.app.state.session_lifecycle = manager

    r = client.post("/api/admin/gc/run", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert "report" in body
    assert "expired_sessions" in body["report"]
    assert "stats" in body["report"]


def test_admin_gc_without_auth_returns_401(client) -> None:
    """Verify unauthenticated requests are rejected."""
    auth_override = app.dependency_overrides.pop(auth_module.require_auth, None)
    admin_override = app.dependency_overrides.pop(auth_module.require_admin, None)
    try:
        r = client.get("/api/admin/gc/stats")
        assert r.status_code == 401
    finally:
        if auth_override is not None:
            app.dependency_overrides[auth_module.require_auth] = auth_override
        if admin_override is not None:
            app.dependency_overrides[auth_module.require_admin] = admin_override


def test_admin_gc_endpoint_no_manager(client) -> None:
    """Verify 503 when no lifecycle manager is available."""
    import backend.orchestrator.main as main_mod

    # Remove the manager from app state
    old = main_mod.app.state.session_lifecycle
    main_mod.app.state.session_lifecycle = None
    r = client.get("/api/admin/gc/stats", headers=AUTH)
    assert r.status_code == 503
    main_mod.app.state.session_lifecycle = old
