"""Log storage with in-memory ring buffer and SQLite persistence.

Provides fast recent-log access via an in-memory ring buffer,
plus long-term querying via SQLite. Designed for high throughput
from multiple async agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
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

    def __init__(self, ring_size: int = RING_BUFFER_SIZE) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=ring_size)
        self._lock = asyncio.Lock()
        self._initialized = False

    async def _init(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        await asyncio.to_thread(_ensure_table)

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

        # Persist asynchronously without blocking the caller
        asyncio.create_task(self._persist(entry))
        return entry

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
            logs = [l for l in logs if l.get("session_id") == session_id]
        if agent:
            logs = [l for l in logs if l.get("agent") == agent]
        if level:
            logs = [l for l in logs if l.get("level") == level.upper()]

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
        datetime.now(UTC).isoformat().replace("+00:00", "Z")
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


# Global singleton
_log_store: LogStore | None = None


def get_log_store() -> LogStore:
    """Get or create the global log store singleton."""
    global _log_store
    if _log_store is None:
        _log_store = LogStore()
    return _log_store
