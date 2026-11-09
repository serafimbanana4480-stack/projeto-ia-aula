"""Durable, owner-scoped two-bot executions."""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from backend.persistence.db import get_db


def create(owner: str, group_id: str, request: str, root: str, path: str,
           profiles: list[dict[str, Any]]) -> str:
    run_id = uuid4().hex
    with get_db() as conn:
        conn.execute("INSERT INTO bot_group_runs (id, group_id, user_id, request, project_root, file_path, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                     (run_id, group_id, owner, request, root, path))
        for position, profile in enumerate(profiles):
            conn.execute("INSERT INTO bot_group_run_tasks (id, run_id, position, bot_id, bot_name, provider, model, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
                         (uuid4().hex, run_id, position, profile['id'], profile['name'], profile['provider'], profile['model']))
    return run_id


def get(owner: str, group_id: str, run_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT id, group_id, request, project_root, file_path, status, created_at FROM bot_group_runs WHERE id=? AND group_id=? AND user_id=?", (run_id, group_id, owner)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['tasks'] = [dict(item) for item in conn.execute("SELECT * FROM bot_group_run_tasks WHERE run_id=? ORDER BY position", (run_id,))]
        result['records'] = [{**dict(item), 'payload': json.loads(item['payload'])} for item in conn.execute("SELECT * FROM bot_group_run_records WHERE run_id=? ORDER BY rowid", (run_id,))]
        return result


def list_runs(owner: str, group_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT id FROM bot_group_runs WHERE user_id=? AND group_id=? ORDER BY rowid DESC LIMIT 50", (owner, group_id)).fetchall()
    return [run for row in rows if (run := get(owner, group_id, row['id'])) is not None]


def set_run(run_id: str, status: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE bot_group_runs SET status=? WHERE id=?", (status, run_id))


def set_task(task_id: str, status: str, result: str | None = None, error: str | None = None) -> None:
    with get_db() as conn:
        conn.execute("UPDATE bot_group_run_tasks SET status=?, result=?, error=? WHERE id=?", (status, result, error, task_id))


def record(run_id: str, task_id: str, kind: str, payload: dict[str, Any]) -> str:
    record_id = uuid4().hex
    with get_db() as conn:
        conn.execute("INSERT INTO bot_group_run_records (id, run_id, task_id, kind, payload) VALUES (?, ?, ?, ?, ?)", (record_id, run_id, task_id, kind, json.dumps(payload, ensure_ascii=False)))
    return record_id


def interrupt_unfinished() -> None:
    with get_db() as conn:
        conn.execute("UPDATE bot_group_run_tasks SET status='interrupted', error='Backend reiniciado antes da conclusão.' WHERE status IN ('pending', 'running') AND run_id IN (SELECT id FROM bot_group_runs WHERE status IN ('pending', 'running'))")
        conn.execute("UPDATE bot_group_runs SET status='interrupted' WHERE status IN ('pending', 'running')")
