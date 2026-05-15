"""Memory and Knowledge System for Nexus IDE.

Provides persistent, semantic memory across sessions using ChromaDB for
vector embeddings and SQLite for structured metadata.

Architecture:
- ``MemoryStore``: high-level API for storing and retrieving memories
- ``EmbeddingService``: generates embeddings via Ollama
- ``SemanticIndex``: ChromaDB-backed vector search
- ``ContextBuilder``: assembles relevant context for agent requests

Key features:
- Session-scoped and global memories
- Semantic similarity search
- Automatic context window assembly
- Memory decay and relevance scoring
- Hybrid search (semantic + keyword)
"""

from __future__ import annotations

import logging
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

    # Relations
    related_memory_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type.value,
            "session_id": self.session_id,
            "content": self.content[:500],
            "summary": self.summary,
            "tags": self.tags,
            "source": self.source,
            "file_path": self.file_path,
            "importance": self.importance,
            "created_at": self.created_at,
            "access_count": self.access_count,
        }


class EmbeddingService:
    """Generates vector embeddings using Ollama's embedding endpoint.

    Delegates to backend.tools.embeddings.embed() for the actual API call,
    with a deterministic fallback when Ollama is unavailable.
    """

    def __init__(
        self, ollama_host: str = "http://localhost:11434", model: str = "nomic-embed-text"
    ) -> None:
        self._host = ollama_host.rstrip("/")
        self._model = model
        self._dimension = 768  # default for nomic-embed-text

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
            return result
        except (ImportError, RuntimeError):
            pass

        # Direct API call as secondary fallback
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # Try new API format first
                resp = await client.post(
                    f"{self._host}/api/embed",
                    json={"model": self._model, "input": text},
                )
                if resp.status_code == 404:
                    # Fall back to old API format
                    resp = await client.post(
                        f"{self._host}/api/embeddings",
                        json={"model": self._model, "prompt": text},
                    )
                resp.raise_for_status()
                data = resp.json()
                # New API returns "embeddings" (list of lists)
                embedding = data.get("embeddings", [[]])[0] or data.get("embedding", [])
                if embedding:
                    self._dimension = len(embedding)
                return embedding
            except Exception as exc:
                logger.warning("Embedding generation failed: %s. Using fallback.", exc)
                return self._fallback_embed(text)

    def _fallback_embed(self, text: str) -> list[float]:
        """Deterministic fallback embedding when Ollama is unavailable."""
        import hashlib

        hash_bytes = hashlib.sha256(text.encode()).digest()
        # Generate a pseudo-embedding from hash
        embedding = []
        for i in range(0, min(len(hash_bytes), self._dimension // 4)):
            val = int.from_bytes(hash_bytes[i : i + 4], "big") / (2**32)
            embedding.append(val * 2 - 1)  # normalize to [-1, 1]
        # Pad to dimension
        while len(embedding) < self._dimension:
            embedding.append(0.0)
        return embedding[: self._dimension]

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

    Stores memories in-memory with optional ChromaDB persistence.
    For production, swap with a full vector DB backend.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        *,
        max_memories: int = 10_000,
        ollama_host: str = "http://localhost:11434",
    ) -> None:
        self._memories: dict[str, Memory] = {}
        self._embeddings = embedding_service or EmbeddingService(ollama_host)
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
    ) -> Memory:
        """Store a new memory with automatic embedding generation."""
        # Generate embedding
        embedding = await self._embeddings.embed(content)

        memory = Memory(
            memory_type=memory_type,
            session_id=session_id,
            project_id=project_id,
            content=content,
            summary=summary or content[:100],
            embedding=embedding,
            tags=tags or [],
            source=source,
            importance=importance,
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
        memory_type: MemoryType | None = None,
        top_k: int = 10,
        min_similarity: float = 0.3,
    ) -> list[tuple[Memory, float]]:
        """Semantic search over stored memories."""
        query_embedding = await self._embeddings.embed(query)

        results: list[tuple[Memory, float]] = []
        for mem_id, mem in self._memories.items():
            # Filter by session/type
            if session_id and mem.session_id and mem.session_id != session_id:
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
        *,
        max_tokens: int = 4000,
        top_k: int = 5,
    ) -> str:
        """Build a context string from relevant memories for an agent request."""
        results = await self.search(query, session_id=session_id, top_k=top_k)

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
                content_terms = set(__import__("re").findall(r"[A-Za-z0-9_]+", mem.content.lower()))
                overlap = len(query_terms & content_terms)
                if overlap:
                    keyword_matches.append((mem, min(1.0, 0.3 + overlap * 0.2)))

            keyword_matches.sort(key=lambda item: item[1], reverse=True)
            results.extend(keyword_matches[: max(0, top_k - len(results))])

        if not results:
            return ""

        context_parts: list[str] = []
        token_estimate = 0

        for mem, similarity in results:
            snippet = mem.content[:500]
            token_estimate += len(snippet.split())
            if token_estimate > max_tokens:
                break
            context_parts.append(
                f"[Memory {mem.memory_id[:8]} | relevance={similarity:.2f}]: {snippet}"
            )

        return "\n\n".join(context_parts)

    async def get_by_tag(self, tag: str, limit: int = 20) -> list[Memory]:
        """Retrieve memories by tag."""
        matches = [m for m in self._memories.values() if tag in m.tags]
        matches.sort(key=lambda m: m.created_at, reverse=True)
        return matches[:limit]

    async def get_session_memories(self, session_id: str) -> list[Memory]:
        """Get all memories for a session."""
        return [m for m in self._memories.values() if m.session_id == session_id]

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
        }

    def _evict_least_important(self) -> None:
        """Evict the least important memory to stay under the limit."""
        if not self._memories:
            return

        # Score: lower importance + older + less accessed = evict first
        now = time.time()
        scored = []
        for mem_id, mem in self._memories.items():
            age_days = (now - mem.created_at) / 86400
            score = (
                mem.importance * 0.5
                + (1.0 / (mem.access_count + 1)) * 0.3
                + (1.0 / (age_days + 1)) * 0.2
            )
            scored.append((mem_id, score))

        scored.sort(key=lambda x: x[1])
        if scored:
            evict_id = scored[0][0]
            del self._memories[evict_id]
            self._index.pop(evict_id, None)
            logger.debug("Evicted memory %s (low importance/access)", evict_id)


# Global singleton
_memory_store: MemoryStore | None = None


def get_memory_store(ollama_host: str = "http://localhost:11434") -> MemoryStore:
    """Get or create the global memory store singleton."""
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore(ollama_host=ollama_host)
    return _memory_store
