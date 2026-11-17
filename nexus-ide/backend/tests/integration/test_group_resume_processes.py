"""Two real processes, one SQLite file: claim exclusivity and crash recovery.

The unit tests prove the SQL rules in-process. This file proves the same rules
across operating-system processes with ``subprocess``: a claim held by one
process cannot be taken by another, a killed holder does not duplicate work
after restart, and a stale attempt (same ``worker_id``) cannot write after the
task was reclaimed. Every database lives under ``tmp_path``; ``data/`` is never
opened.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from backend.persistence.db import SCHEMA_PATH

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER = Path(__file__).resolve().parent / "group_run_worker.py"
STARTUP_TIMEOUT_S = 60.0


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _seed(db_path: Path, run_id: str, task_id: str) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO bot_groups (id, user_id, name) VALUES ('g-1', 'alice', 'group')"
        )
        conn.execute(
            "INSERT INTO bot_group_runs "
            "(id, group_id, user_id, request, project_root, file_path, status, "
            "execution_engine, created_at, updated_at) "
            "VALUES (?, 'g-1', 'alice', 'req', '.', 'a.txt', 'pending', "
            "'legacy_file', '2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z')",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO bot_group_run_tasks "
            "(id, run_id, position, bot_id, bot_name, provider, model, status, attempt) "
            "VALUES (?, ?, 0, 'bot-1', 'Bot', 'p', 'm', 'pending', 0)",
            (task_id, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _task_row(db_path: Path, task_id: str) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM bot_group_run_tasks WHERE id=?", (task_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return dict(row)


def _run_row(db_path: Path, run_id: str) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM bot_group_runs WHERE id=?", (run_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    return dict(row)


def _wait_file(path: Path, timeout: float = STARTUP_TIMEOUT_S) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            import json

            return json.loads(path.read_text(encoding="utf-8"))
        time.sleep(0.01)
    raise AssertionError(f"worker did not write {path}")


def _spawn(
    db_path: Path,
    action: str,
    *,
    out: Path,
    task: str = "",
    worker: str = "",
    token: str = "",
    result: str = "done",
    gate: Path | None = None,
    lease: float = 60.0,
    hold: float = 0.0,
) -> subprocess.Popen[str]:
    command = [
        sys.executable,
        str(WORKER),
        action,
        "--task",
        task,
        "--worker",
        worker,
        "--token",
        token,
        "--result",
        result,
        "--out",
        str(out),
        "--lease",
        str(lease),
        "--hold",
        str(hold),
    ]
    if gate is not None:
        command.extend(["--gate", str(gate)])
    env = dict(os.environ)
    env["NEXUS_DB_PATH"] = str(db_path)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _finish(process: subprocess.Popen[str], timeout: float = 60.0) -> None:
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=30)
        raise AssertionError(
            f"worker timed out; stdout={stdout!r} stderr={stderr!r}"
        ) from None
    assert process.returncode == 0, f"worker failed: stdout={stdout!r} stderr={stderr!r}"


def test_two_processes_race_one_claim_and_the_stale_attempt_is_fenced(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "race.db"
    _seed(db_path, "run-race", "task-race")
    gate = tmp_path / "go"

    outputs = {"worker-a": tmp_path / "a.json", "worker-b": tmp_path / "b.json"}
    workers = [
        _spawn(
            db_path,
            "claim",
            out=output_path,
            task="task-race",
            worker=worker,
            gate=gate,
            lease=1.0,
        )
        for worker, output_path in outputs.items()
    ]
    try:
        # Give both processes time to reach the gate, then release them together.
        time.sleep(0.3)
        gate.write_text("go", encoding="utf-8")
        for process in workers:
            _finish(process)
    finally:
        for process in workers:
            if process.poll() is None:
                process.kill()

    results = {
        worker: _wait_file(path) for worker, path in outputs.items()
    }
    winners = {worker: payload["token"] for worker, payload in results.items() if payload["token"]}
    assert len(winners) == 1, results
    winner_worker, first_token = next(iter(winners.items()))

    stored = _task_row(db_path, "task-race")
    assert stored["status"] == "running"
    assert stored["attempt"] == 1
    assert stored["worker_id"] == winner_worker
    assert stored["attempt_id"] == first_token

    # The lease expires; the same worker_id is allowed to reclaim, but the
    # token rotates. The old attempt must not be able to write after that.
    time.sleep(1.3)
    second_out = tmp_path / "second.json"
    second = _spawn(
        db_path,
        "claim",
        out=second_out,
        task="task-race",
        worker=winner_worker,
        lease=60.0,
    )
    _finish(second)
    second_token = _wait_file(second_out)["token"]
    assert second_token and second_token != first_token
    stored = _task_row(db_path, "task-race")
    assert stored["attempt"] == 2
    assert stored["attempt_id"] == second_token

    stale_out = tmp_path / "stale.json"
    stale = _spawn(
        db_path,
        "complete",
        out=stale_out,
        task="task-race",
        worker=winner_worker,
        token=first_token,
        result="stale write",
    )
    _finish(stale)
    stale_result = _wait_file(stale_out)
    assert stale_result["ok"] is False
    assert stale_result["error"] == "TaskOwnershipError"
    assert _task_row(db_path, "task-race")["result"] is None

    fresh_out = tmp_path / "fresh.json"
    fresh = _spawn(
        db_path,
        "complete",
        out=fresh_out,
        task="task-race",
        worker=winner_worker,
        token=second_token,
        result="fresh write",
    )
    _finish(fresh)
    assert _wait_file(fresh_out)["ok"] is True
    stored = _task_row(db_path, "task-race")
    assert stored["status"] == "completed"
    assert stored["result"] == "fresh write"
    assert stored["attempt"] == 2


@pytest.mark.timeout(180)
def test_killed_holder_is_recovered_by_a_new_process_without_duplicates(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "restart.db"
    _seed(db_path, "run-restart", "task-restart")

    holder_out = tmp_path / "holder.json"
    holder = _spawn(
        db_path,
        "claim",
        out=holder_out,
        task="task-restart",
        worker="holder",
        lease=300.0,
        hold=120.0,
    )
    holder_token = _wait_file(holder_out)["token"]
    assert holder_token
    assert holder.poll() is None, "the holder must still be alive before the kill"
    holder.kill()
    holder.communicate(timeout=30)

    stored = _task_row(db_path, "task-restart")
    assert stored["status"] == "running"
    assert stored["worker_id"] == "holder"
    assert stored["attempt"] == 1
    assert stored["attempt_id"] == holder_token

    recover_out = tmp_path / "recover.json"
    recovery = _spawn(
        db_path,
        "recover_and_claim",
        out=recover_out,
        task="task-restart",
        worker="replacement",
        lease=60.0,
    )
    _finish(recovery)
    recovered = _wait_file(recover_out)
    assert recovered["counts"]["runs"] == 1
    replacement_token = recovered["token"]
    assert replacement_token and replacement_token != holder_token

    stored = _task_row(db_path, "task-restart")
    assert stored["status"] == "running"
    assert stored["attempt"] == 2, "restart recovery must not refund the attempt"
    assert stored["worker_id"] == "replacement"

    complete_out = tmp_path / "complete.json"
    completed = _spawn(
        db_path,
        "complete",
        out=complete_out,
        task="task-restart",
        worker="replacement",
        token=replacement_token,
        result="only once",
    )
    _finish(completed)
    assert _wait_file(complete_out)["ok"] is True

    # A second restart sees a completed run and must leave it alone.
    again_out = tmp_path / "again.json"
    again = _spawn(db_path, "interrupt", out=again_out)
    _finish(again)
    _wait_file(again_out)

    stored = _task_row(db_path, "task-restart")
    assert stored["status"] == "completed"
    assert stored["result"] == "only once"
    assert stored["attempt"] == 2
    run = _run_row(db_path, "run-restart")
    assert run["status"] == "completed"

    conn = _connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM bot_group_run_tasks").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM bot_group_run_tasks WHERE status='completed'"
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()
