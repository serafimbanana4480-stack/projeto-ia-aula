"""Persistent memory store backed by SQLite.

Extends :class:`MemoryStore` so that every stored memory is written to SQLite
and reloaded on process restart. All metadata fields are preserved, including
``session_id``, ``project_id``, ``file_path``, ``language`` and relations.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any

from backend.knowledge.memory import EmbeddingService, Memory, MemoryStore, MemoryType
from backend.persistence.db import DB_PATH

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS persistent_memories (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    session_id TEXT,
    project_id TEXT,
    content TEXT NOT NULL,
    summary TEXT,
    embedding_json TEXT,
    memory_type TEXT,
    tags TEXT,
    source TEXT,
    file_path TEXT,
    language TEXT,
    related_memory_ids TEXT,
    importance REAL,
    created_at REAL,
    last_accessed_at REAL,
    access_count INTEGER DEFAULT 0
);
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pm_user ON persistent_memories(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_pm_session ON persistent_memories(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_pm_project ON persistent_memories(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_pm_type ON persistent_memories(memory_type)",
    "CREATE INDEX IF NOT EXISTS idx_pm_created ON persistent_memories(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pm_source ON persistent_memories(source)",
]


class PersistentMemoryStore(MemoryStore):
    """High-level memory management with SQLite persistence.

    Inherits from :class:`MemoryStore` and overrides storage/retrieval so that
    all writes are mirrored to SQLite and existing rows are loaded on startup.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        *,
        max_memories: int = 10_000,
    ) -> None:
        super().__init__(embedding_service=embedding_service, max_memories=max_memories)
        self._ensure_schema()
        self._load_from_db()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(_CREATE_TABLE_SQL)
            # Backwards-compatible migrations must run before creating indexes
            # that reference the newly-added columns.
            self._migrate_schema(conn)
            for idx_sql in _INDEXES:
                conn.execute(idx_sql)
            conn.commit()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Add columns that may be missing from older schemas."""
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(persistent_memories)").fetchall()
        }
        additions = [
            ("session_id", "TEXT"),
            ("project_id", "TEXT"),
            ("file_path", "TEXT"),
            ("language", "TEXT"),
            ("related_memory_ids", "TEXT"),
        ]
        for col, dtype in additions:
            if col not in columns:
                conn.execute(f"ALTER TABLE persistent_memories ADD COLUMN {col} {dtype}")
                logger.info("Migrated persistent_memories: added %s", col)

    def _save_memory(self, memory: Memory, user_id: str = "") -> None:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO persistent_memories
                   (id, user_id, session_id, project_id, content, summary, embedding_json,
                    memory_type, tags, source, file_path, language, related_memory_ids,
                    importance, created_at, last_accessed_at, access_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory.memory_id,
                    user_id,
                    memory.session_id,
                    memory.project_id,
                    memory.content,
                    memory.summary,
                    json.dumps(memory.embedding),
                    memory.memory_type.value,
                    json.dumps(memory.tags),
                    memory.source,
                    memory.file_path,
                    memory.language,
                    json.dumps(memory.related_memory_ids),
                    memory.importance,
                    memory.created_at,
                    memory.last_accessed_at,
                    memory.access_count,
                ),
            )
            conn.commit()

    def _delete_from_db(self, memory_id: str) -> None:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                "DELETE FROM persistent_memories WHERE id = ?",
                (memory_id,),
            )
            conn.commit()

    def _load_from_db(self) -> None:
        try:
            with sqlite3.connect(str(DB_PATH)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM persistent_memories ORDER BY created_at DESC"
                ).fetchall()

                for row in rows:
                    memory = self._row_to_memory(row)
                    self._memories[memory.memory_id] = memory
                    self._index[memory.memory_id] = memory.embedding

                if rows:
                    logger.info(
                        "Loaded %d persistent memories from DB",
                        len(rows),
                    )
        except Exception as exc:
            logger.warning("Failed to load persistent memories: %s", exc)

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            memory_id=row["id"],
            memory_type=(
                MemoryType(row["memory_type"]) if row["memory_type"] else MemoryType.GLOBAL
            ),
            session_id=row["session_id"] or "",
            project_id=row["project_id"] or "",
            content=row["content"] or "",
            summary=row["summary"] or "",
            embedding=(json.loads(row["embedding_json"]) if row["embedding_json"] else []),
            tags=(json.loads(row["tags"]) if row["tags"] else []),
            source=row["source"] or "",
            file_path=row["file_path"] or "",
            language=row["language"] or "",
            related_memory_ids=(
                json.loads(row["related_memory_ids"]) if row["related_memory_ids"] else []
            ),
            importance=(row["importance"] if row["importance"] is not None else 0.5),
            created_at=(row["created_at"] if row["created_at"] is not None else time.time()),
            last_accessed_at=(
                row["last_accessed_at"] if row["last_accessed_at"] is not None else time.time()
            ),
            access_count=(row["access_count"] if row["access_count"] is not None else 0),
        )

    # ------------------------------------------------------------------
    # Public API (overrides MemoryStore to add persistence)
    # ------------------------------------------------------------------

    async def store(
        self,
        content: str,
        *,
        memory_type: MemoryType = MemoryType.SESSION,
        session_id: str = "",
        project_id: str = "",
        user_id: str = "",
        tags: list[str] | None = None,
        source: str = "",
        summary: str = "",
        importance: float = 0.5,
        file_path: str = "",
        language: str = "",
        related_memory_ids: list[str] | None = None,
    ) -> Memory:
        """Store a new memory and persist it to SQLite."""
        memory = await super().store(
            content,
            memory_type=memory_type,
            session_id=session_id,
            project_id=project_id,
            tags=tags,
            source=source,
            summary=summary,
            importance=importance,
            file_path=file_path,
            language=language,
            related_memory_ids=related_memory_ids,
        )
        self._save_memory(memory, user_id=user_id)
        return memory

    async def delete(self, memory_id: str) -> bool:
        result = await super().delete(memory_id)
        if result:
            self._delete_from_db(memory_id)
        return result

    async def clear_session(self, session_id: str) -> int:
        memories = await self.get_session_memories(session_id)
        count = await super().clear_session(session_id)
        for mem in memories:
            self._delete_from_db(mem.memory_id)
        return count

    def stats(self) -> dict[str, Any]:
        stats = super().stats()
        stats["persistent_db"] = str(DB_PATH)
        return stats
