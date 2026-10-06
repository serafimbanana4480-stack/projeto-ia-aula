"""Log storage with in-memory ring buffer and SQLite persistence.

Provides fast recent-log access via an in-memory ring buffer,
plus long-term querying via SQLite. Designed for high throughput
from multiple async agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RING_BUFFER_SIZE = 10_000
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nexus.db"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@contextmanager
def _get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_table() -> None:
    """Create the structured_logs table if it does not exist."""
    try:
        with _get_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS structured_logs (
                    id          TEXT PRIMARY KEY,
                    timestamp   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    level       TEXT NOT NULL,
                    message     TEXT NOT NULL,
                    agent       TEXT,
                    session_id  TEXT,
                    task_id     TEXT,
                    extra_json  TEXT,
                    correlation_id TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_session ON structured_logs(session_id, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_agent ON structured_logs(agent, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_level ON structured_logs(level, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_time ON structured_logs(timestamp DESC)"
            )
    except Exception as exc:
        logger.warning("Failed to ensure structured_logs table: %s", exc)


class LogStore:
    """In-memory ring buffer + SQLite persistence for structured logs."""

    #: Hard cap on in-flight persist tasks.  ``insert()`` is called once per log
    #: line; without a cap a burst of logging can spawn an unbounded number of
    #: threads in the default executor and exhaust memory.
    MAX_INFLIGHT_PERSISTS = 512

    def __init__(self, ring_size: int = RING_BUFFER_SIZE) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=ring_size)
        self._lock = asyncio.Lock()
        self._initialized = False
        # Strong references to the persist tasks.  ``asyncio.create_task``
        # returns an object the event loop only weakly references, so without
        # this set a task can be garbage-collected mid-flight (losing the log
        # line) and nothing is ever inspected for failure.
        self._persist_tasks: set[asyncio.Task[None]] = set()
        self._dropped_persists = 0

    async def _init(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        await asyncio.to_thread(_ensure_table)

    @property
    def inflight_persists(self) -> int:
        """Number of persist tasks currently running (diagnostics/tests)."""
        return len(self._persist_tasks)

    @property
    def dropped_persists(self) -> int:
        """Persists skipped because the in-flight cap was reached."""
        return self._dropped_persists

    def _schedule_persist(self, entry: dict[str, Any]) -> bool:
        """Persist *entry* in the background, supervised.

        Keeps a strong reference, attaches a done-callback that logs failures
        and removes the reference, and refuses new work past
        :attr:`MAX_INFLIGHT_PERSISTS` so a log storm cannot exhaust the default
        thread pool.  Returns ``False`` when the write was dropped.
        """
        if len(self._persist_tasks) >= self.MAX_INFLIGHT_PERSISTS:
            self._dropped_persists += 1
            if self._dropped_persists == 1 or self._dropped_persists % 1000 == 0:
                logger.warning(
                    "Dropped %d structured-log persist(s): %d already in flight",
                    self._dropped_persists,
                    len(self._persist_tasks),
                )
            return False
        try:
            task = asyncio.create_task(self._persist(entry))
        except RuntimeError as exc:  # no running loop
            logger.debug("Log persistence skipped (no event loop): %s", exc)
            return False
        self._persist_tasks.add(task)
        task.add_done_callback(self._on_persist_done)
        return True

    def _on_persist_done(self, task: asyncio.Task[None]) -> None:
        self._persist_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            # Never swallow silently: an unobserved persist failure is how a
            # dead log sink goes unnoticed for weeks.
            logger.error("Structured log persistence failed: %s", exc, exc_info=exc)

    async def insert(
        self,
        level: str,
        message: str,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        extra: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert a log entry into both ring buffer and SQLite."""
        await self._init()

        entry = {
            "id": uuid.uuid4().hex[:16],
            "timestamp": _now_iso(),
            "level": level.upper(),
            "message": message,
            "agent": agent,
            "session_id": session_id,
            "task_id": task_id,
            "extra": extra or {},
            "correlation_id": correlation_id,
        }

        async with self._lock:
            self._buffer.append(entry)

        # Persist asynchronously without blocking the caller.  The task is
        # supervised (strong reference + done-callback); the previous bare
        # ``create_task`` could be collected mid-flight and never reported a
        # failure.
        self._schedule_persist(entry)
        return entry

    async def drain(self, timeout: float = 5.0) -> None:
        """Wait for in-flight persist tasks (used on shutdown and in tests)."""
        pending = list(self._persist_tasks)
        if not pending:
            return
        await asyncio.wait(pending, timeout=timeout)

    async def _persist(self, entry: dict[str, Any]) -> None:
        """Persist a single entry to SQLite (background task)."""
        try:
            await asyncio.to_thread(self._sync_persist, entry)
        except Exception as exc:
            logger.debug("Log persistence failed (non-critical): %s", exc)

    def _sync_persist(self, entry: dict[str, Any]) -> None:
        with _get_db() as conn:
            conn.execute(
                """
                INSERT INTO structured_logs
                (id, timestamp, level, message, agent, session_id, task_id, extra_json, correlation_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["id"],
                    entry["timestamp"],
                    entry["level"],
                    entry["message"],
                    entry["agent"],
                    entry["session_id"],
                    entry["task_id"],
                    json.dumps(entry["extra"], default=str),
                    entry["correlation_id"],
                ),
            )

    async def get_recent(
        self,
        limit: int = 100,
        session_id: str | None = None,
        agent: str | None = None,
        level: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent logs from the in-memory ring buffer."""
        async with self._lock:
            logs = list(self._buffer)

        if session_id:
            logs = [entry for entry in logs if entry.get("session_id") == session_id]
        if agent:
            logs = [entry for entry in logs if entry.get("agent") == agent]
        if level:
            logs = [entry for entry in logs if entry.get("level") == level.upper()]

        return logs[-limit:]

    async def query(
        self,
        session_id: str | None = None,
        agent: str | None = None,
        level: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query SQLite for historical logs with filters."""
        await self._init()

        conditions: list[str] = []
        params: list[Any] = []

        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if level:
            conditions.append("level = ?")
            params.append(level.upper())
        if since:
            conditions.append("timestamp >= ?")
            params.append(since.isoformat())
        if until:
            conditions.append("timestamp <= ?")
            params.append(until.isoformat())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query_sql = f"""
            SELECT * FROM structured_logs
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        def _run() -> list[dict[str, Any]]:
            with _get_db() as conn:
                rows = conn.execute(query_sql, tuple(params)).fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    try:
                        d["extra"] = json.loads(d.pop("extra_json", "{}"))
                    except json.JSONDecodeError:
                        d["extra"] = {}
                    results.append(d)
                return results

        return await asyncio.to_thread(_run)

    async def count_by_level(
        self,
        since: datetime | None = None,
    ) -> dict[str, int]:
        """Aggregate log counts by level."""
        await self._init()

        params: list[Any] = []
        where_clause = ""
        if since:
            where_clause = "WHERE timestamp >= ?"
            params.append(since.isoformat())

        sql = f"""
            SELECT level, COUNT(*) as cnt
            FROM structured_logs
            {where_clause}
            GROUP BY level
        """

        def _run() -> dict[str, int]:
            with _get_db() as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
                return {row["level"]: row["cnt"] for row in rows}

        return await asyncio.to_thread(_run)

    async def get_error_patterns(
        self,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return frequently occurring error messages."""
        await self._init()

        params: list[Any] = []
        where_clause = "WHERE level IN ('ERROR', 'CRITICAL')"
        if since:
            where_clause += " AND timestamp >= ?"
            params.append(since.isoformat())

        sql = f"""
            SELECT message, COUNT(*) as cnt, MAX(timestamp) as last_seen
            FROM structured_logs
            {where_clause}
            GROUP BY message
            ORDER BY cnt DESC
            LIMIT ?
        """
        params.append(limit)

        def _run() -> list[dict[str, Any]]:
            with _get_db() as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [dict(r) for r in rows]

        return await asyncio.to_thread(_run)

    async def prune_old_logs(self, days: int = 30) -> int:
        """Remove logs older than N days. Returns number of rows deleted."""
        await self._init()
        # Simple date math: we rely on SQLite for the actual comparison
        from datetime import timedelta

        cutoff_dt = datetime.now(UTC) - timedelta(days=days)
        cutoff_iso = cutoff_dt.isoformat()

        def _run() -> int:
            with _get_db() as conn:
                cursor = conn.execute(
                    "DELETE FROM structured_logs WHERE timestamp < ?",
                    (cutoff_iso,),
                )
                return cursor.rowcount

        return await asyncio.to_thread(_run)


#: Global singleton
_log_store: LogStore | None = None

#: How often the retention sweep runs, and how much history it keeps.
PRUNE_INTERVAL_SECONDS = 6 * 3600
PRUNE_RETENTION_DAYS = 30


def _read_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(float(raw))
    except ValueError:
        logger.warning("Invalid %s=%r — using %d", name, raw, default)
        return default
    return max(1, value)


async def prune_logs_forever(interval_seconds: int | None = None) -> None:
    """Supervised retention sweep for ``structured_logs``.

    ``prune_old_logs`` existed but was called from nowhere, so the table grew
    without bound.  This loop is the caller: it runs once at startup and then on
    a timer, logs its own failures, and stops cleanly on cancellation.
    """
    interval = interval_seconds or _read_int_env(
        "NEXUS_LOG_PRUNE_INTERVAL_SECONDS", PRUNE_INTERVAL_SECONDS
    )
    retention_days = _read_int_env("NEXUS_LOG_RETENTION_DAYS", PRUNE_RETENTION_DAYS)
    store = get_log_store()
    while True:
        try:
            removed = await store.prune_old_logs(days=retention_days)
            if removed:
                logger.info(
                    "Pruned %d structured log(s) older than %d day(s)",
                    removed,
                    retention_days,
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - the sweep must never die
            logger.exception("Structured log retention sweep failed")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


def get_log_store() -> LogStore:
    """Get or create the global log store singleton."""
    global _log_store
    if _log_store is None:
        _log_store = LogStore()
    return _log_store
