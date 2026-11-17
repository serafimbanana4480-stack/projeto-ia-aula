"""Contract tests for the composer -> primary-runtime bridge.

These are deliberately *independent*: they do not patch the coordinator, the
persistence layer, the tool registry or the route. They exercise the public
persistence primitives the bridge is required to rely on and fail with an
explicit ``CONTRACT-GAP`` when the contract in
``docs/closeout/GROUP-RUNTIME-CONTRACT.md`` is not represented in the schema or
behaviour.

The end-to-end HTTP/uvicorn scenarios live in
``backend/tests/integration/test_group_primary_e2e.py`` and
``backend/tests/integration/test_group_kill_restart.py``.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from backend.persistence import bot_group_runs, bot_groups, bots
from backend.persistence import db as db_module
from backend.persistence.db import get_db

pytestmark = pytest.mark.contract


def _profiles(owner: str = "contract-user") -> list[dict[str, Any]]:
    first = bots.create_bot(
        owner,
        {
            "name": "Alpha",
            "description": "leitura e analise",
            "instructions": "",
            "provider": "ollama",
            "model": "scripted:latest",
        },
    )
    second = bots.create_bot(
        owner,
        {
            "name": "Beta",
            "description": "revisao",
            "instructions": "",
            "provider": "ollama",
            "model": "scripted:latest",
        },
    )
    return [first, second]


def _group(owner: str, profiles: list[dict[str, Any]]) -> dict[str, Any]:
    group = bot_groups.create_group(owner, "Contract group", [item["id"] for item in profiles])
    assert group is not None
    return group


def _seed_primary_run(
    owner: str,
    *,
    root: Path,
    project_root: str = "",
) -> tuple[str, str, str, str]:
    """Create one run_state + projection + task and return their ids."""
    from backend.runtime.run_coordinator import RunCoordinator

    profiles = _profiles(owner)
    group = _group(owner, profiles)
    run_id = f"run-{uuid.uuid4().hex}"
    coordinator = RunCoordinator()
    coordinator.create_run(
        goal="contract",
        requirements=["responder"],
        constraints=[],
        definition_of_done=["resposta entregue"],
        project_id=project_root or str(root),
        user_id=owner,
        session_id=str(profiles[0]["session_id"]),
        run_id=run_id,
    )
    bot_group_runs.create(
        owner,
        group["id"],
        "contract request",
        project_root or str(root),
        "",
        profiles,
        run_id=run_id,
        execution_engine="primary",
    )
    run = bot_group_runs.get(owner, group["id"], run_id)
    assert run is not None
    task_id = str(run["tasks"][0]["id"])
    return run_id, group["id"], task_id, str(profiles[0]["id"])


def _columns(table: str) -> set[str]:
    with get_db() as conn:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


# ---------------------------------------------------------------------------
# 0. The bridge must be importable before anything else can be validated.
# ---------------------------------------------------------------------------
def test_group_primary_bridge_imports_cleanly() -> None:
    try:
        from backend.runtime import group_primary
    except Exception as exc:  # noqa: BLE001 - the exact import failure is the finding
        pytest.fail(
            "BLOCKED: backend.runtime.group_primary is not importable, so the "
            f"composer cannot start any run: {type(exc).__name__}: {exc}"
        )
    assert group_primary.EXECUTION_ENGINE_PRIMARY == "primary"
    assert group_primary.EXECUTION_ENGINE_LEGACY == "legacy_file"


# ---------------------------------------------------------------------------
# 1. Canonical identity must be a real column, not an API-side inference.
# ---------------------------------------------------------------------------
def test_canonical_run_id_and_engine_are_persisted_columns() -> None:
    required = {
        "bot_group_runs": {
            "execution_engine",
            "lease_owner",
            "lease_attempt_id",
            "lease_expires_at",
            "stop_reason",
        },
        "bot_group_messages": {"run_id"},
        "bot_group_run_tasks": {
            "attempt_id",
            "lease_expires_at",
            "effect_key",
            "effect_kind",
            "effect_evidence_json",
        },
        "run_state": {"owner_id", "attempt_id", "lease_expires_at", "reconciliation_json"},
    }
    gaps: list[str] = []
    for table, expected in required.items():
        actual = _columns(table)
        missing = sorted(expected - actual)
        if missing:
            gaps.append(f"{table}: missing {', '.join(missing)}")
    if gaps:
        pytest.fail(
            "CONTRACT-GAP: the durable identity/ownership columns are not in the "
            "schema, so the API has to invent them:\n- " + "\n- ".join(gaps)
        )


def test_group_message_add_api_persists_the_run_id() -> None:
    """The table must carry ``run_id``; an API-side record map is not enough."""
    columns = _columns("bot_group_messages")
    if "run_id" not in columns:
        pytest.fail(
            "CONTRACT-GAP: bot_group_messages.run_id does not exist. The bridge "
            "currently reconstructs it from bot_group_run_records, so a direct "
            "database reload cannot associate a message with its execution."
        )
    owner = "message-contract-user"
    profiles = _profiles(owner)
    group = _group(owner, profiles)
    run_id = f"run-{uuid.uuid4().hex}"
    # This is the storage primitive the bridge is expected to call. Its
    # signature must accept run_id; otherwise the column can never be filled.
    try:
        message = bot_groups.add_message(
            group["id"], "assistant", "ok", profiles[0]["id"], profiles[0]["name"],
            run_id=run_id,
        )
    except TypeError as exc:
        pytest.fail(
            "CONTRACT-GAP: bot_groups.add_message() does not accept run_id, so "
            f"bot_group_messages.run_id cannot be populated: {exc}"
        )
    assert message.get("run_id") == run_id
    with get_db() as conn:
        stored = conn.execute(
            "SELECT run_id FROM bot_group_messages WHERE id=?", (message["id"],)
        ).fetchone()
    assert stored is not None and stored["run_id"] == run_id


def test_primary_projection_stores_execution_engine_in_its_column() -> None:
    owner = "engine-contract-user"
    profiles = _profiles(owner)
    group = _group(owner, profiles)
    run_id = f"run-{uuid.uuid4().hex}"
    bot_group_runs.create(
        owner,
        group["id"],
        "engine",
        ".",
        "",
        profiles,
        run_id=run_id,
        execution_engine="primary",
    )
    with get_db() as conn:
        row = conn.execute(
            "SELECT execution_engine FROM bot_group_runs WHERE id=?", (run_id,)
        ).fetchone()
    assert row is not None
    assert row["execution_engine"] == "primary", (
        "the projection row must say primary; inferring it from a record or an id "
        "prefix means bot_group_runs.execution_engine is not the contract field"
    )


# ---------------------------------------------------------------------------
# 2. Two executors / stale attempt (same worker_id).
# ---------------------------------------------------------------------------
def test_two_executors_cannot_claim_one_task_and_stale_token_is_fenced(tmp_path: Path) -> None:
    run_id, _group_id, task_id, _bot_id = _seed_primary_run("claim-user", root=tmp_path)
    worker = "same-worker"

    first = bot_group_runs.claim_task(task_id, worker, lease_seconds=60)
    assert first, "the first executor must win the claim"
    second = bot_group_runs.claim_task(task_id, worker, lease_seconds=60)
    assert second is None, "a second executor claimed a live task"

    run = bot_group_runs.get("claim-user", _group_id, run_id)
    assert run is not None
    task_before = run["tasks"][0]
    assert int(task_before["attempt"]) == 1
    assert task_before["attempt_id"] == first

    # The first process dies: its lease is released, but the spent attempt and
    # its token are not refunded.
    assert bot_group_runs.release_task(task_id, worker, attempt_id=first) is True
    run = bot_group_runs.get("claim-user", _group_id, run_id)
    assert run is not None
    released = run["tasks"][0]
    assert int(released["attempt"]) == 1, "releasing a lease must not refund the attempt"
    assert released["attempt_id"] == first

    takeover = bot_group_runs.claim_task(task_id, worker)
    assert takeover, "the task must be claimable after its owner released it"
    assert takeover != first, "the takeover must rotate the fencing token"

    # The old executor wakes up. It reuses the same worker_id but its token is
    # stale; the persisted ownership check must reject the write.
    with pytest.raises(bot_group_runs.TaskOwnershipError):
        bot_group_runs.set_task(
            task_id,
            "completed",
            result="STALE",
            worker_id=worker,
            attempt_id=first,
        )
    assert bot_group_runs.complete_task(
        task_id, worker, takeover, result="FRESH"
    ) is True

    run = bot_group_runs.get("claim-user", _group_id, run_id)
    assert run is not None
    final = run["tasks"][0]
    assert final["result"] == "FRESH"
    assert int(final["attempt"]) == 2
    assert final["attempt_id"] == takeover


_CLAIM_CHILD = r"""
import json
import os
import sys
import time

repo, task_id, worker, go_file = sys.argv[1:5]
sys.path.insert(0, repo)
from backend.persistence import bot_group_runs

while not os.path.exists(go_file):
    time.sleep(0.005)
token = bot_group_runs.claim_task(task_id, worker, lease_seconds=60)
print("CLAIM_RESULT=" + json.dumps({"token": token}))
"""


def test_two_real_processes_only_one_claims_the_same_task(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    _run_id, _group_id, task_id, _bot_id = _seed_primary_run("process-claim-user", root=tmp_path)
    go_file = tmp_path / "go"
    env = {
        **os.environ,
        "NEXUS_DB_PATH": str(db_module.DB_PATH),
        "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
    }
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _CLAIM_CHILD,
                str(Path(__file__).resolve().parents[3]),
                task_id,
                f"process-{index}",
                str(go_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for index in range(2)
    ]
    time.sleep(0.4)
    go_file.write_text("go", encoding="utf-8")
    outputs: list[dict[str, Any]] = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            line = next(
                (line for line in stdout.splitlines() if line.startswith("CLAIM_RESULT=")),
                "",
            )
            assert process.returncode == 0, stderr
            assert line, f"child produced no claim result: {stdout}\n{stderr}"
            outputs.append(json.loads(line.split("=", 1)[1]))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()

    tokens = [item.get("token") for item in outputs]
    assert sum(1 for token in tokens if token) == 1, (
        "exactly one real process must win the atomic claim; got " + repr(tokens)
    )
    # The loser's write is fenced by the persisted owner, not by an in-memory set.
    winner = next(token for token in tokens if token)
    loser_worker = next(
        f"process-{index}" for index, item in enumerate(outputs) if not item.get("token")
    )
    winning_worker = next(
        f"process-{index}" for index, item in enumerate(outputs) if item.get("token")
    )
    with pytest.raises(bot_group_runs.TaskOwnershipError):
        bot_group_runs.set_task(
            task_id,
            "completed",
            result="stale-write",
            worker_id=loser_worker,
            attempt_id=winner,
        )
    assert bot_group_runs.complete_task(
        task_id, winning_worker, winner, result="winner-write"
    )
    run = bot_group_runs.get("process-claim-user", _group_id, _run_id)
    assert run is not None
    assert run["tasks"][0]["result"] == "winner-write"


def test_run_claim_fences_a_previous_attempt_with_the_same_owner(tmp_path: Path) -> None:
    from backend.runtime.run_coordinator import RunCoordinator, RunState, StaleAttemptError

    owner = "run-claim-user"
    run_id, group_id, _task_id, _bot_id = _seed_primary_run(owner, root=tmp_path)
    coordinator = RunCoordinator()
    worker = "run-worker"

    first = bot_group_runs.claim_run(run_id, worker, lease_seconds=60)
    assert first
    # A different executor must not be able to take a live run.
    assert bot_group_runs.claim_run(run_id, "other-worker", lease_seconds=60) is None
    assert bot_group_runs.release_run(run_id, worker, first) is True
    # The same worker may resume after its lease is released; that is a new
    # attempt with a new fencing token, not a reuse of the old attempt.
    second = bot_group_runs.claim_run(run_id, worker, lease_seconds=60)
    assert second and second != first
    assert bot_group_runs.owns_run(run_id, first) is False
    assert bot_group_runs.owns_run(run_id, second) is True

    with pytest.raises(StaleAttemptError):
        coordinator.transition(
            run_id, RunState.PLANNING, reason="stale wake-up", attempt_id=first
        )
    record = coordinator.get_run(run_id)
    assert record is not None and record.state is RunState.CREATED
    assert bot_groups.get_group(owner, group_id) is not None


# ---------------------------------------------------------------------------
# 3. Crash after a write: reconcile or block, never replay.
# ---------------------------------------------------------------------------
def _effect_task(tmp_path: Path, owner: str) -> tuple[str, str, str, str]:
    run_id, group_id, task_id, _bot_id = _seed_primary_run(owner, root=tmp_path)
    bot_group_runs.set_run(run_id, "running")
    token = bot_group_runs.claim_task(task_id, "effect-worker", lease_seconds=60)
    assert token
    return run_id, group_id, task_id, token


def test_pending_effect_with_workspace_evidence_blocks_replay(tmp_path: Path) -> None:
    owner = "pending-effect-user"
    run_id, _group_id, task_id, token = _effect_task(tmp_path, owner)
    (tmp_path / "written.txt").write_text("ONCE", encoding="utf-8")

    assert bot_group_runs.begin_effect(
        task_id,
        "effect-worker",
        token,
        key="write:written.txt",
        kind="write_file",
        evidence_paths=["written.txt"],
    )
    counts = bot_group_runs.interrupt_unfinished()
    assert counts["blocked"] >= 1

    run = bot_group_runs.get(owner, _group_id, run_id)
    assert run is not None
    assert run["status"] == "blocked"
    assert run["tasks"][0]["status"] == "blocked"
    assert run["tasks"][0]["error_class"] == "reconciliation_required"
    assert bot_group_runs.get_effect_state(run_id, "write:written.txt") == "pending"

    # A blind retry is refused: the run is parked and the task is not
    # claimable, so the write cannot be repeated before a human reconciles it.
    assert bot_group_runs.claim_task(task_id, "effect-worker") is None
    assert (tmp_path / "written.txt").read_text(encoding="utf-8") == "ONCE"
    blocked = bot_group_runs.list_blocked_runs()
    assert (owner, _group_id, run_id) in blocked


def test_confirmed_effect_without_completion_blocks_until_reconciled(tmp_path: Path) -> None:
    owner = "confirmed-effect-user"
    run_id, _group_id, task_id, token = _effect_task(tmp_path, owner)
    (tmp_path / "written.txt").write_text("ONCE", encoding="utf-8")

    assert bot_group_runs.begin_effect(
        task_id,
        "effect-worker",
        token,
        key="write:written.txt",
        kind="write_file",
        evidence_paths=["written.txt"],
    )
    assert bot_group_runs.confirm_effect(
        task_id, "effect-worker", token, result_digest="digest-once"
    )
    bot_group_runs.interrupt_unfinished()

    run = bot_group_runs.get(owner, _group_id, run_id)
    assert run is not None
    assert run["status"] == "blocked"
    assert run["tasks"][0]["status"] == "blocked"
    assert run["tasks"][0]["error_class"] == "effect_confirmed_result_missing"
    # The ledger says the effect happened; no second call may be granted by the
    # group executor even though the completion row is missing.
    assert bot_group_runs.claim_task(task_id, "effect-worker") is None
    assert (tmp_path / "written.txt").read_text(encoding="utf-8") == "ONCE"


def test_cancelled_run_never_resurrects_and_keeps_its_outcome(tmp_path: Path) -> None:
    owner = "cancel-contract-user"
    run_id, _group_id, task_id, _token = _effect_task(tmp_path, owner)
    assert bot_group_runs.cancel_run(run_id, reason="user stop") is True
    assert bot_group_runs.set_run(run_id, "running") is False
    assert bot_group_runs.claim_task(task_id, "late-worker") is None
    run = bot_group_runs.get(owner, _group_id, run_id)
    assert run is not None
    assert run["status"] == "cancelled"
    assert run["tasks"][0]["status"] == "cancelled"


def test_database_path_is_disposable() -> None:
    """Guard: this suite must never run against the canonical data directory."""
    current = Path(db_module.DB_PATH).resolve()
    assert "data" not in current.parts, f"refusing to run contract tests against {current}"
