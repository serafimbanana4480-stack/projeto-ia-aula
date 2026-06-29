"""Tests for backend.tools.memory_tools."""

from __future__ import annotations

import pytest

from backend.tools.memory_tools import recall_context, store_memory


class TestMemoryTools:
    @pytest.mark.asyncio
    async def test_store_and_recall(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.knowledge.memory import EmbeddingService, MemoryStore

        svc = EmbeddingService()

        async def _fast_embed(text: str) -> list[float]:
            return svc._fallback_embed(text)

        monkeypatch.setattr(svc, "embed", _fast_embed)
        store = MemoryStore(embedding_service=svc, max_memories=100)
        monkeypatch.setattr(
            "backend.tools.memory_tools.get_memory_store",
            lambda: store,
        )

        result = await store_memory(
            content="PostgreSQL is the primary database",
            memory_type="global",
            tags="database,postgres",
            source="TEST",
        )
        assert result["stored"] is True
        assert "memory_id" in result

        # Search with the same text to guarantee similarity with fallback embeddings
        recall = await recall_context("PostgreSQL primary database", top_k=5)
        assert "memories" in recall
        assert any("PostgreSQL" in m["content"] for m in recall["memories"])

    @pytest.mark.asyncio
    async def test_recall_empty_query(self) -> None:
        result = await recall_context("   ")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_store_empty_content(self) -> None:
        result = await store_memory("   ")
        assert "error" in result
