"""Tests for the MemoryBank (episodic / semantic / procedural memory).

Covers:
- Adding memories of each kind (episodic, semantic, procedural).
- Filtering by kind.
- Forgetting low-importance entries.
- Consolidating near-duplicate memories.
"""

from __future__ import annotations

import pytest

from backend.knowledge.memory import EmbeddingService, MemoryStore
from backend.knowledge.memory_bank import MemoryBank, MemoryKind


class _StaticEmbeddingService(EmbeddingService):
    """Embedding service whose ``embed`` is replaced in tests via monkeypatch.

    Kept as a thin subclass so we get the cosine_similarity helper for free.
    """

    async def embed(self, text: str) -> list[float]:  # pragma: no cover - replaced
        return self._fallback_embed(text)


def _make_store(monkeypatch: pytest.MonkeyPatch) -> MemoryStore:
    """Build a MemoryStore whose embeddings are deterministic and fast."""
    svc = _StaticEmbeddingService()

    async def _fast_embed(text: str) -> list[float]:
        return svc._fallback_embed(text)

    # Deterministic, hash-based fallback avoids any outbound embedding call.
    monkeypatch.setattr(svc, "embed", _fast_embed)
    return MemoryStore(embedding_service=svc, max_memories=1_000)


def _bank_with_embeddings(
    monkeypatch: pytest.MonkeyPatch, embeddings: dict[str, list[float]]
) -> MemoryBank:
    """Build a MemoryBank whose embedding is a lookup table.

    ``embeddings`` maps a content string to the vector to return. The fallback
    is the deterministic hash embed so that any unmapped content still gets
    a sensible vector.
    """
    svc = EmbeddingService()
    default_embed = svc._fallback_embed
    lookup = embeddings

    async def _embed(text: str) -> list[float]:
        return lookup.get(text, default_embed(text))

    monkeypatch.setattr(svc, "embed", _embed)
    return MemoryBank(MemoryStore(embedding_service=svc, max_memories=1_000))


class TestMemoryBankAdd:
    @pytest.mark.asyncio
    async def test_add_episodic_sets_kind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bank = MemoryBank(_make_store(monkeypatch))
        mem = await bank.add_episodic("User opened the settings panel at 10:00")
        assert mem.kind == MemoryKind.EPISODIC.value
        # Round-trip via get
        assert bank.get(mem.memory_id) is mem

    @pytest.mark.asyncio
    async def test_add_semantic_sets_kind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bank = MemoryBank(_make_store(monkeypatch))
        mem = await bank.add_semantic("Python is dynamically typed")
        assert mem.kind == MemoryKind.SEMANTIC.value

    @pytest.mark.asyncio
    async def test_add_procedural_sets_kind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bank = MemoryBank(_make_store(monkeypatch))
        mem = await bank.add_procedural("To deploy: 1) build, 2) test, 3) push to staging")
        assert mem.kind == MemoryKind.PROCEDURAL.value

    @pytest.mark.asyncio
    async def test_add_propagates_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bank = MemoryBank(_make_store(monkeypatch))
        mem = await bank.add_semantic(
            "SQLite stores the relational data",
            importance=0.9,
            tags=["db", "storage"],
            source="DOCUMENTER",
        )
        assert mem.importance == pytest.approx(0.9)
        assert "db" in mem.tags
        assert mem.source == "DOCUMENTER"


class TestListByKind:
    @pytest.mark.asyncio
    async def test_list_by_kind_filters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bank = MemoryBank(_make_store(monkeypatch))
        await bank.add_episodic("User clicked the submit button")
        await bank.add_episodic("Server returned a 500 error")
        await bank.add_semantic("API uses REST over HTTPS")
        await bank.add_procedural("How to run the test suite")

        episodic = bank.list_by_kind(MemoryKind.EPISODIC)
        semantic = bank.list_by_kind(MemoryKind.SEMANTIC)
        procedural = bank.list_by_kind(MemoryKind.PROCEDURAL)

        assert len(episodic) == 2
        assert len(semantic) == 1
        assert len(procedural) == 1
        assert all(m.kind == MemoryKind.EPISODIC.value for m in episodic)
        assert all(m.kind == MemoryKind.SEMANTIC.value for m in semantic)
        assert all(m.kind == MemoryKind.PROCEDURAL.value for m in procedural)


class TestForgetBelow:
    @pytest.mark.asyncio
    async def test_forget_below_removes_low_importance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bank = MemoryBank(_make_store(monkeypatch))
        await bank.add_semantic("Important architectural decision", importance=0.9)
        await bank.add_semantic("Minor note", importance=0.2)
        await bank.add_semantic("Trivial chatter", importance=0.1)
        await bank.add_procedural("Deploy steps", importance=0.5)

        # Threshold 0.3: should drop the 0.2 and 0.1 entries.
        removed = await bank.forget_below(0.3)
        assert removed == 2

        remaining = bank.store.all_memories()
        assert len(remaining) == 2
        importances = sorted(m.importance for m in remaining)
        assert importances == [0.5, 0.9]


class TestConsolidate:
    @pytest.mark.asyncio
    async def test_consolidate_merges_near_duplicate_semantic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two near-duplicate semantic facts: almost identical vectors.
        dup_a = [1.0, 0.0, 0.0, 0.0]
        dup_b = [0.99, 0.01, 0.0, 0.0]  # cosine similarity ~ 0.9999
        other = [0.0, 0.0, 1.0, 0.0]  # orthogonal: similarity 0
        bank = _bank_with_embeddings(
            monkeypatch,
            {
                "Python uses indentation for blocks": dup_a,
                "Python uses indentation for code blocks": dup_b,
                "The sky appears blue during the day": other,
            },
        )

        keeper = await bank.add_semantic("Python uses indentation for blocks", importance=0.6)
        duplicate = await bank.add_semantic(
            "Python uses indentation for code blocks", importance=0.4
        )
        await bank.add_semantic("The sky appears blue during the day", importance=0.7)

        merges = await bank.consolidate(similarity_threshold=0.92)
        assert merges == 1

        remaining = bank.store.all_memories()
        remaining_ids = {m.memory_id for m in remaining}

        # The duplicate should be gone, the high-importance one kept.
        assert duplicate.memory_id not in remaining_ids
        assert keeper.memory_id in remaining_ids
        # The unrelated fact must survive untouched.
        assert any(m.content == "The sky appears blue during the day" for m in remaining)

    @pytest.mark.asyncio
    async def test_consolidate_skips_dissimilar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bank = _bank_with_embeddings(
            monkeypatch,
            {
                "Cats are mammals": [1.0, 0.0, 0.0],
                "Dogs are loyal": [0.0, 1.0, 0.0],
            },
        )
        await bank.add_semantic("Cats are mammals")
        await bank.add_semantic("Dogs are loyal")

        merges = await bank.consolidate(similarity_threshold=0.92)
        assert merges == 0
        assert len(bank.store.all_memories()) == 2


class TestGetMemoryBank:
    def test_singleton_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Reset module-level cache so the test is hermetic.
        import backend.knowledge.memory_bank as bank_mod

        monkeypatch.setattr(bank_mod, "_memory_bank", None)
        first = bank_mod.get_memory_bank()
        second = bank_mod.get_memory_bank()
        assert first is second
