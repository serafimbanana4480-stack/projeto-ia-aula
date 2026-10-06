"""Tests for backend.knowledge.persistent_memory."""

from __future__ import annotations

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
    async def test_clear_session_deletes_from_db(self, store: PersistentMemoryStore) -> None:
        await store.store("Session note", session_id="s1")
        deleted = await store.clear_session("s1")
        assert deleted == 1
        assert len(await store.get_session_memories("s1")) == 0
