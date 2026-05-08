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

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.knowledge.memory import (
    EmbeddingService,
    Memory,
    MemoryStore,
    MemoryType,
)


class TestEmbeddingService:
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
    def store(self) -> MemoryStore:
        svc = EmbeddingService()
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
    async def test_search_with_type_filter(self, store: MemoryStore) -> None:
        await store.store("Global knowledge", memory_type=MemoryType.GLOBAL)
        await store.store("Session note", memory_type=MemoryType.SESSION, session_id="s1")

        results = await store.search("knowledge", memory_type=MemoryType.GLOBAL)
        assert all(r[0].memory_type == MemoryType.GLOBAL for r in results)

    @pytest.mark.asyncio
    async def test_get_context(self, store: MemoryStore) -> None:
        await store.store("Authentication uses JWT tokens for security", memory_type=MemoryType.GLOBAL)
        await store.store("Database uses PostgreSQL with SQLAlchemy ORM", memory_type=MemoryType.GLOBAL)

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
