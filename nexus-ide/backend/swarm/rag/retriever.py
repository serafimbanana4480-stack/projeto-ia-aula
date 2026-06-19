"""SWARM RAG retriever — hybrid (semantic + keyword) search.

Wraps the existing NEXUS memory store and FAISS vector store when available,
and falls back to an in-process inverted index when they are not.

The retriever is designed to be safe to call from any agent:
- Synchronous API (no awaiting) so it can be used mid-stream
- Read-only — no side effects on the underlying stores
- Citation-friendly: every result includes chunk_id, source_path, line range
"""

from __future__ import annotations

import contextlib
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from backend.swarm.rag.chunker import TextChunk

logger = logging.getLogger(__name__)

EMBED_TIMEOUT_S: float = 5.0  # hard timeout for embedding calls (avoids hangs)


@dataclass
class RetrievalHit:
    """A single retrieval hit with citation info."""

    chunk_id: str
    text: str
    source_path: str
    start_line: int
    end_line: int
    language: str = ""
    score: float = 0.0
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source_path": self.source_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "language": self.language,
            "score": round(self.score, 4),
            "semantic_score": round(self.semantic_score, 4),
            "keyword_score": round(self.keyword_score, 4),
            "metadata": self.metadata,
        }


class InMemoryIndex:
    """Tiny inverted index used as a fallback when FAISS isn't available."""

    def __init__(self) -> None:
        self.chunks: list[TextChunk] = []
        # word -> {chunk_id: tf}
        self._postings: dict[str, dict[str, int]] = defaultdict(dict)
        self._doc_lens: dict[str, int] = {}
        self._avg_dl: float = 0.0

    def add(self, chunks: list[TextChunk]) -> None:
        for chunk in chunks:
            self.chunks.append(chunk)
            tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", chunk.text.lower())
            self._doc_lens[chunk.chunk_id] = max(1, len(tokens))
            counts = Counter(tokens)
            for token, tf in counts.items():
                self._postings[token][chunk.chunk_id] = tf
        if self._doc_lens:
            self._avg_dl = sum(self._doc_lens.values()) / len(self._doc_lens)

    def bm25_score(
        self,
        query: str,
        chunk_id: str,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> float:
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query.lower())
        if not tokens:
            return 0.0
        dl = self._doc_lens.get(chunk_id, 1)
        N = max(1, len(self.chunks))
        score = 0.0
        for t in tokens:
            posting = self._postings.get(t)
            if not posting:
                continue
            df = len(posting)
            idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
            tf = posting.get(chunk_id, 0)
            denom = tf + k1 * (1 - b + b * dl / max(1.0, self._avg_dl))
            score += idf * ((tf * (k1 + 1)) / max(1e-9, denom))
        return score


class SwarmRetriever:
    """Hybrid retriever — keyword (BM25) + semantic (cosine over embeddings).

    The semantic leg tries the shared embedding service and FAISS vector store
    from the NEXUS project; on any failure it gracefully degrades to BM25-only.
    """

    def __init__(self, max_chunks: int = 5000, enable_embeddings: bool = True) -> None:
        self._index = InMemoryIndex()
        self._max_chunks = max_chunks
        self._enable_embeddings = enable_embeddings
        # Lazy embedding service (created on first use)
        self._embedder: Any = None
        self._embeddings: dict[str, list[float]] = {}
        self._faiss: Any = None

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def add_chunks(self, chunks: list[TextChunk]) -> int:
        """Add chunks to the in-memory index; also try to embed them."""
        if not chunks:
            return 0
        # Cap to avoid unbounded memory
        if len(self._index.chunks) + len(chunks) > self._max_chunks:
            keep = self._max_chunks - len(self._index.chunks)
            chunks = chunks[: max(0, keep)]
        self._index.add(chunks)
        # Best-effort embeddings — only when enabled
        if self._enable_embeddings:
            try:
                self._embed_chunks(chunks)
            except Exception as exc:  # pragma: no cover - optional
                logger.debug("Embedding step skipped: %s", exc)
        return len(chunks)

    def _embed_chunks(self, chunks: list[TextChunk]) -> None:
        """Embed chunks and optionally push to FAISS. Best-effort.

        Bounded by ``EMBED_TIMEOUT_S`` to prevent network-bound hangs in tests
        or offline environments. Silently no-ops on any failure.
        """
        try:
            from backend.tools.embeddings import embed as shared_embed
        except Exception:
            return

        import asyncio

        async def _run() -> None:
            vecs: list[list[float]] = []
            ids: list[str] = []
            for c in chunks:
                try:
                    v = await asyncio.wait_for(shared_embed(c.text[:2000]), timeout=EMBED_TIMEOUT_S)
                    if v:
                        vecs.append(v)
                        ids.append(c.chunk_id)
                except Exception:
                    continue
            for cid, vec in zip(ids, vecs, strict=True):
                self._embeddings[cid] = vec
            # Try to mirror to FAISS
            try:
                from backend.cache.vector_store import FAISSEmbeddingStore

                if self._faiss is None:
                    self._faiss = FAISSEmbeddingStore()
                for cid, vec in zip(ids, vecs, strict=True):
                    self._faiss.add(vec, {"chunk_id": cid})
            except Exception:
                self._faiss = None  # not available, continue in-memory

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_run())
            else:
                loop.run_until_complete(_run())
        except RuntimeError:
            with contextlib.suppress(Exception):
                asyncio.run(_run())

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.4,
        language: str | None = None,
    ) -> list[RetrievalHit]:
        """Return top-k chunks by hybrid score.

        Combines BM25 keyword score + (optional) cosine similarity. When
        no embeddings are available the semantic leg contributes 0 and we
        fall back to pure keyword search.
        """
        if not query or not self._index.chunks:
            return []

        # ---- Keyword leg (BM25) ----
        keyword_scores: dict[str, float] = {}
        for chunk in self._index.chunks:
            if language and chunk.language and chunk.language != language:
                continue
            keyword_scores[chunk.chunk_id] = self._index.bm25_score(query, chunk.chunk_id)

        max_kw = max(keyword_scores.values()) if keyword_scores else 0.0
        if max_kw > 0:
            for k in keyword_scores:
                keyword_scores[k] /= max_kw

        # ---- Semantic leg (cosine) ----
        semantic_scores: dict[str, float] = self._semantic_ranks(query) if self._embeddings else {}

        # ---- Combine ----
        hits: list[RetrievalHit] = []
        for chunk in self._index.chunks:
            kw = keyword_scores.get(chunk.chunk_id, 0.0)
            sem = semantic_scores.get(chunk.chunk_id, 0.0)
            if language and chunk.language and chunk.language != language:
                continue
            score = semantic_weight * sem + keyword_weight * kw
            if score <= 0:
                continue
            hits.append(
                RetrievalHit(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    source_path=chunk.source_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    language=chunk.language,
                    score=score,
                    semantic_score=sem,
                    keyword_score=kw,
                    metadata=chunk.metadata,
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def _semantic_ranks(self, query: str) -> dict[str, float]:
        """Return chunk_id → normalised cosine similarity in [0,1]."""
        try:
            import asyncio

            from backend.tools.embeddings import embed as shared_embed
        except Exception:
            return {}

        async def _embed_query() -> list[float] | None:
            try:
                return await asyncio.wait_for(shared_embed(query), timeout=EMBED_TIMEOUT_S)
            except Exception:
                return None

        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # In an async context: skip sync semantic search this time
                    return {}
                qvec = loop.run_until_complete(_embed_query())
            except RuntimeError:
                qvec = asyncio.run(_embed_query())
        except Exception:
            return {}
        if not qvec:
            return {}

        results: dict[str, float] = {}
        for cid, vec in self._embeddings.items():
            sim = self._cosine(qvec, vec)
            if sim > 0:
                results[cid] = sim
        if results:
            m = max(results.values())
            for k in results:
                results[k] /= m
        return results

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "chunks": len(self._index.chunks),
            "embeddings": len(self._embeddings),
            "faiss_enabled": self._faiss is not None,
            "languages": dict(Counter(c.language for c in self._index.chunks if c.language)),
        }

    def clear(self) -> None:
        self._index = InMemoryIndex()
        self._embeddings.clear()
        self._faiss = None


# ---------------------------------------------------------------------------
# Index from local files
# ---------------------------------------------------------------------------


def index_directory(
    retriever: SwarmRetriever,
    root: str,
    include_globs: tuple[str, ...] = (
        "*.py",
        "*.ts",
        "*.tsx",
        "*.js",
        "*.jsx",
        "*.md",
        "*.rst",
        "*.json",
        "*.yaml",
        "*.yml",
        "*.toml",
        "*.sql",
        "*.sh",
        "*.html",
        "*.css",
        "*.scss",
        "*.rs",
        "*.go",
        "*.java",
        "*.kt",
        "*.cs",
        "*.cpp",
        "*.c",
        "*.h",
        "*.hpp",
    ),
    exclude_dirs: tuple[str, ...] = (
        "node_modules",
        ".next",
        "dist",
        "build",
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        ".idea",
        ".vscode",
        "logs",
        "data",
    ),
    max_files: int = 2000,
) -> int:
    """Walk ``root`` and index matching files. Returns the number of chunks added."""
    import os
    from pathlib import Path

    root_path = Path(root)
    if not root_path.exists():
        return 0

    files_read = 0
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Mutate dirnames in place to skip excluded dirs
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for fname in filenames:
            if not any(fname.endswith(g.lstrip("*")) for g in include_globs):
                continue
            full = Path(dirpath) / fname
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            from backend.swarm.rag.chunker import chunk_text, detect_language

            chunks = chunk_text(text, source_path=str(full), language=detect_language(str(full)))
            retriever.add_chunks(chunks)
            files_read += 1
            if files_read >= max_files:
                return retriever.stats()["chunks"]
    return retriever.stats()["chunks"]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_retriever: SwarmRetriever | None = None


def get_retriever() -> SwarmRetriever:
    global _retriever
    if _retriever is None:
        _retriever = SwarmRetriever()
    return _retriever


def reset_retriever() -> None:
    global _retriever
    _retriever = None


__all__ = [
    "RetrievalHit",
    "InMemoryIndex",
    "SwarmRetriever",
    "index_directory",
    "get_retriever",
    "reset_retriever",
]
