"""Focused persistence tests for correlated durable execution runs."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta


def _make_session() -> str:
    from backend.persistence.db import create_session

    create_session(None, "Persistence test", "auto", "session-persistence")
    return "session-persistence"


def test_upsert_round_trips_execution_envelope_fields() -> None:
    from backend.persistence.db import upsert_session_run

    session_id = _make_session()
    row = upsert_session_run(
        "run-persistence",
        session_id,
        mission_id="mission-1",
        correlation_id="corr-1",
        mode="chat",
        execution_state="running",
        provider="openrouter",
        model="free-model",
        error_category="none",
        retry_after=12,
        evidence=[{"verified": True, "kind": "tests"}],
    )

    assert row is not None
    assert row["mission_id"] == "mission-1"
    assert row["correlation_id"] == "corr-1"
    assert row["mode"] == "chat"
    assert row["execution_state"] == "running"
    assert row["provider"] == "openrouter"
    assert row["model"] == "free-model"
    assert row["error_category"] == "none"
    assert row["retry_after"] == 12
    assert row["evidence"] == [{"verified": True, "kind": "tests"}]


def test_terminal_update_sets_finished_at_and_correlation_lookup() -> None:
    from backend.persistence.db import (
        get_runs_by_correlation,
        mark_run_terminal,
        upsert_session_run,
    )

    session_id = _make_session()
    upsert_session_run("run-terminal", session_id, correlation_id="corr-terminal")
    row = mark_run_terminal(
        "run-terminal",
        status="completed",
        evidence=[{"verified": True}],
    )

    assert row is not None
    assert row["status"] == "completed"
    assert row["execution_state"] == "completed"
    assert row["finished_at"]
    assert any(item["id"] == "run-terminal" for item in get_runs_by_correlation("corr-terminal"))


def test_recover_interrupted_runs_marks_stale_running_rows() -> None:
    from backend.persistence.db import recover_interrupted_runs, upsert_session_run
    from backend.persistence.db import DB_PATH

    session_id = _make_session()
    upsert_session_run("run-stale", session_id, execution_state="running")
    stale = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE session_runs SET updated_at = ? WHERE id = ?", (stale, "run-stale"))

    recovered = recover_interrupted_runs(max_age_seconds=1)

    assert [item["id"] for item in recovered] == ["run-stale"]
    assert recovered[0]["status"] == "interrupted"
    assert recovered[0]["execution_state"] == "interrupted"
    assert recovered[0]["finished_at"]



def test_recovery_does_not_rewrite_terminal_rows() -> None:
    from backend.persistence.db import DB_PATH, mark_run_terminal, recover_interrupted_runs
    from backend.persistence.db import upsert_session_run

    session_id = _make_session()
    upsert_session_run("run-completed", session_id, execution_state="running")
    mark_run_terminal("run-completed", status="completed")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE session_runs SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00Z", "run-completed"),
        )

    assert recover_interrupted_runs(max_age_seconds=1) == []