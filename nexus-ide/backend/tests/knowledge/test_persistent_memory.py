"""Tests for backend.knowledge.persistent_memory."""

from __future__ import annotations

import sqlite3

import pytest

from backend.knowledge.memory import MemoryType
from backend.knowledge.persistent_memory import PersistentMemoryStore


class TestPersistentMemoryStore:
    @pytest.fixture
    def store(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> PersistentMemoryStore:
        from backend.knowledge import persistent_memory as pm_module
        from backend.knowledge.memory import EmbeddingService

        svc = EmbeddingService()

        async def _fast_embed(text: str) -> list[float]:
            return svc._fallback_embed(text)

        monkeypatch.setattr(svc, "embed", _fast_embed)
        test_db = tmp_path / "test_nexus.db"
        monkeypatch.setattr(pm_module, "DB_PATH", test_db)
        return PersistentMemoryStore(embedding_service=svc, max_memories=100)

    @pytest.mark.asyncio
    async def test_store_and_reload(self, store: PersistentMemoryStore) -> None:
        mem = await store.store(
            "Authentication uses JWT tokens",
            memory_type=MemoryType.PROJECT,
            session_id="s1",
            project_id="proj_1",
            source="ANALYZER",
            tags=["auth", "security"],
            importance=0.8,
            file_path="backend/auth.py",
            language="python",
            kind="episodic",
        )
        assert mem.session_id == "s1"
        assert mem.project_id == "proj_1"
        assert mem.file_path == "backend/auth.py"
        assert mem.kind == "episodic"

        # Simulate restart by loading from DB into a new instance
        new_store = PersistentMemoryStore(
            embedding_service=store._embeddings,
            max_memories=100,
        )
        project_mems = await new_store.get_project_memories("proj_1")
        assert len(project_mems) > 0
        assert project_mems[0].content == "Authentication uses JWT tokens"
        assert project_mems[0].kind == "episodic"

        # Search with the same text to guarantee similarity with fallback embeddings
        loaded = await new_store.search("Authentication uses JWT tokens", top_k=1)
        assert len(loaded) > 0
        assert loaded[0][0].project_id == "proj_1"

    @pytest.mark.asyncio
    async def test_user_scoped_memories_cannot_be_searched_or_deleted_by_another_user(
        self, store: PersistentMemoryStore
    ) -> None:
        first = await store.store("private alpha memory", user_id="user-alpha")
        second = await store.store("private beta memory", user_id="user-beta")

        alpha_results = await store.search(
            "private memory", user_id="user-alpha", top_k=10, min_similarity=0.0
        )
        assert {memory.memory_id for memory, _score in alpha_results} == {first.memory_id}
        assert await store.list_all(user_id="user-alpha") == [first]
        assert store.get(second.memory_id, user_id="user-alpha") is None
        assert await store.delete(second.memory_id, user_id="user-alpha") is False
        assert store.get(second.memory_id, user_id="user-beta") is not None

    @pytest.mark.asyncio
    async def test_user_scope_survives_restart(self, store: PersistentMemoryStore) -> None:
        memory = await store.store(
            "private durable preference",
            user_id="user-alpha",
            memory_type=MemoryType.GLOBAL,
        )
        restarted = PersistentMemoryStore(
            embedding_service=store._embeddings,
            max_memories=100,
        )

        alpha_results = await restarted.search(
            "private durable preference", user_id="user-alpha", min_similarity=0.0
        )
        beta_results = await restarted.search(
            "private durable preference", user_id="user-beta", min_similarity=0.0
        )

        assert [item.memory_id for item, _score in alpha_results] == [memory.memory_id]
        assert beta_results == []

    @pytest.mark.asyncio
    async def test_malformed_row_does_not_hide_older_persisted_memories(
        self, store: PersistentMemoryStore
    ) -> None:
        from backend.knowledge import persistent_memory as pm_module

        valid = await store.store("healthy older memory")
        with sqlite3.connect(str(pm_module.DB_PATH)) as conn:
            conn.execute(
                "INSERT INTO persistent_memories (id, content, memory_type, created_at) "
                "VALUES (?, ?, ?, ?)",
                ("malformed-memory", "bad row", "not-a-memory-type", 9_999_999_999.0),
            )

        restarted = PersistentMemoryStore(
            embedding_service=store._embeddings,
            max_memories=100,
        )

        assert valid.memory_id in restarted._memories
        assert "malformed-memory" not in restarted._memories

    @pytest.mark.asyncio
    async def test_recall_survives_sqlite_access_telemetry_failure(
        self, store: PersistentMemoryStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        memory = await store.store("recall remains available during database contention")

        def fail_telemetry(_memory) -> None:
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(store, "_save_memory", fail_telemetry)

        results = await store.search(
            "recall remains available during database contention", min_similarity=0.0
        )

        assert [item.memory_id for item, _score in results] == [memory.memory_id]

    @pytest.mark.asyncio
    async def test_clear_session_deletes_from_db(self, store: PersistentMemoryStore) -> None:
        await store.store("Session note", session_id="s1")
        deleted = await store.clear_session("s1")
        assert deleted == 1

    @pytest.mark.asyncio
    async def test_capacity_eviction_is_persisted_and_stays_evicted(
        self, store: PersistentMemoryStore
    ) -> None:
        from backend.knowledge import persistent_memory as pm_module

        store._max_memories = 2
        evicted = await store.store("least important", importance=0.0)
        await store.store("important one", importance=1.0)
        await store.store("important two", importance=1.0)

        assert evicted.memory_id not in store._memories
        assert evicted.memory_id not in store._index
        with sqlite3.connect(str(pm_module.DB_PATH)) as conn:
            rows = conn.execute("SELECT id FROM persistent_memories").fetchall()
        persisted_ids = {row[0] for row in rows}
        assert len(persisted_ids) == 2
        assert evicted.memory_id not in persisted_ids

        reloaded = PersistentMemoryStore(
            embedding_service=store._embeddings,
            max_memories=2,
        )
        assert evicted.memory_id not in reloaded._memories
        assert evicted.memory_id not in reloaded._index
        assert len(reloaded._memories) == 2

    @pytest.mark.asyncio
    async def test_failed_eviction_persistence_restores_in_memory_state(
        self, store: PersistentMemoryStore
    ) -> None:
        from backend.knowledge import persistent_memory as pm_module

        store._max_memories = 1
        retained = await store.store("retained memory", importance=0.0)
        with sqlite3.connect(str(pm_module.DB_PATH)) as conn:
            conn.execute(
                """CREATE TRIGGER reject_memory_eviction
                   BEFORE DELETE ON persistent_memories
                   BEGIN SELECT RAISE(ABORT, 'delete rejected'); END"""
            )

        with pytest.raises(sqlite3.IntegrityError):
            await store.store("new memory", importance=1.0)

        assert set(store._memories) == {retained.memory_id}
        assert set(store._index) == {retained.memory_id}
        with sqlite3.connect(str(pm_module.DB_PATH)) as conn:
            rows = conn.execute("SELECT id FROM persistent_memories").fetchall()
        assert {row[0] for row in rows} == {retained.memory_id}
