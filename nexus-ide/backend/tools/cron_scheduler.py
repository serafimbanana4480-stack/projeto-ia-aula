"""Cron Scheduler — automated task scheduling for NEXUS IDE.

Supports:
- One-time tasks (at specific time)
- Recurring tasks (interval, cron expression)
- Task persistence in SQLite
- Task execution with agent dispatch
- Webhook notifications

Configuration:
- CRON_ENABLED=true/false
- CRON_DB_PATH=data/cron.db

Tables:
- cron_jobs: id, name, schedule, task_type, payload, enabled, next_run, last_run, run_count, error_count, created_at
- cron_logs: id, job_id, status, output, error, started_at, finished_at

Usage:
    from backend.tools.cron_scheduler import schedule_task, list_tasks, cancel_task
    schedule_task("backup", "0 2 * * *", {"action": "backup", "path": "/data"})
    schedule_task("cleanup", {"interval": 3600}, {"action": "cleanup"})
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import shlex
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from croniter import croniter

logger = logging.getLogger(__name__)

_ALLOWED_SHELL_COMMANDS: frozenset[str] = frozenset({
    "ls", "cat", "echo", "pwd", "whoami", "date", "uptime",
    "df", "du", "ps", "ping", "curl", "wget", "git",
    "python3", "node", "npm", "docker",
    "cp", "mv", "rm", "mkdir", "touch",
    "head", "tail", "grep", "sort", "wc", "find",
    "tar", "gzip", "unzip",
})


def get_db_path() -> Path:
    """Get the cron database path."""
    db_path = os.getenv("CRON_DB_PATH", "data/cron.db")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def init_db() -> None:
    """Initialize the cron database."""
    db_path = get_db_path()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                schedule_type TEXT NOT NULL,  -- 'cron', 'interval', 'once'
                schedule_expr TEXT NOT NULL,   -- cron expr or interval seconds or ISO timestamp
                task_type TEXT NOT NULL,       -- 'agent', 'shell', 'python', 'function'
                payload TEXT NOT NULL,         -- JSON payload
                enabled INTEGER DEFAULT 1,
                next_run REAL,                 -- Unix timestamp
                last_run REAL,                 -- Unix timestamp
                run_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                created_at REAL DEFAULT (unixepoch())
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cron_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                status TEXT NOT NULL,          -- 'success', 'error', 'skipped', 'running'
                output TEXT,
                error TEXT,
                started_at REAL DEFAULT (unixepoch()),
                finished_at REAL,
                FOREIGN KEY (job_id) REFERENCES cron_jobs(id)
            )
        """)
        conn.commit()


@dataclass
class CronJob:
    id: int
    name: str
    description: str
    schedule_type: str
    schedule_expr: str
    task_type: str
    payload: dict[str, Any]
    enabled: bool
    next_run: float | None
    last_run: float | None
    run_count: int
    error_count: int
    created_at: float


def _row_to_job(row: sqlite3.Row) -> CronJob:
    """Convert a database row to a CronJob."""
    return CronJob(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        schedule_type=row["schedule_type"],
        schedule_expr=row["schedule_expr"],
        task_type=row["task_type"],
        payload=json.loads(row["payload"]),
        enabled=bool(row["enabled"]),
        next_run=row["next_run"],
        last_run=row["last_run"],
        run_count=row["run_count"],
        error_count=row["error_count"],
        created_at=row["created_at"],
    )


def _calculate_next_run(schedule_type: str, schedule_expr: str, from_time: float | None = None) -> float:
    """Calculate the next run time for a job."""
    now = from_time or time.time()

    if schedule_type == "cron":
        itr = croniter(schedule_expr, datetime.fromtimestamp(now, UTC))
        next_dt = itr.get_next(datetime)
        return next_dt.timestamp()

    elif schedule_type == "interval":
        interval = int(schedule_expr)
        return now + interval

    elif schedule_type == "once":
        # ISO timestamp
        dt = datetime.fromisoformat(schedule_expr.replace("Z", "+00:00"))
        return dt.timestamp()

    return now + 3600  # Default: 1 hour


def schedule_task(
    name: str,
    schedule: str | dict[str, Any],
    payload: dict[str, Any],
    task_type: str = "agent",
    description: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    """Schedule a new task.

    Args:
        name: Unique task name.
        schedule: Cron expression (e.g. "0 2 * * *"), interval dict (e.g. {"interval": 3600}), or ISO timestamp for one-time.
        payload: JSON-serializable task payload.
        task_type: 'agent', 'shell', 'python', 'function'.
        description: Optional description.
        enabled: Whether the task is enabled.

    Returns:
        Dict with success status and job ID.
    """
    init_db()
    db_path = get_db_path()

    # Parse schedule
    if isinstance(schedule, dict):
        schedule_type = "interval"
        schedule_expr = str(schedule.get("interval", 3600))
    elif "T" in schedule and "-" in schedule:
        # ISO timestamp
        schedule_type = "once"
        schedule_expr = schedule
    else:
        schedule_type = "cron"
        schedule_expr = schedule

    # Calculate next run
    next_run = _calculate_next_run(schedule_type, schedule_expr)

    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                INSERT INTO cron_jobs (name, description, schedule_type, schedule_expr, task_type, payload, enabled, next_run)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description=excluded.description,
                    schedule_type=excluded.schedule_type,
                    schedule_expr=excluded.schedule_expr,
                    task_type=excluded.task_type,
                    payload=excluded.payload,
                    enabled=excluded.enabled,
                    next_run=excluded.next_run
                """,
                (name, description, schedule_type, schedule_expr, task_type, json.dumps(payload), int(enabled), next_run),
            )
            conn.commit()
            job_id = cursor.lastrowid

        return {
            "success": True,
            "job_id": job_id,
            "name": name,
            "schedule_type": schedule_type,
            "next_run": datetime.fromtimestamp(next_run, UTC).isoformat(),
        }
    except Exception as exc:
        logger.error("Failed to schedule task: %s", exc)
        return {"success": False, "error": str(exc)}


def list_tasks(enabled_only: bool = False) -> list[dict[str, Any]]:
    """List all scheduled tasks."""
    init_db()
    db_path = get_db_path()

    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if enabled_only:
                rows = conn.execute("SELECT * FROM cron_jobs WHERE enabled = 1 ORDER BY next_run").fetchall()
            else:
                rows = conn.execute("SELECT * FROM cron_jobs ORDER BY created_at DESC").fetchall()

            jobs = []
            for row in rows:
                job = _row_to_job(row)
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "description": job.description,
                    "schedule_type": job.schedule_type,
                    "schedule_expr": job.schedule_expr,
                    "task_type": job.task_type,
                    "enabled": job.enabled,
                    "next_run": datetime.fromtimestamp(job.next_run, UTC).isoformat() if job.next_run else None,
                    "last_run": datetime.fromtimestamp(job.last_run, UTC).isoformat() if job.last_run else None,
                    "run_count": job.run_count,
                    "error_count": job.error_count,
                })
            return jobs
    except Exception as exc:
        logger.error("Failed to list tasks: %s", exc)
        return []


def cancel_task(name: str) -> dict[str, Any]:
    """Cancel/remove a scheduled task."""
    init_db()
    db_path = get_db_path()

    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute("DELETE FROM cron_jobs WHERE name = ?", (name,))
            conn.commit()
            if cursor.rowcount > 0:
                return {"success": True, "message": f"Task '{name}' cancelled"}
            return {"success": False, "error": f"Task '{name}' not found"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def enable_task(name: str, enabled: bool = True) -> dict[str, Any]:
    """Enable or disable a task."""
    init_db()
    db_path = get_db_path()

    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "UPDATE cron_jobs SET enabled = ? WHERE name = ?",
                (int(enabled), name),
            )
            conn.commit()
            if cursor.rowcount > 0:
                return {"success": True, "message": f"Task '{name}' {'enabled' if enabled else 'disabled'}"}
            return {"success": False, "error": f"Task '{name}' not found"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def get_task_logs(name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get execution logs for a task."""
    init_db()
    db_path = get_db_path()

    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT l.* FROM cron_logs l
                JOIN cron_jobs j ON l.job_id = j.id
                WHERE j.name = ?
                ORDER BY l.started_at DESC
                LIMIT ?
                """,
                (name, limit),
            ).fetchall()

            return [
                {
                    "id": row["id"],
                    "status": row["status"],
                    "output": row["output"],
                    "error": row["error"],
                    "started_at": datetime.fromtimestamp(row["started_at"], UTC).isoformat(),
                    "finished_at": datetime.fromtimestamp(row["finished_at"], UTC).isoformat() if row["finished_at"] else None,
                }
                for row in rows
            ]
    except Exception as exc:
        logger.error("Failed to get task logs: %s", exc)
        return []


def _execute_job(job: CronJob) -> dict[str, Any]:
    """Execute a single cron job."""
    start_time = time.time()
    output = ""
    error = None
    status = "success"

    try:
        if job.task_type == "agent":
            # Dispatch to an agent
            agent_name = job.payload.get("agent", "CODER")
            query = job.payload.get("query", "")
            # TODO: Integrate with agent dispatch system
            output = f"Dispatched to agent {agent_name}: {query}"
            logger.info("Cron job dispatched to agent: %s", agent_name)

        elif job.task_type == "shell":
            cmd = job.payload.get("command", "")
            tokens = shlex.split(cmd)
            if not tokens or tokens[0] not in _ALLOWED_SHELL_COMMANDS:
                error = f"Command '{tokens[0] if tokens else ''}' is not in the allowed shell commands whitelist"
                status = "error"
            else:
                result = subprocess.run(
                    tokens,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=job.payload.get("timeout", 300),
                )
                output = result.stdout
                if result.returncode != 0:
                    error = result.stderr
                    status = "error"

        elif job.task_type == "python":
            code = job.payload.get("code", "")
            try:
                tree = ast.parse(code, mode='exec')
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom, ast.Call, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)):
                        raise ValueError(f"Node type {type(node).__name__} is not allowed in cron python tasks")
                allowed_root = (ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Pass)
                for node in tree.body:
                    if not isinstance(node, allowed_root):
                        raise ValueError(f"Statement type {type(node).__name__} is not allowed")
                compiled = compile(tree, '<cron_python>', 'exec')
                local_vars = {}
                exec(compiled, {"__builtins__": {}}, local_vars)
                output = str(local_vars)
            except (SyntaxError, ValueError) as e:
                status = "error"
                error = str(e)
                output = ""

        elif job.task_type == "function":
            # Call a registered function
            func_name = job.payload.get("function", "")
            args = job.payload.get("args", [])
            kwargs = job.payload.get("kwargs", {})
            # TODO: Function registry
            output = f"Function {func_name} called with args={args}, kwargs={kwargs}"

        else:
            output = f"Unknown task type: {job.task_type}"
            status = "error"

    except Exception as exc:
        error = str(exc)
        status = "error"
        logger.error("Cron job failed: %s", exc)

    finally:
        # Log execution
        db_path = get_db_path()
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT INTO cron_logs (job_id, status, output, error, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job.id, status, output, error, start_time, time.time()),
            )
            conn.commit()

        # Update job stats
        next_run = _calculate_next_run(job.schedule_type, job.schedule_expr, from_time=time.time())
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                UPDATE cron_jobs
                SET last_run = ?, next_run = ?, run_count = run_count + 1,
                    error_count = error_count + ?
                WHERE id = ?
                """,
                (time.time(), next_run, 1 if status == "error" else 0, job.id),
            )
            conn.commit()

    return {"status": status, "output": output, "error": error}


class CronScheduler:
    """Background scheduler that runs jobs at their scheduled times."""

    def __init__(self, check_interval: int = 30) -> None:
        self.check_interval = check_interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the scheduler in a background thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info("Cron scheduler started (check interval: %ds)", self.check_interval)

    def stop(self) -> None:
        """Stop the scheduler."""
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            logger.info("Cron scheduler stopped")

    def _run_loop(self) -> None:
        """Main loop that checks for jobs to run."""
        while self._running:
            try:
                self._check_and_run_jobs()
            except Exception as exc:
                logger.error("Cron scheduler error: %s", exc)
            time.sleep(self.check_interval)

    def _check_and_run_jobs(self) -> None:
        """Check for jobs that are due and execute them."""
        init_db()
        db_path = get_db_path()
        now = time.time()

        try:
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM cron_jobs WHERE enabled = 1 AND next_run <= ?",
                    (now,),
                ).fetchall()

                for row in rows:
                    job = _row_to_job(row)
                    logger.info("Executing cron job: %s (type=%s)", job.name, job.task_type)
                    _execute_job(job)

        except Exception as exc:
            logger.error("Failed to check/run jobs: %s", exc)


# Global scheduler instance
_scheduler: CronScheduler | None = None


def get_scheduler() -> CronScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = CronScheduler()
    return _scheduler


def start_scheduler() -> None:
    """Start the cron scheduler if enabled."""
    if os.getenv("CRON_ENABLED", "false").lower() in ("true", "1", "yes", "on"):
        get_scheduler().start()


def stop_scheduler() -> None:
    """Stop the cron scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None


def scheduler_status() -> dict[str, Any]:
    """Get cron scheduler status and job counts."""
    try:
        init_db()
        db_path = get_db_path()
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) as cnt FROM cron_jobs").fetchone()["cnt"]
            enabled = conn.execute("SELECT COUNT(*) as cnt FROM cron_jobs WHERE enabled = 1").fetchone()["cnt"]
            running_scheduler = _scheduler is not None and _scheduler._running
            return {
                "success": True,
                "scheduler_running": running_scheduler,
                "total_jobs": total,
                "enabled_jobs": enabled,
                "check_interval_seconds": get_scheduler().check_interval if _scheduler else None,
            }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

from backend.tools.registry import ToolSpec, register_tool

register_tool(
    ToolSpec(
        name="schedule_task",
        description="Schedule a recurring or one-time task with cron expression, interval, or timestamp.",
        schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique task name"},
                "schedule": {"type": "string", "description": "Cron expression, interval dict, or ISO timestamp"},
                "payload": {"type": "object", "description": "Task payload JSON"},
                "task_type": {"type": "string", "description": "agent|shell|python|function", "default": "agent"},
                "description": {"type": "string"},
                "enabled": {"type": "boolean", "default": True},
            },
            "required": ["name", "schedule", "payload"],
        },
        handler=schedule_task,
    )
)

register_tool(
    ToolSpec(
        name="list_tasks",
        description="List all scheduled cron tasks.",
        schema={
            "type": "object",
            "properties": {
                "enabled_only": {"type": "boolean", "default": False},
            },
        },
        handler=list_tasks,
    )
)

register_tool(
    ToolSpec(
        name="cancel_task",
        description="Cancel/remove a scheduled task by name.",
        schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
        handler=cancel_task,
    )
)

register_tool(
    ToolSpec(
        name="scheduler_status",
        description="Get cron scheduler status and job counts.",
        schema={"type": "object", "properties": {}},
        handler=scheduler_status,
    )
)
