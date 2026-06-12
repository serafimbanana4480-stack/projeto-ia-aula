"""Persistent memory store backed by SQLite.

Wraps :class:`MemoryStore` so that every stored memory is written to SQLite
and reloaded on process restart.
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
    content TEXT NOT NULL,
    summary TEXT,
    embedding_json TEXT,
    memory_type TEXT,
    tags TEXT,
    source TEXT,
    importance REAL,
    created_at REAL,
    last_accessed_at REAL,
    access_count INTEGER DEFAULT 0
);
"""

_CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_pm_user ON persistent_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_pm_type ON persistent_memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_pm_created ON persistent_memories(created_at DESC);
"""


class PersistentMemoryStore:
    """High-level memory management with SQLite persistence.

    Delegates all search / retrieval to an in-memory :class:`MemoryStore`,
    but loads existing rows from ``persistent_memories`` on construction
    and writes every new memory back to the same table.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        *,
        max_memories: int = 10_000,
    ) -> None:
        self._inner = MemoryStore(
            embedding_service=embedding_service,
            max_memories=max_memories,
        )
        self._ensure_schema()
        self._load_from_db()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_INDEXES_SQL)
            conn.commit()

    def _save_memory(self, memory: Memory, user_id: str = "") -> None:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO persistent_memories
                   (id, user_id, content, summary, embedding_json, memory_type,
                    tags, source, importance, created_at, last_accessed_at, access_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory.memory_id,
                    user_id,
                    memory.content,
                    memory.summary,
                    json.dumps(memory.embedding),
                    memory.memory_type.value,
                    json.dumps(memory.tags),
                    memory.source,
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
                    memory = Memory(
                        memory_id=row["id"],
                        memory_type=(
                            MemoryType(row["memory_type"])
                            if row["memory_type"]
                            else MemoryType.GLOBAL
                        ),
                        content=row["content"] or "",
                        summary=row["summary"] or "",
                        embedding=(
                            json.loads(row["embedding_json"])
                            if row["embedding_json"]
                            else []
                        ),
                        tags=(
                            json.loads(row["tags"])
                            if row["tags"]
                            else []
                        ),
                        source=row["source"] or "",
                        importance=(
                            row["importance"]
                            if row["importance"] is not None
                            else 0.5
                        ),
                        created_at=(
                            row["created_at"]
                            if row["created_at"] is not None
                            else time.time()
                        ),
                        last_accessed_at=(
                            row["last_accessed_at"]
                            if row["last_accessed_at"] is not None
                            else time.time()
                        ),
                        access_count=(
                            row["access_count"]
                            if row["access_count"] is not None
                            else 0
                        ),
                    )
                    self._inner._memories[memory.memory_id] = memory
                    self._inner._index[memory.memory_id] = memory.embedding

                if rows:
                    logger.info(
                        "Loaded %d persistent memories from DB",
                        len(rows),
                    )
        except Exception as exc:
            logger.warning("Failed to load persistent memories: %s", exc)

    # ------------------------------------------------------------------
    # Public API (delegates to _inner, adds persistence)
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
    ) -> Memory:
        """Store a new memory and persist it to SQLite."""
        memory = await self._inner.store(
            content,
            memory_type=memory_type,
            session_id=session_id,
            project_id=project_id,
            tags=tags,
            source=source,
            summary=summary,
            importance=importance,
        )
        self._save_memory(memory, user_id=user_id)
        return memory

    async def search(
        self,
        query: str,
        *,
        session_id: str | None = None,
        memory_type: MemoryType | None = None,
        top_k: int = 10,
        min_similarity: float = 0.3,
    ) -> list[tuple[Memory, float]]:
        return await self._inner.search(
            query,
            session_id=session_id,
            memory_type=memory_type,
            top_k=top_k,
            min_similarity=min_similarity,
        )

    async def get_context(
        self,
        query: str,
        session_id: str = "",
        *,
        max_tokens: int = 4000,
        top_k: int = 5,
    ) -> str:
        return await self._inner.get_context(
            query,
            session_id=session_id,
            max_tokens=max_tokens,
            top_k=top_k,
        )

    async def get_by_tag(self, tag: str, limit: int = 20) -> list[Memory]:
        return await self._inner.get_by_tag(tag, limit=limit)

    async def get_session_memories(self, session_id: str) -> list[Memory]:
        return await self._inner.get_session_memories(session_id)

    async def list_all(self, limit: int = 1000) -> list[Memory]:
        """Return all memories ordered by creation time (newest first)."""
        return await self._inner.list_all(limit=limit)

    async def delete(self, memory_id: str) -> bool:
        result = await self._inner.delete(memory_id)
        if result:
            self._delete_from_db(memory_id)
        return result

    async def clear_session(self, session_id: str) -> int:
        memories = await self._inner.get_session_memories(session_id)
        count = await self._inner.clear_session(session_id)
        for mem in memories:
            self._delete_from_db(mem.memory_id)
        return count

    def stats(self) -> dict[str, Any]:
        return self._inner.stats()
