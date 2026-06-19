"""Memory Bank — episodic, semantic, and procedural memory kinds.

Wraps the existing :class:`MemoryStore` to add a higher-level concept of
*memory kinds* (episodic / semantic / procedural) along with consolidation
(merging near-duplicates) and decay (forgetting low-importance entries).

Architecture:
- ``MemoryKind`` : StrEnum distinguishing episodic events, semantic facts,
  and procedural knowledge.
- ``MemoryBank`` : thin facade that tags memories with a kind, supports
  similarity-based consolidation, and importance-based forgetting.
- ``get_memory_bank`` : process-wide cached singleton for shared use.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from backend.knowledge.memory import Memory, MemoryStore, get_memory_store

logger = logging.getLogger(__name__)


class MemoryKind(StrEnum):
    """High-level classification of memories.

    * ``EPISODIC``   — a specific event or experience (time, place, action).
    * ``SEMANTIC``   — a discrete fact or piece of declarative knowledge.
    * ``PROCEDURAL`` — a how-to, workflow, or step-by-step procedure.
    """

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


def _cos(a: list[float], b: list[float]) -> float:
    """Cosine similarity fallback used when ``EmbeddingService`` is unavailable."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class MemoryBank:
    """Higher-level memory facade exposing episodic/semantic/procedural kinds."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or get_memory_store()

    def get(self, memory_id: str) -> Memory | None:
        """Return a memory by ID, delegating to the underlying store."""
        return self.store.get(memory_id)

    async def add_episodic(self, event: str, **kwargs: object) -> Memory:
        """Store an episodic event (a specific experience)."""
        return await self.store.store(event, kind=MemoryKind.EPISODIC.value, **kwargs)

    async def add_semantic(self, fact: str, **kwargs: object) -> Memory:
        """Store a semantic fact (declarative knowledge)."""
        return await self.store.store(fact, kind=MemoryKind.SEMANTIC.value, **kwargs)

    async def add_procedural(self, procedure: str, **kwargs: object) -> Memory:
        """Store a procedural memory (how-to / workflow)."""
        return await self.store.store(procedure, kind=MemoryKind.PROCEDURAL.value, **kwargs)

    def list_by_kind(self, kind: MemoryKind) -> list[Memory]:
        """Return all stored memories matching the given kind."""
        kind_value = kind.value
        return [m for m in self.store.all_memories() if m.kind == kind_value]

    async def consolidate(self, similarity_threshold: float = 0.92) -> int:
        """Merge near-duplicate memories within the same kind.

        For each pair of memories of the same kind whose embedding cosine
        similarity is ``>= similarity_threshold``, the entry with the higher
        ``importance`` is kept; the other is merged in (its tags are appended,
        access counts summed) and then deleted. Memories without an embedding
        are skipped.

        Returns the number of merges performed.
        """
        # Use the embedding service helper when present, otherwise fall back
        # to a local cosine implementation.
        embed_svc = getattr(self.store, "_embeddings", None)
        sim_fn = getattr(embed_svc, "cosine_similarity", None)

        def _similarity(a: list[float], b: list[float]) -> float:
            if callable(sim_fn):
                try:
                    return float(sim_fn(a, b))
                except Exception:  # pragma: no cover - defensive
                    return _cos(a, b)
            return _cos(a, b)

        memories = self.store.all_memories()
        # Group by kind for O(n) per-kind comparisons.
        by_kind: dict[str, list[Memory]] = {}
        for m in memories:
            if not m.embedding:
                continue
            by_kind.setdefault(m.kind, []).append(m)

        to_delete: set[str] = set()
        merges = 0

        for group in by_kind.values():
            # Snapshot ids that haven't been merged away yet.
            survivors = [m for m in group if m.memory_id not in to_delete]
            for i in range(len(survivors)):
                a = survivors[i]
                if a.memory_id in to_delete:
                    continue
                for j in range(i + 1, len(survivors)):
                    b = survivors[j]
                    if b.memory_id in to_delete:
                        continue
                    if a.embedding and b.embedding:
                        sim = _similarity(a.embedding, b.embedding)
                    else:
                        sim = 0.0
                    if sim < similarity_threshold:
                        continue
                    # Keep the higher-importance one as the merged result.
                    if a.importance >= b.importance:
                        keeper, victim = a, b
                    else:
                        keeper, victim = b, a
                    keeper.access_count += victim.access_count
                    for tag in victim.tags:
                        if tag not in keeper.tags:
                            keeper.tags.append(tag)
                    to_delete.add(victim.memory_id)
                    merges += 1
                    logger.debug(
                        "Consolidated %s into %s (sim=%.3f)",
                        victim.memory_id,
                        keeper.memory_id,
                        sim,
                    )

        for mid in to_delete:
            await self.store.delete(mid)

        if merges:
            logger.info("Consolidated %d near-duplicate memories", merges)
        return merges

    async def forget_below(self, score: float) -> int:
        """Delete memories whose importance is strictly below ``score``.

        Returns the number of memories removed.
        """
        memories = self.store.all_memories()
        to_delete = [m.memory_id for m in memories if m.importance < score]
        for mid in to_delete:
            await self.store.delete(mid)
        if to_delete:
            logger.info("Forgot %d memories with importance < %.2f", len(to_delete), score)
        return len(to_delete)


# Module-level cached singleton
_memory_bank: MemoryBank | None = None


def get_memory_bank() -> MemoryBank:
    """Return a process-wide cached :class:`MemoryBank` instance."""
    global _memory_bank
    if _memory_bank is None:
        _memory_bank = MemoryBank()
    return _memory_bank
