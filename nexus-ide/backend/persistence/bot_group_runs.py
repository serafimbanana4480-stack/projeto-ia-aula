"""Durable, owner-scoped bot group executions."""
from __future__ import annotations

import json
import sqlite3
from typing import Any
from uuid import uuid4

from backend.persistence.db import get_db


class ActiveGroupRun(RuntimeError):
    """The group already has a durable execution in flight."""


def _ensure_idle(conn: sqlite3.Connection, owner: str, group_id: str) -> None:
    conn.execute("BEGIN IMMEDIATE")
    active = conn.execute(
        """SELECT 1 FROM bot_group_runs WHERE user_id=? AND group_id=?
           AND status IN ('pending', 'running') LIMIT 1""",
        (owner, group_id),
    ).fetchone()
    if active:
        raise ActiveGroupRun


def create(owner: str, group_id: str, request: str, root: str, path: str,
           profiles: list[dict[str, Any]]) -> str:
    run_id = uuid4().hex
    with get_db() as conn:
        _ensure_idle(conn, owner, group_id)
        conn.execute(
            """INSERT INTO bot_group_runs
               (id, group_id, user_id, request, project_root, file_path, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (run_id, group_id, owner, request, root, path),
        )
        for position, profile in enumerate(profiles):
            task_id = uuid4().hex
            conn.execute(
                """INSERT INTO bot_group_run_tasks
                   (id, run_id, position, bot_id, bot_name, provider, model, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (task_id, run_id, position, profile["id"], profile["name"],
                 profile["provider"], profile["model"]),
            )
            conn.execute(
                "INSERT INTO bot_group_run_task_prompts (task_id, instructions) VALUES (?, ?)",
                (task_id, profile.get("instructions", "")),
            )
    return run_id


def _load(
    conn: sqlite3.Connection, rows: list[sqlite3.Row], *, include_evidence: bool, worker: bool,
) -> list[dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for row in rows:
        runs[row["id"]] = {**dict(row), "tasks": [], "records": []}
    if not runs:
        return []
    placeholders = ",".join("?" for _ in runs)
    result_column = "t.result" if include_evidence else "NULL AS result"
    for row in conn.execute(
        f"""SELECT t.id, t.run_id, t.position, t.bot_id, t.bot_name, t.provider, t.model,
            t.status, {result_column}, t.error, p.instructions FROM bot_group_run_tasks t
            LEFT JOIN bot_group_run_task_prompts p ON t.id=p.task_id
            WHERE t.run_id IN ({placeholders}) ORDER BY t.position""",
        tuple(runs),
    ):
        task = dict(row)
        if not worker:
            task["has_snapshot"] = task.pop("instructions") is not None
        runs[row["run_id"]]["tasks"].append(task)
    if include_evidence:
        for row in conn.execute(
            f"SELECT * FROM bot_group_run_records WHERE run_id IN ({placeholders}) ORDER BY rowid",
            tuple(runs),
        ):
            runs[row["run_id"]]["records"].append({**dict(row), "payload": json.loads(row["payload"])})
    for run in runs.values():
        tasks = run["tasks"]
        run["can_resume"] = (
            run["status"] in ("interrupted", "failed")
            and bool(tasks)
            and all(task.get("has_snapshot", task.get("instructions") is not None) for task in tasks)
        )
        for task in tasks:
            task.pop("has_snapshot", None)
    return list(runs.values())


_PUBLIC_RUN = "id, group_id, request, project_root, file_path, status, created_at"


def get(owner: str, group_id: str, run_id: str, *, worker: bool = False) -> dict[str, Any] | None:
    with get_db() as conn:
        conn.execute("BEGIN")  # task state and records belong to one snapshot
        rows = conn.execute(
            f"SELECT {_PUBLIC_RUN} FROM bot_group_runs WHERE id=? AND group_id=? AND user_id=?",
            (run_id, group_id, owner),
        ).fetchall()
        return next(iter(_load(conn, rows, include_evidence=True, worker=worker)), None)


def status(owner: str, group_id: str, run_id: str) -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM bot_group_runs WHERE id=? AND group_id=? AND user_id=?",
            (run_id, group_id, owner),
        ).fetchone()
        return str(row["status"]) if row is not None else None


def list_runs(owner: str, group_id: str, *, include_evidence: bool = True) -> list[dict[str, Any]]:
    with get_db() as conn:
        conn.execute("BEGIN")
        rows = conn.execute(
            f"""SELECT {_PUBLIC_RUN} FROM bot_group_runs WHERE user_id=? AND group_id=?
                ORDER BY rowid DESC LIMIT 50""",
            (owner, group_id),
        ).fetchall()
        return _load(conn, rows, include_evidence=include_evidence, worker=False)


def resume(owner: str, group_id: str, run_id: str) -> bool:
    """Reserve one retry atomically; committed work remains available to the worker."""
    with get_db() as conn:
        _ensure_idle(conn, owner, group_id)
        claimed = conn.execute(
            """UPDATE bot_group_runs SET status='pending'
               WHERE id=? AND group_id=? AND user_id=? AND status IN ('interrupted', 'failed')
               AND EXISTS (SELECT 1 FROM bot_group_run_tasks WHERE run_id=bot_group_runs.id)
               AND NOT EXISTS (
                   SELECT 1 FROM bot_group_run_tasks t LEFT JOIN bot_group_run_task_prompts p
                   ON t.id=p.task_id WHERE t.run_id=bot_group_runs.id AND p.task_id IS NULL
               )""",
            (run_id, group_id, owner),
        ).rowcount
        if not claimed:
            return False
        conn.execute(
            """UPDATE bot_group_run_tasks SET status='pending', result=NULL, error=NULL
               WHERE run_id=? AND status!='completed'""",
            (run_id,),
        )
        return True


def set_run(run_id: str, status: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE bot_group_runs SET status=? WHERE id=?", (status, run_id))


def set_task(task_id: str, status: str, result: str | None = None, error: str | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE bot_group_run_tasks SET status=?, result=?, error=? WHERE id=?",
            (status, result, error, task_id),
        )
        if status == "failed":
            conn.execute(
                """INSERT INTO bot_group_run_records (id, run_id, task_id, kind, payload)
                   SELECT ?, run_id, id, 'attempt_failed', ? FROM bot_group_run_tasks WHERE id=?""",
                (uuid4().hex, json.dumps({"error": error}, ensure_ascii=False), task_id),
            )


def finish(run_id: str, status: str, unfinished: str, detail: str) -> None:
    with get_db() as conn:
        changed = conn.execute(
            "UPDATE bot_group_runs SET status=? WHERE id=? AND status IN ('pending', 'running')",
            (status, run_id),
        ).rowcount
        if not changed:
            return
        conn.execute(
            """UPDATE bot_group_run_tasks SET status=?, error=?
               WHERE run_id=? AND status IN ('pending', 'running')""",
            (unfinished, detail, run_id),
        )


def record(run_id: str, task_id: str, kind: str, payload: dict[str, Any]) -> str:
    record_id = uuid4().hex
    with get_db() as conn:
        conn.execute("INSERT INTO bot_group_run_records (id, run_id, task_id, kind, payload) VALUES (?, ?, ?, ?, ?)", (record_id, run_id, task_id, kind, json.dumps(payload, ensure_ascii=False)))
    return record_id


def interrupt_unfinished() -> None:
    with get_db() as conn:
        conn.execute("UPDATE bot_group_run_tasks SET status='interrupted', error='Backend reiniciado antes da conclusão.' WHERE status IN ('pending', 'running') AND run_id IN (SELECT id FROM bot_group_runs WHERE status IN ('pending', 'running'))")
        conn.execute("UPDATE bot_group_runs SET status='interrupted' WHERE status IN ('pending', 'running')")
