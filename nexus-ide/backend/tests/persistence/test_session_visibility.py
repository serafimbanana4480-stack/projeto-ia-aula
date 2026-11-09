"""The session list must show what the database actually holds.

Three defects are pinned here:

* the tool audit fabricated a session row for an unknown session id, so the
  live database grew ghost sessions that showed up in the session list and
  in ``count_active_sessions()``;
* the garbage collector's soft delete was invisible: the persisted status was
  overwritten by a value derived from ``last_active_at`` and the expired
  sessions were still listed;
* deleting a session left its todos behind, because ``todos.session_id``
  carries no foreign key.
"""

from __future__ import annotations

from backend.persistence import db


def test_log_tool_execution_does_not_create_a_session() -> None:
    """An unknown session id must not fabricate a session row."""
    before = db.count_active_sessions()
    listed_before = {row["id"] for row in db.list_sessions()}

    execution_id = db.log_tool_execution(
        session_id="session-that-does-not-exist",
        tool_name="probe",
        args={"a": 1},
        result="ok",
    )

    assert db.count_active_sessions() == before
    assert {row["id"] for row in db.list_sessions()} == listed_before

    with db.get_db() as conn:
        row = conn.execute(
            "SELECT session_id FROM tool_executions WHERE id = ?", (execution_id,)
        ).fetchone()
    assert row is not None
    assert row["session_id"] is None, "an unknown session must be stored as NULL"


def test_log_tool_execution_keeps_a_known_session() -> None:
    """A real session id is still stored on the execution."""
    session = db.create_session(title="Known session")
    execution_id = db.log_tool_execution(
        session_id=session["id"],
        tool_name="probe",
        args={},
        result="ok",
    )
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT session_id FROM tool_executions WHERE id = ?", (execution_id,)
        ).fetchone()
    assert row is not None
    assert row["session_id"] == session["id"]


def test_expired_sessions_are_not_listed() -> None:
    """A soft-deleted session must not show up in the listing."""
    live = db.create_session(title="Live")
    dead = db.create_session(title="Dead")

    assert db.mark_session_expired(dead["id"]) is True

    listed = [row["id"] for row in db.list_sessions()]
    assert live["id"] in listed
    assert dead["id"] not in listed

    # The count and the decorated listing agree with the plain listing.
    assert db.count_sessions() == len(listed)
    decorated = [row["id"] for row in db.list_sessions_with_counts()]
    assert dead["id"] not in decorated
    assert db.count_active_sessions() == len(listed)


def test_session_stats_agrees_with_the_session_list() -> None:
    """``get_session_stats()`` must not contradict the session list."""
    live = db.create_session(title="Live")
    dead = db.create_session(title="Dead")
    db.mark_session_expired(dead["id"])

    listed = db.list_sessions()
    stats = db.get_session_stats()

    assert stats["active"] == len(listed), "the stats must count the listed sessions"
    assert stats["active"] == 1
    assert stats["expired"] == 1
    assert stats["total"] == stats["active"] + stats["expired"]
    assert live["id"] in {row["id"] for row in listed}
    assert dead["id"] not in {row["id"] for row in listed}


def test_delete_session_removes_its_todos() -> None:
    """The todos of a deleted session must not be orphaned."""
    session = db.create_session(title="With todos")
    other = db.create_session(title="Other session")
    db.create_todo(session["id"], "write the docs")
    db.create_todo(session["id"], "ship it")
    db.create_todo(other["id"], "not mine")

    counts = db.delete_session_related_data(session["id"])

    assert counts["todos"] == 2
    assert db.get_session_todos_db(session["id"]) == []
    # The todos of another session are untouched.
    assert len(db.get_session_todos_db(other["id"])) == 1
