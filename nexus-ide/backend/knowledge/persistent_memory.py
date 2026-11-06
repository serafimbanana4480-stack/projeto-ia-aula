"""Persistent memory store backed by SQLite.

Extends :class:`MemoryStore` so that every stored memory is written to SQLite
and reloaded on process restart. All metadata fields are preserved, including
``session_id``, ``project_id``, ``file_path``, ``language`` and relations.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.knowledge.memory import EmbeddingService, Memory, MemoryStore, MemoryType
from backend.persistence.db import DB_PATH

logger = logging.getLogger(__name__)

#: The value :data:`DB_PATH` had when this module was imported.  A difference
#: means the attribute was overridden explicitly (the test suite does that).
_INITIAL_DB_PATH = DB_PATH


def _db_path() -> Path:
    """Return the SQLite file the persistent memories are stored in.

    The path used to be bound at import time, so an override of
    ``backend.persistence.db.DB_PATH`` — the one the test fixture installs,
    and the one ``NEXUS_DB_PATH`` produces — was ignored and every memory was
    written to the real database, even under pytest.  Resolving the location
    on every call makes the store follow the same override as the rest of the
    application.

    The order is:

    1. this module's :data:`DB_PATH` when it was overridden explicitly;
    2. ``NEXUS_DB_PATH`` — the same override the persistence layer honours;
    3. ``backend.persistence.db.DB_PATH`` — the database the rest of the
       application uses, read at call time.
    """
    if DB_PATH != _INITIAL_DB_PATH:
        return Path(DB_PATH)
    override = os.environ.get("NEXUS_DB_PATH")
    if override:
        return Path(override).expanduser().resolve()
    from backend.persistence import db as persistence_db

    return Path(persistence_db.DB_PATH)


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
    kind TEXT DEFAULT 'semantic',
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
        db_path = _db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db_path)) as conn:
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
            ("user_id", "TEXT"),
            ("session_id", "TEXT"),
            ("project_id", "TEXT"),
            ("file_path", "TEXT"),
            ("language", "TEXT"),
            ("kind", "TEXT DEFAULT 'semantic'"),
            ("related_memory_ids", "TEXT"),
        ]
        for col, dtype in additions:
            if col not in columns:
                conn.execute(f"ALTER TABLE persistent_memories ADD COLUMN {col} {dtype}")
                logger.info("Migrated persistent_memories: added %s", col)

    def _user_for_session(self, session_id: str) -> str | None:
        """Resolve an owned session to its user without exposing session data."""
        if not session_id:
            return None
        try:
            with sqlite3.connect(str(_db_path())) as conn:
                row = conn.execute(
                    "SELECT user_id FROM sessions WHERE id = ? LIMIT 1",
                    (session_id,),
                ).fetchone()
            return str(row[0]) if row and row[0] else None
        except sqlite3.Error:
            return None

    def _save_memory(
        self,
        memory: Memory,
        user_id: str | None = None,
        *,
        evicted_memory_ids: tuple[str, ...] = (),
    ) -> None:
        owner_id = memory.user_id if user_id is None else user_id
        with sqlite3.connect(str(_db_path())) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO persistent_memories
                   (id, user_id, session_id, project_id, content, summary, embedding_json,
                    memory_type, tags, source, file_path, language, kind, related_memory_ids,
                    importance, created_at, last_accessed_at, access_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory.memory_id,
                    owner_id,
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
                    memory.kind,
                    json.dumps(memory.related_memory_ids),
                    memory.importance,
                    memory.created_at,
                    memory.last_accessed_at,
                    memory.access_count,
                ),
            )
            for memory_id in evicted_memory_ids:
                conn.execute("DELETE FROM persistent_memories WHERE id = ?", (memory_id,))
            conn.commit()

    def _delete_from_db(self, memory_id: str, user_id: str | None = None) -> None:
        with sqlite3.connect(str(_db_path())) as conn:
            if user_id is None:
                conn.execute("DELETE FROM persistent_memories WHERE id = ?", (memory_id,))
            else:
                conn.execute(
                    "DELETE FROM persistent_memories WHERE id = ? AND user_id = ?",
                    (memory_id, user_id),
                )
            conn.commit()

    def _load_from_db(self) -> None:
        try:
            with sqlite3.connect(str(_db_path())) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM persistent_memories ORDER BY created_at DESC"
                ).fetchall()

                loaded_count = 0
                for row in rows:
                    try:
                        memory = self._row_to_memory(row)
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        # One malformed legacy row must not prevent healthy,
                        # older memories later in the ordered result from
                        # being restored after restart. Keep the row in the
                        # canonical database so it can be inspected/repaired.
                        logger.warning(
                            "Skipping malformed persistent memory %s: %s",
                            row["id"],
                            exc,
                        )
                        continue
                    self._memories[memory.memory_id] = memory
                    self._index[memory.memory_id] = memory.embedding
                    loaded_count += 1

                if loaded_count:
                    logger.info(
                        "Loaded %d persistent memories from DB",
                        loaded_count,
                    )
        except Exception as exc:
            logger.warning("Failed to load persistent memories: %s", exc)

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            memory_id=row["id"],
            user_id=str(row["user_id"] or ""),
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
            kind=row["kind"] or "semantic",
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
        kind: str = "semantic",
        related_memory_ids: list[str] | None = None,
    ) -> Memory:
        """Store a new memory and persist it to SQLite."""
        owner_id = user_id or self._user_for_session(session_id) or ""
        memories_before = self._memories.copy()
        index_before = self._index.copy()
        try:
            memory = await super().store(
                content,
                user_id=owner_id,
                memory_type=memory_type,
                session_id=session_id,
                project_id=project_id,
                tags=tags,
                source=source,
                summary=summary,
                importance=importance,
                file_path=file_path,
                language=language,
                kind=kind,
                related_memory_ids=related_memory_ids,
            )
            evicted_ids = tuple(memories_before.keys() - self._memories.keys())
            self._save_memory(memory, evicted_memory_ids=evicted_ids)
        except Exception:
            self._memories = memories_before
            self._index = index_before
            raise
        return memory

    async def delete(self, memory_id: str, *, user_id: str | None = None) -> bool:
        result = await super().delete(memory_id, user_id=user_id)
        if result:
            self._delete_from_db(memory_id, user_id=user_id)
        return result

    async def clear_session(self, session_id: str) -> int:
        memories = await self.get_session_memories(session_id)
        count = await super().clear_session(session_id)
        for mem in memories:
            self._delete_from_db(mem.memory_id)
        return count

    def stats(self, *, user_id: str | None = None) -> dict[str, Any]:
        stats = super().stats(user_id=user_id)
        stats["persistent_db"] = str(_db_path())
        return stats

    async def search(self, *args: Any, **kwargs: Any) -> list[tuple[Memory, float]]:
        """Search and persist access telemetry for the returned memories."""
        if kwargs.get("user_id") is None:
            session_id = str(kwargs.get("session_id") or "")
            if session_id:
                kwargs["user_id"] = self._user_for_session(session_id) or "__unowned_session__"
        results = await super().search(*args, **kwargs)
        for memory, _score in results:
            try:
                self._save_memory(memory)
            except sqlite3.Error as exc:
                # last_accessed_at/access_count improve future eviction but
                # must not make an otherwise successful recall fail when
                # SQLite is briefly busy. The memory content is unchanged.
                logger.warning(
                    "Could not persist access telemetry for memory %s: %s",
                    memory.memory_id,
                    exc,
                )
        return results

    async def get_context(
        self,
        query: str,
        session_id: str = "",
        project_id: str = "",
        *,
        user_id: str | None = None,
        max_tokens: int = 4000,
        top_k: int = 5,
    ) -> str:
        """Build recall context within the owner of the associated session."""
        owner_id = user_id
        if owner_id is None and session_id:
            owner_id = self._user_for_session(session_id) or "__unowned_session__"
        return await super().get_context(
            query,
            session_id=session_id,
            project_id=project_id,
            user_id=owner_id,
            max_tokens=max_tokens,
            top_k=top_k,
        )
