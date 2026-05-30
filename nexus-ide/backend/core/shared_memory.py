"""Shared Memory Space — digital whiteboard for NEXUS IDE agents.

All agents write discoveries to a central SQLite-backed whiteboard so that
knowledge is shared across the swarm.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.persistence.db import get_db

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────────────────────


class WhiteboardEntry(BaseModel):
    """A single discovery written to the shared whiteboard."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    topic: str = Field(min_length=1, max_length=256)
    author_agent: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    related_entries: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# DB initialisation
# ──────────────────────────────────────────────────────────────────────────────


def _init_whiteboard_db() -> None:
    """Create whiteboard tables if they do not exist."""
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whiteboard_entries (
                entry_id         TEXT PRIMARY KEY,
                topic            TEXT NOT NULL,
                author_agent     TEXT NOT NULL,
                content          TEXT NOT NULL,
                timestamp        TEXT NOT NULL,
                importance       REAL NOT NULL DEFAULT 0.5
                    CHECK (importance >= 0.0 AND importance <= 1.0),
                tags             TEXT NOT NULL DEFAULT '[]',
                related_entries  TEXT NOT NULL DEFAULT '[]',
                archived         INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whiteboard_entry_links (
                id              TEXT PRIMARY KEY,
                entry_id_1      TEXT NOT NULL,
                entry_id_2      TEXT NOT NULL,
                relation_type   TEXT NOT NULL DEFAULT 'related',
                created_at      TEXT NOT NULL,
                UNIQUE(entry_id_1, entry_id_2, relation_type)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wb_topic ON whiteboard_entries(topic)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wb_author ON whiteboard_entries(author_agent)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wb_timestamp ON whiteboard_entries(timestamp)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wb_archived ON whiteboard_entries(archived)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wb_links_1 ON whiteboard_entry_links(entry_id_1)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wb_links_2 ON whiteboard_entry_links(entry_id_2)"
        )


# ──────────────────────────────────────────────────────────────────────────────
# SharedMemory
# ──────────────────────────────────────────────────────────────────────────────


class SharedMemory:
    """Singleton manager for the agent whiteboard.

    Usage::

        shm = get_shared_memory()
        entry = shm.write_entry("CODER", "code.change", "Fixed bug in api.py")
        entries = shm.read_entries(topic="code.change", limit=10)
    """

    _instance: SharedMemory | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> SharedMemory:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    _init_whiteboard_db()
        return cls._instance

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def write_entry(
        self,
        agent_name: str,
        topic: str,
        content: str,
        importance: float = 0.5,
        tags: list[str] | None = None,
        related_entries: list[str] | None = None,
    ) -> WhiteboardEntry:
        """Write a new entry to the whiteboard."""
        entry = WhiteboardEntry(
            topic=topic,
            author_agent=agent_name,
            content=content,
            importance=importance,
            tags=tags or [],
            related_entries=related_entries or [],
        )
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO whiteboard_entries
                (entry_id, topic, author_agent, content, timestamp,
                 importance, tags, related_entries, archived)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.topic,
                    entry.author_agent,
                    entry.content,
                    entry.timestamp.isoformat(),
                    entry.importance,
                    json.dumps(entry.tags),
                    json.dumps(entry.related_entries),
                    0,
                ),
            )
        logger.info(
            "Whiteboard entry %s written by %s on %s",
            entry.entry_id,
            agent_name,
            topic,
        )
        return entry

    def read_entries(
        self,
        topic: str | None = None,
        agent: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        since: datetime | None = None,
    ) -> list[WhiteboardEntry]:
        """Read whiteboard entries with optional filtering."""
        conditions = ["archived = 0"]
        params: list[Any] = []

        if topic:
            conditions.append("topic = ?")
            params.append(topic)
        if agent:
            conditions.append("author_agent = ?")
            params.append(agent)
        if since:
            conditions.append("timestamp > ?")
            params.append(since.isoformat())

        where_clause = " AND ".join(conditions)

        with get_db() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM whiteboard_entries
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()

        results: list[WhiteboardEntry] = []
        for row in rows:
            entry = self._row_to_entry(row)
            if tags:
                if not any(t in entry.tags for t in tags):
                    continue
            results.append(entry)
        return results[:limit]

    def search_entries(self, query: str, limit: int = 20) -> list[WhiteboardEntry]:
        """Full-text search across topics, authors, content and tags."""
        query_lower = query.lower()
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM whiteboard_entries
                WHERE archived = 0
                ORDER BY timestamp DESC
                """,
            ).fetchall()

        scored: list[tuple[float, WhiteboardEntry]] = []
        for row in rows:
            entry = self._row_to_entry(row)
            score = 0.0
            if query_lower in entry.topic.lower():
                score += 3.0
            if query_lower in entry.author_agent.lower():
                score += 1.0
            if query_lower in entry.content.lower():
                score += 2.0
            for tag in entry.tags:
                if query_lower in tag.lower():
                    score += 2.5
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def link_entries(
        self,
        entry_id_1: str,
        entry_id_2: str,
        relation_type: str = "related",
    ) -> bool:
        """Create a bidirectional link between two whiteboard entries."""
        if entry_id_1 == entry_id_2:
            return False
        e1, e2 = sorted([entry_id_1, entry_id_2])
        with get_db() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO whiteboard_entry_links
                    (id, entry_id_1, entry_id_2, relation_type, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex[:16],
                        e1,
                        e2,
                        relation_type,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def get_thread(self, entry_id: str) -> list[WhiteboardEntry]:
        """Return an entry and all related entries recursively."""
        entry = self._get_entry_by_id(entry_id)
        if entry is None:
            return []

        visited: set[str] = set()
        queue = [entry_id]
        results: list[WhiteboardEntry] = []

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)

            current = self._get_entry_by_id(current_id)
            if current is None:
                continue
            results.append(current)

            for related in current.related_entries:
                if related not in visited:
                    queue.append(related)

            for linked in self._get_linked_entries(current_id):
                if linked not in visited:
                    queue.append(linked)

        results.sort(key=lambda e: e.timestamp)
        return results

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def archive_old_entries(
        self,
        days: int = 30,
        max_importance: float = 0.3,
    ) -> int:
        """Archive entries older than *days* with importance below *max_importance*.

        Returns the number of entries archived.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with get_db() as conn:
            cursor = conn.execute(
                """
                UPDATE whiteboard_entries
                SET archived = 1
                WHERE timestamp < ? AND importance < ? AND archived = 0
                """,
                (cutoff, max_importance),
            )
            archived = cursor.rowcount
        logger.info(
            "Archived %d whiteboard entries older than %d days with importance < %.2f",
            archived,
            days,
            max_importance,
        )
        return archived

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_entry(self, row: sqlite3.Row) -> WhiteboardEntry:
        return WhiteboardEntry(
            entry_id=row["entry_id"],
            topic=row["topic"],
            author_agent=row["author_agent"],
            content=row["content"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            importance=row["importance"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            related_entries=json.loads(row["related_entries"])
            if row["related_entries"]
            else [],
        )

    def _get_entry_by_id(self, entry_id: str) -> WhiteboardEntry | None:
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT * FROM whiteboard_entries
                WHERE entry_id = ? AND archived = 0
                """,
                (entry_id,),
            ).fetchone()
            if row:
                return self._row_to_entry(row)
            return None

    def _get_linked_entries(self, entry_id: str) -> list[str]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT entry_id_1, entry_id_2 FROM whiteboard_entry_links
                WHERE entry_id_1 = ? OR entry_id_2 = ?
                """,
                (entry_id, entry_id),
            ).fetchall()
        results: list[str] = []
        for row in rows:
            other = (
                row["entry_id_2"]
                if row["entry_id_1"] == entry_id
                else row["entry_id_1"]
            )
            results.append(other)
        return results


# ──────────────────────────────────────────────────────────────────────────────
# Convenience accessor
# ──────────────────────────────────────────────────────────────────────────────


def get_shared_memory() -> SharedMemory:
    """Return the singleton :class:`SharedMemory` instance."""
    return SharedMemory()
