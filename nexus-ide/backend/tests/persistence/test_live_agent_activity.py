"""The session panel's agent list during a run that has not answered yet."""

from __future__ import annotations

from backend.persistence.db import (
    create_session,
    get_agent_activity,
    get_db,
    upsert_session_run,
)


def test_running_agent_is_visible_before_any_assistant_message() -> None:
    create_session(session_id="sess-live", title="live")
    upsert_session_run(
        "run-live",
        "sess-live",
        status="running",
        agent="NEXUS",
        phase="act",
    )

    activity = get_agent_activity()

    nexus = next(item for item in activity if item["agent"] == "NEXUS")
    assert nexus["status"] == "active"


def test_stale_running_agent_is_not_shown_as_live() -> None:
    create_session(session_id="sess-old", title="old")
    upsert_session_run(
        "run-old",
        "sess-old",
        status="running",
        agent="NEXUS",
        phase="act",
    )
    with get_db() as conn:
        conn.execute(
            "UPDATE session_runs SET updated_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", "run-old"),
        )

    assert all(item["agent"] != "NEXUS" for item in get_agent_activity())
