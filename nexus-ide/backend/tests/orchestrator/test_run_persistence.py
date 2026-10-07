"""Focused persistence tests for correlated durable execution runs."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest


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


def test_terminal_upsert_without_checkpoint_preserves_durable_progress() -> None:
    import json

    from backend.persistence.db import upsert_session_run

    session_id = _make_session()
    checkpoint = {"cycles": 3, "changed_files": ["src/app.py"]}
    usage = {"total_tokens": 128}

    upsert_session_run(
        "run-checkpoint-preserved",
        session_id,
        checkpoint=checkpoint,
        usage=usage,
    )
    final = upsert_session_run(
        "run-checkpoint-preserved",
        session_id,
        status="completed",
        finished=True,
    )

    assert final is not None
    assert json.loads(final["checkpoint_json"]) == checkpoint
    assert json.loads(final["usage_json"]) == usage


def test_messages_retain_run_links_and_identical_assistant_answers() -> None:
    from backend.persistence.db import add_message, get_messages, upsert_session_run

    session_id = _make_session()
    upsert_session_run("run-answer-a", session_id, execution_state="completed")
    upsert_session_run("run-answer-b", session_id, execution_state="completed")
    add_message(session_id, "assistant", "Done", run_id="run-answer-a")
    add_message(session_id, "assistant", "Done", run_id="run-answer-b")

    answers = [
        message for message in get_messages(session_id) if message.get("role") == "assistant"
    ]

    assert [message["run_id"] for message in answers] == ["run-answer-a", "run-answer-b"]


def test_primary_run_persists_user_prompt_before_stream_recovery() -> None:
    from types import SimpleNamespace

    from backend.orchestrator.routes.chat_primary import _start_primary_run
    from backend.persistence.db import get_messages

    session_id = _make_session()
    decision = SimpleNamespace(to_dict=lambda: {"lane": "primary"})

    _start_primary_run(
        "run-start-prompt",
        session_id,
        SimpleNamespace(message="continue after reload", mode="auto"),
        decision,
    )

    messages = get_messages(session_id)
    assert any(
        message["role"] == "user"
        and message["content"] == "continue after reload"
        and message["run_id"] == "run-start-prompt"
        for message in messages
    )


def test_message_history_limit_returns_the_most_recent_messages_in_order() -> None:
    from backend.persistence.db import add_message, get_messages

    session_id = _make_session()
    add_message(session_id, "user", "first")
    add_message(session_id, "user", "second")
    add_message(session_id, "user", "third")

    messages = get_messages(session_id, limit=2)

    assert [message["content"] for message in messages] == ["second", "third"]


def test_terminal_update_sets_finished_at_and_correlation_lookup() -> None:
    from backend.persistence.db import (
        get_runs_by_correlation,
        mark_run_terminal,
        upsert_session_run,
    )

    session_id = _make_session()
    upsert_session_run(
        "run-terminal",
        session_id,
        correlation_id="corr-terminal",
        execution_state="running",
    )
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


def test_terminal_update_rejects_nonterminal_status_or_state() -> None:
    from backend.persistence.db import mark_run_terminal, upsert_session_run

    session_id = _make_session()
    upsert_session_run("run-invalid-terminal", session_id, execution_state="running")

    with pytest.raises(ValueError):
        mark_run_terminal("run-invalid-terminal", status="running")
    with pytest.raises(ValueError):
        mark_run_terminal(
            "run-invalid-terminal",
            status="completed",
            execution_state="running",
        )


def test_failed_run_can_store_blocked_execution_state() -> None:
    from backend.persistence.db import mark_run_terminal, upsert_session_run

    session_id = _make_session()
    upsert_session_run("run-blocked", session_id, execution_state="running")
    row = mark_run_terminal(
        "run-blocked",
        status="failed",
        execution_state="blocked",
    )

    assert row is not None
    assert row["status"] == "failed"
    assert row["execution_state"] == "blocked"


def test_recover_interrupted_runs_marks_stale_running_rows() -> None:
    from backend.persistence.db import DB_PATH, recover_interrupted_runs, upsert_session_run

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



def test_recovery_does_not_overwrite_concurrent_terminalization() -> None:
    from backend.persistence.db import DB_PATH, recover_interrupted_runs, upsert_session_run

    session_id = _make_session()
    upsert_session_run("run-race", session_id, execution_state="running")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE session_runs SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00Z", "run-race"),
        )
        conn.executescript(
            """
            CREATE TRIGGER terminalize_before_recovery
            BEFORE UPDATE OF status ON session_runs
            WHEN OLD.id = 'run-race' AND NEW.status = 'interrupted'
            BEGIN
                UPDATE session_runs
                   SET status = 'completed',
                       execution_state = 'completed'
                 WHERE id = OLD.id;
                SELECT RAISE(IGNORE);
            END;
            """
        )

    assert recover_interrupted_runs(max_age_seconds=1) == []
    with sqlite3.connect(DB_PATH) as conn:
        assert conn.execute(
            "SELECT status, execution_state FROM session_runs WHERE id = 'run-race'"
        ).fetchone() == ("completed", "completed")
