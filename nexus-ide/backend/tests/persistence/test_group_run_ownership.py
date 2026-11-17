"""Durability invariants for the group-run projection.

These tests exercise the persisted authority, not a process-local set: every
claim/lease/write goes through SQLite and the assertions read the rows back.
"""

from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from backend.persistence import bot_group_runs, bots, db
from backend.persistence import bot_groups as groups
from backend.runtime.run_coordinator import (
    ReconciliationRequired,
    RunCoordinator,
    RunState,
    StaleAttemptError,
)


def _bots(owner: str, count: int = 2) -> list[dict[str, Any]]:
    return [
        bots.create_bot(
            owner,
            {
                "name": f"bot-{index}",
                "description": "",
                "instructions": "",
                "provider": "lmstudio",
                "model": f"model-{index}",
            },
        )
        for index in range(count)
    ]


def _group(owner: str, count: int = 2) -> tuple[str, list[dict[str, Any]]]:
    members = _bots(owner, count)
    created = groups.create_group(owner, "durability", [member["id"] for member in members])
    assert created is not None
    return str(created["id"]), members


def _new_run(
    owner: str = "alice",
    *,
    count: int = 2,
    run_id: str | None = None,
    engine: str = "legacy_file",
) -> tuple[str, str, list[dict[str, Any]]]:
    group_id, members = _group(owner, count)
    resolved = bot_group_runs.create(
        owner,
        group_id,
        "request",
        ".",
        "file.txt",
        members,
        run_id=run_id,
        execution_engine=engine,
    )
    return resolved, group_id, members


def _task(run_id: str, owner: str, group_id: str, index: int = 0) -> dict[str, Any]:
    run = bot_group_runs.get(owner, group_id, run_id)
    assert run is not None
    return run["tasks"][index]


# ---------------------------------------------------------------------------
# claim / fencing
# ---------------------------------------------------------------------------


def test_two_concurrent_claims_have_exactly_one_winner() -> None:
    run_id, group_id, _ = _new_run()
    task = _task(run_id, "alice", group_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda worker: bot_group_runs.claim_task(
                    task["id"], worker, lease_seconds=60
                ),
                ("worker-a", "worker-b"),
            )
        )

    assert sum(1 for token in results if token) == 1, results
    stored = _task(run_id, "alice", group_id)
    assert stored["status"] == "running"
    assert stored["attempt"] == 1
    assert stored["attempt_id"] in [token for token in results if token]
    assert stored["worker_id"] in {"worker-a", "worker-b"}


def test_stale_attempt_is_rejected_even_with_the_same_worker_id() -> None:
    run_id, group_id, _ = _new_run()
    task = _task(run_id, "alice", group_id)

    first = bot_group_runs.claim_task(task["id"], "same-worker", lease_seconds=0.05)
    assert first
    time.sleep(0.12)
    second = bot_group_runs.claim_task(task["id"], "same-worker", lease_seconds=60)

    assert second
    assert second != first
    with pytest.raises(bot_group_runs.TaskOwnershipError):
        bot_group_runs.complete_task(
            task["id"], "same-worker", first, result="stale write"
        )
    with pytest.raises(bot_group_runs.TaskOwnershipError):
        bot_group_runs.set_task(
            task["id"],
            "failed",
            worker_id="same-worker",
            attempt_id=first,
            error="stale failure",
        )

    stored = _task(run_id, "alice", group_id)
    assert stored["status"] == "running"
    assert stored["attempt"] == 2
    assert stored["result"] is None
    assert stored["attempt_id"] == second

    assert bot_group_runs.complete_task(
        task["id"], "same-worker", second, result="fresh write"
    )
    stored = _task(run_id, "alice", group_id)
    assert stored["status"] == "completed"
    assert stored["result"] == "fresh write"
    assert stored["attempt"] == 2


def test_expired_lease_preserves_attempt_counter_and_run_budget() -> None:
    coordinator = RunCoordinator()
    run = coordinator.create_run(
        goal="budget survives lease churn",
        requirements=["answer"],
        definition_of_done=["answer"],
        budget={"max_tokens": 100},
        run_id="run-budget-" + str(time.time_ns()),
    )
    coordinator.transition(run.run_id, RunState.PLANNING)
    coordinator.transition(run.run_id, RunState.RUNNING)
    assert coordinator.record_usage(run.run_id, tokens=7).ok
    before = coordinator.get_run(run.run_id)
    assert before is not None

    group_id, members = _group("alice")
    run_id = bot_group_runs.create(
        "alice",
        group_id,
        "request",
        ".",
        "file.txt",
        members,
        run_id=run.run_id,
        execution_engine="primary",
    )
    task = _task(run_id, "alice", group_id)

    first = bot_group_runs.claim_task(task["id"], "worker", lease_seconds=0.05)
    assert first
    time.sleep(0.12)
    second = bot_group_runs.claim_task(task["id"], "worker", lease_seconds=60)
    assert second and second != first

    stored = _task(run_id, "alice", group_id)
    assert stored["attempt"] == 2, "a lease expiry must not refund a retry"
    after = coordinator.get_run(run.run_id)
    assert after is not None
    assert after.retry_count == before.retry_count
    assert after.budget == before.budget
    verdict = coordinator.budget_status(run.run_id)
    assert verdict.usage["tokens"] == 7, "lease churn must not touch accumulated usage"
    assert verdict.ok


def test_run_claim_is_exclusive_and_force_takeover_rotates_the_token() -> None:
    run_id, group_id, _ = _new_run()

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(
            pool.map(
                lambda worker: bot_group_runs.claim_run(run_id, worker, lease_seconds=60),
                ("resumer-a", "resumer-b"),
            )
        )

    winners = [token for token in tokens if token]
    assert len(winners) == 1, tokens
    first = winners[0]
    assert bot_group_runs.owns_run(run_id, first)

    takeover = bot_group_runs.claim_run(run_id, "resumer-c", force=True)
    assert takeover and takeover != first
    assert not bot_group_runs.owns_run(run_id, first)
    assert bot_group_runs.owns_run(run_id, takeover)


def test_group_and_primary_claim_adopt_the_same_attempt_identity() -> None:
    coordinator = RunCoordinator()
    run = coordinator.create_run(
        goal="shared identity",
        requirements=[],
        definition_of_done=[],
        run_id="run-shared-" + str(time.time_ns()),
    )
    group_id, members = _group("alice")
    run_id = bot_group_runs.create(
        "alice",
        group_id,
        "request",
        ".",
        "file.txt",
        members,
        run_id=run.run_id,
        execution_engine="primary",
    )
    group_token = bot_group_runs.claim_run(run_id, "worker", lease_seconds=60)
    assert group_token
    primary = coordinator.claim(run.run_id, owner_id="worker", lease_seconds=60)
    assert primary is not None
    assert primary.attempt_id == group_token, "one execution, one attempt identity"
    task = _task(run_id, "alice", group_id)
    assert bot_group_runs.claim_task(task["id"], "worker", lease_seconds=60)
    state = coordinator.get_run(run.run_id)
    assert state is not None
    assert state.attempt_id == group_token


# ---------------------------------------------------------------------------
# outcome vocabulary
# ---------------------------------------------------------------------------


def test_retryable_interrupted_terminal_and_skipped_are_distinct() -> None:
    run_id, group_id, _ = _new_run(count=3)

    first = _task(run_id, "alice", group_id, 0)
    token = bot_group_runs.claim_task(first["id"], "worker", lease_seconds=60)
    assert token
    assert bot_group_runs.fail_task(
        first["id"],
        "worker",
        token,
        status="retryable",
        error="provider 503",
        error_class="transient",
    )
    assert _task(run_id, "alice", group_id, 0)["status"] == "retryable"

    retry_token = bot_group_runs.claim_task(first["id"], "worker", lease_seconds=60)
    assert retry_token
    assert bot_group_runs.fail_task(
        first["id"], "worker", retry_token, status="failed", error="terminal"
    )
    assert bot_group_runs.claim_task(first["id"], "worker", lease_seconds=60) is None

    second = _task(run_id, "alice", group_id, 1)
    token = bot_group_runs.claim_task(second["id"], "worker", lease_seconds=60)
    assert token
    assert bot_group_runs.release_task(second["id"], "worker", attempt_id=token)
    assert _task(run_id, "alice", group_id, 1)["status"] == "interrupted"
    assert bot_group_runs.claim_task(second["id"], "worker-2", lease_seconds=60)

    third = _task(run_id, "alice", group_id, 2)
    assert bot_group_runs.set_task(third["id"], "skipped", error="plan skipped it")
    assert _task(run_id, "alice", group_id, 2)["status"] == "skipped"
    assert bot_group_runs.claim_task(third["id"], "worker", lease_seconds=60) is None


def test_restart_rotates_the_fence_on_an_already_completed_task() -> None:
    run_id, group_id, _ = _new_run()
    task = _task(run_id, "alice", group_id, 0)
    token = bot_group_runs.claim_task(task["id"], "worker", lease_seconds=60)
    assert token
    assert bot_group_runs.complete_task(task["id"], "worker", token, result="original")

    bot_group_runs.interrupt_unfinished()

    stored = _task(run_id, "alice", group_id)
    assert stored["status"] == "completed"
    assert stored["result"] == "original"
    assert stored["attempt"] == 1
    assert stored["attempt_id"] != token, "startup must invalidate the dead attempt"
    with pytest.raises(bot_group_runs.TaskOwnershipError):
        bot_group_runs.complete_task(task["id"], "worker", token, result="tampered")
    assert _task(run_id, "alice", group_id)["result"] == "original"


def test_completed_run_rejects_post_completion_mutations() -> None:
    run_id, group_id, _ = _new_run()
    task = _task(run_id, "alice", group_id, 0)
    token = bot_group_runs.claim_task(task["id"], "worker", lease_seconds=60)
    assert token
    assert bot_group_runs.complete_task(task["id"], "worker", token, result="done")
    assert bot_group_runs.set_run(run_id, "completed")
    assert bot_group_runs.set_task(task["id"], "failed", error="tamper") is False
    assert (
        bot_group_runs.complete_task(task["id"], "worker", token, result="tamper")
        is False
    )
    stored = _task(run_id, "alice", group_id)
    assert stored["status"] == "completed"
    assert stored["result"] == "done"


def test_restart_preserves_failed_retryable_and_skipped_outcomes() -> None:
    run_id, group_id, _ = _new_run(count=3)
    first, second, third = (
        _task(run_id, "alice", group_id, 0),
        _task(run_id, "alice", group_id, 1),
        _task(run_id, "alice", group_id, 2),
    )
    token = bot_group_runs.claim_task(first["id"], "worker", lease_seconds=60)
    assert token
    assert bot_group_runs.fail_task(
        first["id"], "worker", token, status="failed", error="terminal"
    )
    token = bot_group_runs.claim_task(second["id"], "worker", lease_seconds=60)
    assert token
    assert bot_group_runs.fail_task(
        second["id"], "worker", token, status="retryable", error="provider 503"
    )
    assert bot_group_runs.set_task(third["id"], "skipped", error="plan skipped")

    bot_group_runs.interrupt_unfinished()

    statuses = [task["status"] for task in bot_group_runs.get("alice", group_id, run_id)["tasks"]]
    assert statuses == ["failed", "retryable", "skipped"], statuses
    run = bot_group_runs.get("alice", group_id, run_id)
    assert run is not None
    assert run["status"] == "interrupted"


def test_completed_task_never_reruns_and_cancelled_run_never_resurrects() -> None:
    run_id, group_id, _ = _new_run()
    first, second = (
        _task(run_id, "alice", group_id, 0),
        _task(run_id, "alice", group_id, 1),
    )

    token = bot_group_runs.claim_task(first["id"], "worker", lease_seconds=60)
    assert token
    assert bot_group_runs.complete_task(first["id"], "worker", token, result="done")

    assert bot_group_runs.claim_task(first["id"], "worker", lease_seconds=60) is None
    assert bot_group_runs.set_task(first["id"], "pending") is False
    assert _task(run_id, "alice", group_id, 0)["status"] == "completed"

    token = bot_group_runs.claim_task(second["id"], "worker", lease_seconds=60)
    assert token
    assert bot_group_runs.set_run(run_id, "cancelled")
    assert bot_group_runs.set_run(run_id, "running") is False
    assert bot_group_runs.claim_task(second["id"], "worker-2", lease_seconds=60) is None
    assert bot_group_runs.claim_run(run_id, "resumer") is None


# ---------------------------------------------------------------------------
# crash after a workspace write
# ---------------------------------------------------------------------------


def test_crash_after_workspace_write_blocks_instead_of_rewriting(
    tmp_path: Path,
) -> None:
    coordinator = RunCoordinator()
    run = coordinator.create_run(
        goal="write once",
        requirements=["file written"],
        definition_of_done=["file written"],
        run_id="run-crash-" + str(time.time_ns()),
    )
    coordinator.transition(run.run_id, RunState.PLANNING)
    coordinator.transition(run.run_id, RunState.RUNNING)

    group_id, members = _group("alice")
    run_id = bot_group_runs.create(
        "alice",
        group_id,
        "write once",
        str(tmp_path),
        "notas.txt",
        members,
        run_id=run.run_id,
        execution_engine="primary",
    )
    task = _task(run_id, "alice", group_id)
    run_token = bot_group_runs.claim_run(run_id, "worker-a", lease_seconds=60)
    assert run_token
    token = bot_group_runs.claim_task(task["id"], "worker-a", lease_seconds=60)
    assert token

    key = "write_file:crash-case"
    coordinator.checkpoint(
        run.run_id,
        phase="before_side_effect",
        payload={
            "tool": "write_file",
            "args": {"path": "notas.txt", "project_path": str(tmp_path)},
            "idempotency_key": key,
            "task_id": task["id"],
        },
        attempt_id=run_token,
    )
    assert bot_group_runs.begin_effect(
        task["id"],
        "worker-a",
        token,
        key=key,
        kind="write_file",
        evidence_paths=["notas.txt"],
    )

    # The write really happened; the process dies before recording completion.
    written = tmp_path / "notas.txt"
    written.write_text("once", encoding="utf-8")

    counts = bot_group_runs.interrupt_unfinished()
    assert counts["blocked"] >= 1

    crash = bot_group_runs.get("alice", group_id, run_id)
    assert crash is not None
    assert crash["status"] == "blocked"
    blocked_task = crash["tasks"][0]
    assert blocked_task["status"] == "blocked"
    assert blocked_task["error_class"] == "reconciliation_required"
    assert blocked_task["attempt"] == 1
    assert "notas.txt" in blocked_task["error"]
    assert bot_group_runs.claim_task(task["id"], "worker-b", lease_seconds=60) is None
    assert written.read_text(encoding="utf-8") == "once"

    # The primary runtime agrees: paused with evidence, not silently resumable.
    state = coordinator.get_run(run.run_id)
    assert state is not None
    assert state.state is RunState.PAUSED
    effects = state.reconciliation["effects"]
    assert effects and effects[0]["evidence"] == ["notas.txt"]
    with pytest.raises(ReconciliationRequired):
        coordinator.restore(run.run_id)
    assert coordinator.claim(run.run_id, owner_id="worker-b") is None

    # No blind retry: the ledger still says pending and cannot be re-reserved.
    assert coordinator.reserve_side_effect(run.run_id, key, kind="write_file") is False
    assert bot_group_runs.get_effect_state(run.run_id, key) == "pending"


def test_primary_lease_takeover_fences_the_old_attempt_and_keeps_usage() -> None:
    coordinator = RunCoordinator()
    run = coordinator.create_run(
        goal="ownership",
        requirements=[],
        definition_of_done=[],
        run_id="run-lease-" + str(time.time_ns()),
    )
    first = coordinator.claim(run.run_id, owner_id="worker-a", lease_seconds=0.05)
    assert first is not None
    assert coordinator.claim(run.run_id, owner_id="worker-b", lease_seconds=60) is None

    time.sleep(0.12)
    second = coordinator.claim(run.run_id, owner_id="worker-b", lease_seconds=60)
    assert second is not None
    assert second.attempt_id != first.attempt_id

    with pytest.raises(StaleAttemptError):
        coordinator.update_progress(
            run.run_id, current_task_id="stale", attempt_id=first.attempt_id
        )
    coordinator.update_progress(
        run.run_id, current_task_id="fresh", attempt_id=second.attempt_id
    )
    state = coordinator.get_run(run.run_id)
    assert state is not None
    assert state.current_task_id == "fresh"


def test_startup_recovery_clears_a_dead_lease_and_marks_the_run_recovering() -> None:
    coordinator = RunCoordinator()
    run = coordinator.create_run(
        goal="interrupted",
        requirements=[],
        definition_of_done=[],
        run_id="run-startup-" + str(time.time_ns()),
    )
    coordinator.transition(run.run_id, RunState.PLANNING)
    coordinator.transition(run.run_id, RunState.RUNNING)
    claim = coordinator.claim(run.run_id, owner_id="dead-process", lease_seconds=300)
    assert claim is not None

    recovered = coordinator.recover_stale_claims(run_ids=[run.run_id])
    assert recovered == [run.run_id]
    state = coordinator.get_run(run.run_id)
    assert state is not None
    assert state.state is RunState.RECOVERING
    assert state.owner_id == ""
    assert state.attempt_id is None
    assert coordinator.owns(run.run_id, claim.attempt_id) is False
    # The dead lease must not delay a real resume.
    replacement = coordinator.claim(
        run.run_id, owner_id="new-process", lease_seconds=60
    )
    assert replacement is not None
    assert replacement.attempt_id != claim.attempt_id


# ---------------------------------------------------------------------------
# schema compatibility
# ---------------------------------------------------------------------------


_OLD_GROUP_SCHEMA = """
CREATE TABLE bot_groups (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE bot_group_runs (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES bot_groups(id),
    user_id TEXT NOT NULL,
    request TEXT NOT NULL,
    project_root TEXT NOT NULL,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE bot_group_run_tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES bot_group_runs(id),
    position INTEGER NOT NULL,
    bot_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    worker_id TEXT,
    claimed_at TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    UNIQUE(run_id, position)
);
CREATE TABLE bot_group_run_records (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES bot_group_runs(id),
    task_id TEXT NOT NULL REFERENCES bot_group_run_tasks(id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


def test_fresh_database_has_the_ownership_columns() -> None:
    with sqlite3.connect(str(db.DB_PATH)) as conn:
        run_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(bot_group_runs)")}
        task_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(bot_group_run_tasks)")
        }
    assert {
        "execution_engine",
        "lease_owner",
        "lease_attempt_id",
        "lease_expires_at",
        "updated_at",
    } <= run_columns
    assert {
        "attempt_id",
        "lease_expires_at",
        "error_class",
        "finished_at",
        "effect_key",
        "effect_kind",
        "effect_evidence_json",
    } <= task_columns

    run_id, group_id, _ = _new_run()
    stored = bot_group_runs.get("alice", group_id, run_id)
    assert stored is not None
    assert stored["execution_engine"] == "legacy_file"
    assert stored["updated_at"]


def test_legacy_database_migrates_without_rewriting_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_db = tmp_path / "old.db"
    with sqlite3.connect(str(old_db)) as conn:
        conn.executescript(_OLD_GROUP_SCHEMA)
        conn.execute(
            "INSERT INTO bot_groups (id, user_id, name) VALUES ('g-old', 'alice', 'old')"
        )
        conn.execute(
            "INSERT INTO bot_group_runs "
            "(id, group_id, user_id, request, project_root, file_path, status, created_at) "
            "VALUES ('run-old', 'g-old', 'alice', 'req', '.', 'a.txt', 'running', "
            "'2025-01-01T00:00:00.000Z')"
        )
        conn.execute(
            "INSERT INTO bot_group_run_tasks "
            "(id, run_id, position, bot_id, bot_name, provider, model, status, "
            "worker_id, claimed_at, attempt) "
            "VALUES ('task-old', 'run-old', 0, 'b1', 'B', 'p', 'm', 'running', "
            "'legacy-worker', '2025-01-01T00:00:01.000Z', 2)"
        )
        conn.commit()

    monkeypatch.setattr(db, "DB_PATH", old_db)
    db.close_pool()
    db.init_db(run_migrations=False)
    try:
        with sqlite3.connect(str(old_db)) as conn:
            run_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(bot_group_runs)")
            }
            task_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(bot_group_run_tasks)")
            }
        assert "execution_engine" in run_columns
        assert "attempt_id" in task_columns

        run = bot_group_runs.get("alice", "g-old", "run-old")
        assert run is not None
        assert run["status"] == "running", "history must not be rewritten"
        assert run["created_at"] == "2025-01-01T00:00:00.000Z"
        task = run["tasks"][0]
        assert task["status"] == "running"
        assert task["worker_id"] == "legacy-worker"
        assert task["attempt"] == 2, "an old retry counter must survive the migration"
        assert task["attempt_id"] is None
        assert task["effect_evidence_json"] == "[]"

        # Idempotent: a second startup is a no-op, not a second migration.
        db.close_pool()
        db.init_db(run_migrations=False)
        again = bot_group_runs.get("alice", "g-old", "run-old")
        assert again is not None
        assert again["status"] == "running"
        assert again["tasks"][0]["attempt"] == 2
        with sqlite3.connect(str(old_db)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM bot_group_runs").fetchone()[0] == 1
    finally:
        db.close_pool()


_OLD_MESSAGES_SCHEMA = """
CREATE TABLE bot_groups (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE bot_group_messages (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES bot_groups(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ({roles})),
    content TEXT NOT NULL,
    bot_id TEXT,
    bot_name TEXT,
    created_at TEXT NOT NULL DEFAULT ''
);
"""


@pytest.mark.parametrize(
    "roles",
    [
        "'user', 'assistant', 'error'",
        "'user', 'assistant', 'error', 'coordinator', 'decision'",
    ],
    ids=["pre-coordinator-roles", "post-coordinator-roles"],
)
def test_legacy_messages_gain_run_id_without_losing_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    roles: str,
) -> None:
    old_db = tmp_path / "old-messages.db"
    rows = [
        ("m-1", "user", "pedido original", None, None, "2025-02-01T10:00:00.000Z"),
        ("m-2", "assistant", "resposta original", "bot-1", "Alpha", "2025-02-01T10:00:01.000Z"),
        ("m-3", "error", "falha original", "bot-2", "Beta", "2025-02-01T10:00:02.000Z"),
    ]
    with sqlite3.connect(str(old_db)) as conn:
        conn.executescript(_OLD_MESSAGES_SCHEMA.format(roles=roles))
        conn.execute(
            "INSERT INTO bot_groups (id, user_id, name) VALUES ('g-msg', 'alice', 'legacy chat')"
        )
        conn.executemany(
            "INSERT INTO bot_group_messages "
            "(id, group_id, role, content, bot_id, bot_name, created_at) "
            "VALUES (?, 'g-msg', ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

    monkeypatch.setattr(db, "DB_PATH", old_db)
    db.close_pool()
    db.init_db(run_migrations=False)
    try:
        with sqlite3.connect(str(old_db)) as conn:
            conn.row_factory = sqlite3.Row
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(bot_group_messages)")
            }
            stored = {
                str(row["id"]): dict(row)
                for row in conn.execute("SELECT * FROM bot_group_messages")
            }
        assert "run_id" in columns
        assert len(stored) == 3, "the migration must preserve every message"
        for message_id, role, content, bot_id, bot_name, created_at in rows:
            item = stored[message_id]
            assert item["group_id"] == "g-msg"
            assert item["role"] == role
            assert item["content"] == content
            assert item["bot_id"] == bot_id
            assert item["bot_name"] == bot_name
            assert item["created_at"] == created_at
            assert item["run_id"] is None, "historical rows must not invent a run_id"

        messages = groups.get_messages("alice", "g-msg")
        assert messages is not None
        assert [item["id"] for item in messages] == ["m-1", "m-2", "m-3"]
        assert all(item["run_id"] is None for item in messages)

        created = groups.add_message(
            "g-msg",
            "assistant",
            "resposta nova",
            "bot-1",
            "Alpha",
            run_id="run-msg-1",
        )
        assert created["run_id"] == "run-msg-1"
        page = groups.get_messages_page("alice", "g-msg", limit=2, before=None)
        assert page is not None
        assert page["messages"][-1]["run_id"] == "run-msg-1"

        # Idempotent re-open: rerunning the migration keeps every row and the
        # new link.
        db.close_pool()
        db.init_db(run_migrations=False)
        reloaded = groups.get_messages("alice", "g-msg")
        assert reloaded is not None
        assert len(reloaded) == 4
        assert reloaded[-1]["run_id"] == "run-msg-1"
        assert [item["content"] for item in reloaded[:3]] == [
            "pedido original",
            "resposta original",
            "falha original",
        ]
    finally:
        db.close_pool()


def test_side_effect_ledger_is_json_and_never_duplicates(tmp_path: Path) -> None:
    coordinator = RunCoordinator()
    run = coordinator.create_run(
        goal="effect",
        requirements=[],
        definition_of_done=[],
        run_id="run-effect-" + str(time.time_ns()),
    )
    key = "write_file:one"
    assert coordinator.reserve_side_effect(run.run_id, key, kind="write_file")
    assert not coordinator.reserve_side_effect(run.run_id, key, kind="write_file")
    row = coordinator.get_side_effect(run.run_id, key)
    assert row is not None
    assert row["status"] == "pending"
    assert coordinator.confirm_side_effect(run.run_id, key, result_digest="digest")
    assert not coordinator.confirm_side_effect(run.run_id, key, result_digest="other")
    report = coordinator.reconcile_pending_side_effects(run.run_id)
    assert report == []
    stored = json.loads(json.dumps(coordinator.get_side_effect(run.run_id, key)))
    assert stored["status"] == "confirmed"
