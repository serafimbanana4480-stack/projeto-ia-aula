"""Tests for the Memory and Knowledge System.

Covers:
- Memory storage and retrieval
- Semantic search
- Embedding generation (with fallback)
- Context building
- Memory eviction
- Session-scoped memories
"""

from __future__ import annotations

import pytest

from backend.knowledge.memory import (
    EmbeddingService,
    Memory,
    MemoryStore,
    MemoryType,
)


class TestEmbeddingService:
    @pytest.mark.asyncio
    async def test_empty_provider_embeddings_use_degraded_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.llm import factory
        from backend.tools import embeddings

        async def empty_embed(*_args, **_kwargs):
            return []

        class EmptyProvider:
            embed = staticmethod(empty_embed)

        monkeypatch.setattr(embeddings, "embed", empty_embed)
        monkeypatch.setattr(factory, "create_llm_client", lambda: EmptyProvider())
        service = EmbeddingService()
        vector = await service.embed("orchid migration")
        assert vector == service._fallback_embed("orchid migration")
        assert service.status()["backend"] == "deterministic_lexical_fallback"
        assert service.status()["last_error"]

    def test_cosine_similarity_rejects_different_dimensions(self) -> None:
        assert EmbeddingService().cosine_similarity([1.0], [1.0, 0.0]) == 0.0

    def test_cosine_similarity_identical(self) -> None:
        svc = EmbeddingService()
        vec = [1.0, 0.0, 0.0]
        sim = svc.cosine_similarity(vec, vec)
        assert sim == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self) -> None:
        svc = EmbeddingService()
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        sim = svc.cosine_similarity(a, b)
        assert sim == pytest.approx(0.0)

    def test_cosine_similarity_opposite(self) -> None:
        svc = EmbeddingService()
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        sim = svc.cosine_similarity(a, b)
        assert sim == pytest.approx(-1.0)

    def test_cosine_similarity_empty(self) -> None:
        svc = EmbeddingService()
        assert svc.cosine_similarity([], [1.0]) == 0.0
        assert svc.cosine_similarity([1.0], []) == 0.0

    def test_fallback_embed_is_deterministic(self) -> None:
        svc = EmbeddingService()
        e1 = svc._fallback_embed("hello world")
        e2 = svc._fallback_embed("hello world")
        assert e1 == e2

    def test_fallback_embed_different_inputs(self) -> None:
        svc = EmbeddingService()
        e1 = svc._fallback_embed("hello")
        e2 = svc._fallback_embed("world")
        assert e1 != e2

    def test_fallback_embed_preserves_shared_terms(self) -> None:
        svc = EmbeddingService()
        stored = svc._fallback_embed("PostgreSQL is the primary database")
        query = svc._fallback_embed("PostgreSQL primary database")
        assert svc.cosine_similarity(stored, query) >= 0.45

    def test_fallback_embed_dimension(self) -> None:
        svc = EmbeddingService()
        emb = svc._fallback_embed("test")
        assert len(emb) == svc._dimension


class TestMemory:
    def test_memory_creation(self) -> None:
        mem = Memory(
            content="Test content",
            memory_type=MemoryType.SESSION,
            session_id="s1",
            tags=["test"],
        )
        assert mem.content == "Test content"
        assert mem.memory_type == MemoryType.SESSION
        assert mem.session_id == "s1"
        assert "test" in mem.tags
        assert len(mem.memory_id) == 16

    def test_memory_to_dict(self) -> None:
        mem = Memory(
            content="Hello world" * 100,  # long content
            summary="Short summary",
            tags=["tag1", "tag2"],
            source="CODER",
        )
        d = mem.to_dict()
        assert d["memory_id"] == mem.memory_id
        assert d["summary"] == "Short summary"
        assert len(d["content"]) <= 500  # truncated
        assert "tag1" in d["tags"]


class TestMemoryStore:
    @pytest.fixture
    def store(self, monkeypatch: pytest.MonkeyPatch) -> MemoryStore:
        svc = EmbeddingService()

        # Use deterministic fallback embed to avoid slow/outbound Ollama calls
        async def _fast_embed(text: str) -> list[float]:
            return svc._fallback_embed(text)

        monkeypatch.setattr(svc, "embed", _fast_embed)
        return MemoryStore(embedding_service=svc, max_memories=100)

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, store: MemoryStore) -> None:
        mem = await store.store(
            "Python is a programming language",
            memory_type=MemoryType.GLOBAL,
            tags=["python", "language"],
        )
        assert mem.memory_id in store._memories
        assert mem.memory_id in store._index

    @pytest.mark.asyncio
    async def test_search_by_semantic_similarity(self, store: MemoryStore) -> None:
        await store.store("Python programming language", memory_type=MemoryType.GLOBAL)
        await store.store("JavaScript for web development", memory_type=MemoryType.GLOBAL)
        await store.store("Cooking recipes for dinner", memory_type=MemoryType.GLOBAL)

        results = await store.search("programming languages", top_k=2)
        assert len(results) > 0
        # Python and JS should be more relevant than cooking
        contents = [r[0].content for r in results]
        assert any("Python" in c for c in contents)

    @pytest.mark.asyncio
    async def test_search_with_session_filter(self, store: MemoryStore) -> None:
        await store.store("Session 1 memory", session_id="s1")
        await store.store("Session 2 memory", session_id="s2")

        results = await store.search("memory", session_id="s1")
        assert all(r[0].session_id == "s1" for r in results)

    @pytest.mark.asyncio
    async def test_long_term_recall_crosses_sessions_without_crossing_projects_or_users(
        self, store: MemoryStore
    ) -> None:
        project_memory = await store.store(
            "Project alpha durable authentication decision",
            user_id="alice",
            memory_type=MemoryType.CONVERSATION,
            session_id="old-session",
            project_id="project-alpha",
        )
        session_memory = await store.store(
            "Project alpha temporary tool result",
            user_id="alice",
            memory_type=MemoryType.SESSION,
            session_id="old-session",
            project_id="project-alpha",
        )
        other_project = await store.store(
            "Project beta unrelated deployment decision",
            user_id="alice",
            memory_type=MemoryType.CONVERSATION,
            session_id="another-session",
            project_id="project-beta",
        )
        other_user = await store.store(
            "Project alpha private account preference",
            user_id="bob",
            memory_type=MemoryType.CONVERSATION,
            session_id="old-session",
            project_id="project-alpha",
        )

        results = await store.search(
            "project alpha durable authentication decision",
            user_id="alice",
            session_id="new-session",
            project_id="project-alpha",
            top_k=20,
            min_similarity=0.0,
        )
        assert {memory.memory_id for memory, _score in results} == {project_memory.memory_id}
        assert session_memory.memory_id not in {memory.memory_id for memory, _score in results}
        assert other_project.memory_id not in {memory.memory_id for memory, _score in results}
        assert other_user.memory_id not in {memory.memory_id for memory, _score in results}

        context = await store.get_context(
            "project alpha durable authentication decision",
            user_id="alice",
            session_id="new-session",
            project_id="project-alpha",
        )
        assert project_memory.content in context
        assert "Project beta" not in context

    @pytest.mark.asyncio
    async def test_search_with_type_filter(self, store: MemoryStore) -> None:
        await store.store("Global knowledge", memory_type=MemoryType.GLOBAL)
        await store.store("Session note", memory_type=MemoryType.SESSION, session_id="s1")

        results = await store.search("knowledge", memory_type=MemoryType.GLOBAL)
        assert all(r[0].memory_type == MemoryType.GLOBAL for r in results)

    @pytest.mark.asyncio
    async def test_get_context(self, store: MemoryStore) -> None:
        await store.store(
            "Authentication uses JWT tokens for security", memory_type=MemoryType.GLOBAL
        )
        await store.store(
            "Database uses PostgreSQL with SQLAlchemy ORM", memory_type=MemoryType.GLOBAL
        )

        context = await store.get_context("JWT authentication", top_k=2)
        assert "JWT" in context or "authentication" in context.lower()

    @pytest.mark.asyncio
    async def test_get_by_tag(self, store: MemoryStore) -> None:
        await store.store("Memory A", tags=["important", "python"])
        await store.store("Memory B", tags=["important", "javascript"])
        await store.store("Memory C", tags=["low-priority"])

        important = await store.get_by_tag("important")
        assert len(important) == 2

    @pytest.mark.asyncio
    async def test_get_session_memories(self, store: MemoryStore) -> None:
        await store.store("S1-A", session_id="s1")
        await store.store("S1-B", session_id="s1")
        await store.store("S2-A", session_id="s2")

        s1_mems = await store.get_session_memories("s1")
        assert len(s1_mems) == 2

    @pytest.mark.asyncio
    async def test_delete_memory(self, store: MemoryStore) -> None:
        mem = await store.store("To be deleted")
        assert await store.delete(mem.memory_id) is True
        assert await store.delete(mem.memory_id) is False

    @pytest.mark.asyncio
    async def test_clear_session(self, store: MemoryStore) -> None:
        await store.store("S1-A", session_id="s1")
        await store.store("S1-B", session_id="s1")
        await store.store("S2-A", session_id="s2")

        deleted = await store.clear_session("s1")
        assert deleted == 2
        s2_mems = await store.get_session_memories("s2")
        assert len(s2_mems) == 1

    @pytest.mark.asyncio
    async def test_eviction_when_full(self, store: MemoryStore) -> None:
        store._max_memories = 5
        for i in range(10):
            await store.store(f"Memory {i}", importance=0.1)
        assert len(store._memories) <= 5

    def test_stats(self, store: MemoryStore) -> None:
        stats = store.stats()
        assert "total_memories" in stats
        assert "by_type" in stats
        assert "max_capacity" in stats


# ── N3: conversation recall never crosses sessions ──────────────────────


@pytest.fixture
def leak_store() -> MemoryStore:
    return _leak_store()


def _leak_store() -> MemoryStore:
    return MemoryStore(embedding_service=EmbeddingService())


@pytest.mark.asyncio
async def test_conversation_memory_does_not_cross_sessions(leak_store: MemoryStore) -> None:
    """Another session must never recall this session's answer.

    Threshold N3.  ``_matches_memory_scope`` only isolated ``SESSION`` and
    ``TOOL_RESULT`` memories by ``session_id``; ``CONVERSATION`` entries — which
    carry the assistant's own answer — were eligible for every session of the
    same user.  That is what leaked a finished run's answer into an unrelated
    session's prompt.
    """
    await leak_store.remember_conversation(
        user_message="Explica o offset da paginação",
        assistant_message="RESPOSTA-SECRETA-DA-SESSAO-ALFA",
        session_id="session-alfa",
        project_id="projeto-x",
        user_id="utilizador-1",
    )
    recalled = await leak_store.get_context(
        "offset da paginação",
        session_id="session-beta",
        project_id="projeto-x",
        user_id="utilizador-1",
        top_k=5,
        max_tokens=1500,
    )
    assert "RESPOSTA-SECRETA-DA-SESSAO-ALFA" not in recalled, (
        "a different session recalled another session's assistant answer"
    )

    # The owning session still keeps its own answer in memory: only the
    # *recall* into a foreign session is forbidden, never the storage.
    stored = await leak_store.search(
        "RESPOSTA-SECRETA-DA-SESSAO-ALFA",
        user_id="utilizador-1",
        session_id="session-alfa",
        project_id="projeto-x",
        top_k=10,
        min_similarity=0.0,
    )
    assert any("RESPOSTA-SECRETA-DA-SESSAO-ALFA" in mem.content for mem, _ in stored)


@pytest.mark.asyncio
async def test_conversation_memory_scope_filters_foreign_session(leak_store: MemoryStore) -> None:
    """The scope predicate itself rejects a foreign session for an answer."""
    from backend.knowledge.memory import _ASSISTANT_ANSWER_TAG, _matches_memory_scope

    _user_entry, own = await leak_store.remember_conversation(
        user_message="Pedido próprio",
        assistant_message="RESPOSTA-PROPRIA",
        session_id="session-alfa",
        project_id="projeto-x",
        user_id="utilizador-1",
    )
    assert _ASSISTANT_ANSWER_TAG in set(own.tags or ()), own.tags
    assert _matches_memory_scope(
        own,
        user_id="utilizador-1",
        session_id="session-alfa",
        project_id="projeto-x",
    )
    assert not _matches_memory_scope(
        own,
        user_id="utilizador-1",
        session_id="session-beta",
        project_id="projeto-x",
    )
