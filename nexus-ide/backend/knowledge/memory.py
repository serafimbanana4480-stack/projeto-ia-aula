"""Memory and Knowledge System for Nexus IDE.

Provides persistent, semantic memory across sessions using embeddings for
vector similarity and SQLite for structured metadata.

Architecture:
- ``MemoryStore``: high-level API for storing and retrieving memories
- ``EmbeddingService``: generates embeddings via local AirLLM or sentence-transformers
- ``SemanticIndex``: in-memory vector search with hybrid keyword boost
- ``ContextBuilder``: assembles relevant context for agent requests

Key features:
- Session-scoped and global memories
- Semantic similarity search
- Automatic context window assembly
- Memory decay and relevance scoring
- Hybrid search (semantic + keyword)
- Conversation memory helpers
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class MemoryType(StrEnum):
    SESSION = "session"  # scoped to a single session
    PROJECT = "project"  # scoped to a project
    GLOBAL = "global"  # available across all sessions
    CODE_SNIPPET = "code_snippet"  # code with metadata
    FILE_CONTENT = "file_content"  # file contents for search
    CONVERSATION = "conversation"  # chat turn
    TOOL_RESULT = "tool_result"  # cached tool execution result
    DOCUMENTATION = "documentation"  # generated docs


@dataclass
class Memory:
    """A single memory entry with embedding and metadata."""

    memory_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    memory_type: MemoryType = MemoryType.SESSION
    session_id: str = ""
    project_id: str = ""

    # Content
    content: str = ""
    summary: str = ""  # short summary for listing
    embedding: list[float] = field(default_factory=list)

    # Metadata
    tags: list[str] = field(default_factory=list)
    source: str = ""  # agent or tool that created this
    file_path: str = ""  # if related to a file
    language: str = ""  # programming language if code

    # Temporal
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    importance: float = 0.5  # 0.0-1.0, affects retention
    kind: str = "semantic"  # episodic | semantic | procedural

    # Relations
    related_memory_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type.value,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "content": self.content[:500],
            "summary": self.summary,
            "tags": self.tags,
            "source": self.source,
            "file_path": self.file_path,
            "language": self.language,
            "importance": self.importance,
            "kind": self.kind,
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
            "access_count": self.access_count,
            "related_memory_ids": self.related_memory_ids,
        }


class EmbeddingService:
    """Generates vector embeddings using local AirLLM / sentence-transformers.

    Delegates to backend.tools.embeddings.embed() for the actual API call,
    with a deterministic fallback when the local model is unavailable.
    """

    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self._model = model
        self._dimension = 384  # default for all-MiniLM-L6-v2
        self._backend = "unavailable"
        self._last_error = "no embedding attempt yet"

    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text.

        Tries the shared embedding function first, then falls back to
        a deterministic hash-based embedding.
        """
        try:
            from backend.tools.embeddings import embed as _shared_embed

            result = await _shared_embed(text, model=self._model)
            if result:
                self._dimension = len(result)
                self._backend = "provider"
                self._last_error = ""
            return result
        except (ImportError, RuntimeError) as exc:
            self._last_error = str(exc)
            logger.debug("Shared embedding unavailable, trying direct provider: %s", exc)

        # Direct provider call as secondary fallback
        try:
            from backend.llm.factory import create_llm_client

            provider = create_llm_client()
            result = await provider.embed([text], model=self._model)
            if result and result[0]:
                self._dimension = len(result[0])
                self._backend = "provider"
                self._last_error = ""
                return result[0]
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning(
                "Direct embedding provider failed, using deterministic fallback: %s", exc
            )

        # Final deterministic fallback
        self._backend = "deterministic_lexical_fallback"
        return self._fallback_embed(text)

    def status(self) -> dict[str, Any]:
        """Expose whether memory is using real or degraded embeddings."""
        return {
            "backend": self._backend,
            "degraded": self._backend != "provider",
            "model": self._model,
            "dimension": self._dimension,
            "last_error": self._last_error or None,
        }

    def _fallback_embed(self, text: str) -> list[float]:
        """Deterministic lexical embedding when a model is unavailable.

        Hashing the complete string made similar sentences statistically
        unrelated, so degraded-mode memory recall only worked for byte-for-byte
        repeats.  Feature hashing preserves shared terms without a network or
        model dependency.  It is intentionally labelled a fallback: this gives
        useful lexical similarity, not a claim of provider-grade semantics.
        """
        import hashlib
        import re

        stopwords = {
            "a", "an", "and", "as", "at", "de", "do", "da", "e", "em",
            "for", "is", "o", "of", "os", "the", "to", "um", "uma",
        }
        tokens = [
            token
            for token in re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
            if len(token) > 1 and token not in stopwords
        ]
        if not tokens:
            tokens = [text.casefold() or "empty"]

        embedding = [0.0] * self._dimension
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            embedding[index] += sign

        norm = math.sqrt(sum(value * value for value in embedding))
        return [value / norm for value in embedding] if norm else embedding

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class MemoryStore:
    """High-level memory management with semantic search.

    Stores memories in-memory with optional persistence via
    :class:`PersistentMemoryStore`. For production, swap with a full
    vector DB backend.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        *,
        max_memories: int = 10_000,
    ) -> None:
        self._memories: dict[str, Memory] = {}
        self._embeddings = embedding_service or EmbeddingService()
        self._max_memories = max_memories
        self._index: dict[str, list[float]] = {}  # memory_id -> embedding

    async def store(
        self,
        content: str,
        *,
        memory_type: MemoryType = MemoryType.SESSION,
        session_id: str = "",
        project_id: str = "",
        tags: list[str] | None = None,
        source: str = "",
        summary: str = "",
        importance: float = 0.5,
        file_path: str = "",
        language: str = "",
        kind: str = "semantic",
        related_memory_ids: list[str] | None = None,
    ) -> Memory:
        """Store a new memory with automatic embedding generation."""
        if not content or not content.strip():
            raise ValueError("Memory content cannot be empty")

        # Generate embedding
        embedding = await self._embeddings.embed(content)

        memory = Memory(
            memory_type=memory_type,
            session_id=session_id,
            project_id=project_id,
            content=content,
            summary=summary or content[:120],
            embedding=embedding,
            tags=tags or [],
            source=source,
            importance=max(0.0, min(1.0, importance)),
            kind=kind,
            file_path=file_path,
            language=language,
            related_memory_ids=related_memory_ids or [],
        )

        self._memories[memory.memory_id] = memory
        self._index[memory.memory_id] = embedding

        # Evict old memories if over limit
        if len(self._memories) > self._max_memories:
            self._evict_least_important()

        logger.debug(
            "Stored memory %s (type=%s, session=%s, importance=%.2f)",
            memory.memory_id,
            memory_type.value,
            session_id,
            importance,
        )
        return memory

    async def search(
        self,
        query: str,
        *,
        session_id: str | None = None,
        project_id: str | None = None,
        memory_type: MemoryType | None = None,
        top_k: int = 10,
        min_similarity: float = 0.3,
    ) -> list[tuple[Memory, float]]:
        """Semantic search over stored memories."""
        query_embedding = await self._embeddings.embed(query)

        results: list[tuple[Memory, float]] = []
        for mem_id, mem in self._memories.items():
            # Filter by session/type/project
            if session_id and mem.session_id and mem.session_id != session_id:
                continue
            if project_id and mem.project_id and mem.project_id != project_id:
                continue
            if memory_type and mem.memory_type != memory_type:
                continue

            mem_embedding = self._index.get(mem_id, [])
            similarity = self._embeddings.cosine_similarity(query_embedding, mem_embedding)

            if similarity >= min_similarity:
                results.append((mem, similarity))
                mem.last_accessed_at = time.time()
                mem.access_count += 1

        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    async def get_context(
        self,
        query: str,
        session_id: str = "",
        project_id: str = "",
        *,
        max_tokens: int = 4000,
        top_k: int = 5,
    ) -> str:
        """Build a context string from relevant memories for an agent request.

        Combines semantic search with keyword boosting, deduplicates results,
        and respects a token budget using a simple character-to-token ratio.
        """
        results = await self.search(
            query,
            session_id=session_id or None,
            project_id=project_id or None,
            top_k=top_k,
        )

        query_terms = {
            term
            for term in __import__("re").findall(r"[A-Za-z0-9_]+", query.lower())
            if len(term) > 2
        }
        seen_ids = {mem.memory_id for mem, _ in results}

        if query_terms:
            keyword_matches: list[tuple[Memory, float]] = []
            for mem in self._memories.values():
                if mem.memory_id in seen_ids:
                    continue
                if session_id and mem.session_id and mem.session_id != session_id:
                    continue
                if project_id and mem.project_id and mem.project_id != project_id:
                    continue
                content_terms = set(__import__("re").findall(r"[A-Za-z0-9_]+", mem.content.lower()))
                overlap = len(query_terms & content_terms)
                if overlap:
                    keyword_matches.append((mem, min(1.0, 0.3 + overlap * 0.2)))

            keyword_matches.sort(key=lambda item: item[1], reverse=True)
            results.extend(keyword_matches[: max(0, top_k - len(results))])

        if not results:
            return ""

        # Deduplicate by memory_id and re-rank
        unique_results: dict[str, tuple[Memory, float]] = {}
        for mem, score in results:
            if mem.memory_id not in unique_results or unique_results[mem.memory_id][1] < score:
                unique_results[mem.memory_id] = (mem, score)

        ranked = sorted(unique_results.values(), key=lambda x: x[1], reverse=True)

        context_parts: list[str] = []
        token_estimate = 0
        chars_per_token = 4

        for mem, similarity in ranked:
            snippet = mem.content[:600]
            estimated = math.ceil(len(snippet) / chars_per_token)
            if token_estimate + estimated > max_tokens:
                break
            token_estimate += estimated

            header = f"[Memory {mem.memory_id[:8]}"
            if mem.memory_type:
                header += f" | type={mem.memory_type.value}"
            if mem.source:
                header += f" | source={mem.source}"
            header += f" | relevance={similarity:.2f}]"
            context_parts.append(f"{header}:\n{snippet}")

        return "\n\n".join(context_parts)

    async def remember_conversation(
        self,
        user_message: str,
        assistant_message: str,
        *,
        session_id: str = "",
        project_id: str = "",
        source: str = "",
        importance: float = 0.5,
    ) -> tuple[Memory, Memory]:
        """Store a user/assistant exchange as conversation memories."""
        user_mem = await self.store(
            content=f"User: {user_message}",
            memory_type=MemoryType.CONVERSATION,
            session_id=session_id,
            project_id=project_id,
            source=source,
            tags=["user_query", source.lower() if source else "chat"],
            importance=importance,
        )
        assistant_mem = await self.store(
            content=f"Assistant: {assistant_message[:2000]}",
            memory_type=MemoryType.CONVERSATION,
            session_id=session_id,
            project_id=project_id,
            source=source,
            tags=["assistant_response", source.lower() if source else "chat"],
            importance=max(0.0, importance - 0.1),
            related_memory_ids=[user_mem.memory_id],
        )
        user_mem.related_memory_ids.append(assistant_mem.memory_id)
        return user_mem, assistant_mem

    async def recall_for_query(
        self,
        query: str,
        *,
        session_id: str = "",
        project_id: str = "",
        top_k: int = 5,
    ) -> str:
        """Convenience alias for ``get_context`` used by agents."""
        return await self.get_context(
            query,
            session_id=session_id,
            project_id=project_id,
            top_k=top_k,
        )

    async def get_by_tag(self, tag: str, limit: int = 20) -> list[Memory]:
        """Retrieve memories by tag."""
        matches = [m for m in self._memories.values() if tag in m.tags]
        matches.sort(key=lambda m: m.created_at, reverse=True)
        return matches[:limit]

    async def get_session_memories(self, session_id: str) -> list[Memory]:
        """Get all memories for a session."""
        return [m for m in self._memories.values() if m.session_id == session_id]

    async def get_project_memories(self, project_id: str) -> list[Memory]:
        """Get all memories scoped to a project."""
        return [m for m in self._memories.values() if m.project_id == project_id]

    async def list_all(self, limit: int = 1000) -> list[Memory]:
        """Return all memories ordered by creation time (newest first)."""
        memories = sorted(self._memories.values(), key=lambda m: m.created_at, reverse=True)
        return memories[:limit]

    def get(self, memory_id: str) -> Memory | None:
        """Return a memory by ID, or None when missing."""
        return self._memories.get(memory_id)

    def all_memories(self) -> list[Memory]:
        """Return all stored memories (unsorted snapshot)."""
        return list(self._memories.values())

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        if memory_id in self._memories:
            del self._memories[memory_id]
            self._index.pop(memory_id, None)
            return True
        return False

    async def clear_session(self, session_id: str) -> int:
        """Clear all memories for a session."""
        to_delete = [mid for mid, m in self._memories.items() if m.session_id == session_id]
        for mid in to_delete:
            del self._memories[mid]
            self._index.pop(mid, None)
        return len(to_delete)

    def stats(self) -> dict[str, Any]:
        """Return memory store statistics."""
        types = {}
        for m in self._memories.values():
            t = m.memory_type.value
            types[t] = types.get(t, 0) + 1
        return {
            "total_memories": len(self._memories),
            "by_type": types,
            "max_capacity": self._max_memories,
            "embedding": self._embeddings.status(),
        }

    def _evict_least_important(self) -> None:
        """Evict the least valuable memory to stay under the limit.

        We maximise a retention score: important + recently accessed + recent
        memories are kept. The memory with the lowest score is evicted first.
        """
        if not self._memories:
            return

        now = time.time()
        scored = []
        for mem_id, mem in self._memories.items():
            age_days = max(0.0, (now - mem.created_at) / 86400)
            # Access component saturates quickly: 0 accesses -> 0, many -> ~0.3
            access_score = mem.access_count / (mem.access_count + 10) * 0.3
            # Age component: recent memories get the full 0.2, old ones decay
            age_score = (1.0 / (age_days + 1.0)) * 0.2
            score = mem.importance * 0.5 + access_score + age_score
            scored.append((mem_id, score))

        scored.sort(key=lambda x: x[1])
        if scored:
            evict_id = scored[0][0]
            del self._memories[evict_id]
            self._index.pop(evict_id, None)
            logger.debug("Evicted memory %s (low importance/access)", evict_id)


# Global singleton
_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Get or create the global memory store singleton.

    Uses :class:`PersistentMemoryStore` when available so that memories
    survive process restarts.
    """
    global _memory_store
    if _memory_store is None:
        try:
            from backend.knowledge.persistent_memory import PersistentMemoryStore

            _memory_store = PersistentMemoryStore()
        except Exception as exc:
            logger.warning(
                "PersistentMemoryStore unavailable, falling back to MemoryStore: %s",
                exc,
            )
            _memory_store = MemoryStore()
    return _memory_store
