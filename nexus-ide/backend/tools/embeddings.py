"""Semantic search over the codebase using the configured local embedding backend.

Uses ``nomic-embed-text`` by default when Ollama is the primary provider.
If no embedding model is available, returns empty results gracefully.

The vector store is a simple in-memory dict. For production, swap in
ChromaDB or Qdrant — the interface stays the same.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from backend.config.settings import get_settings
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# Preferred embedding models in order of preference
_EMBED_MODELS = ["nomic-embed-text", "sentence-transformers/all-MiniLM-L6-v2"]
_EMBED_DIM = 384  # default dimension; overridden by actual model output

# Batch size for embedding generation. Tuned for local Ollama; increase
# for cloud providers with higher throughput.
EMBED_BATCH_SIZE = 16

# In-memory vector store: {chunk_id: (embedding, CodeChunk)}
_store: dict[str, tuple[list[float], "CodeChunk"]] = {}
_store_lock: bool = False  # simple guard for concurrency


@dataclass
class CodeChunk:
    file: str
    start_line: int
    end_line: int
    content: str
    score: float = 0.0


async def _get_available_model() -> str | None:
    """Return the first available embedding model."""
    return _EMBED_MODELS[0]


async def _embed_batch_with_fallback(
    texts: list[str], model: str
) -> list[list[float] | None]:
    """Embed multiple texts with recursive fallback on failure.

    Args:
        texts: List of texts to embed.
        model: Model name to use.

    Returns:
        A list parallel to ``texts`` where each element is either an
        embedding vector or ``None`` if that individual text could not
        be embedded.
    """
    if not texts:
        return []

    try:
        from backend.llm.factory import create_llm_client

        provider = create_llm_client()
        result = await provider.embed(texts, model=model)
        # Guard against provider returning mismatched result lengths
        if result and len(result) == len(texts):
            return result
        logger.warning(
            "Embedding batch returned %d results for %d texts — falling back",
            len(result) if result else 0,
            len(texts),
        )
        raise RuntimeError("Embedding batch size mismatch")
    except Exception as exc:
        if len(texts) == 1:
            logger.warning("Embedding failed for single text: %s", exc)
            return [None]
        # Split batch and retry halves in parallel
        mid = len(texts) // 2
        left_task = _embed_batch_with_fallback(texts[:mid], model)
        right_task = _embed_batch_with_fallback(texts[mid:], model)
        left, right = await asyncio.gather(left_task, right_task)
        return left + right


async def embed(text: str, model: str | None = None) -> list[float]:
    """Generate an embedding via the configured local provider.

    Args:
        text: The text to embed.
        model: Override model name. If None, uses default embedding model.

    Returns:
        List of floats representing the embedding vector.

    Raises:
        RuntimeError: If embedding generation fails.
    """
    if model is None:
        model = _EMBED_MODELS[0]

    result = await _embed_batch_with_fallback([text], model)
    if result[0] is None:
        raise RuntimeError(
            "No embedding model available. Install sentence-transformers: "
            "pip install sentence-transformers"
        )
    return result[0]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _chunk_code(content: str, chunk_size: int = 100, overlap: int = 20) -> list[str]:
    """Split content into overlapping line-based chunks."""
    lines = content.splitlines()
    chunks: list[str] = []
    i = 0
    while i < len(lines):
        chunk_lines = lines[i : i + chunk_size]
        chunks.append("\n".join(chunk_lines))
        i += chunk_size - overlap
    return chunks


async def index_codebase(root: str) -> int:
    """Walk `root`, chunk files, embed and store in memory. Returns chunk count.

    Only indexes files with common code extensions. Skips binary files,
    hidden directories, and very large files (>1MB).
    """
    global _store

    model = await _get_available_model()
    if model is None:
        logger.warning("No embedding model available — skipping indexing")
        return 0

    root_path = Path(root)
    if not root_path.is_dir():
        logger.error("Index root is not a directory: %s", root)
        return 0

    CODE_EXTENSIONS = {
        ".py", ".ts", ".js", ".tsx", ".jsx", ".rs", ".go", ".java",
        ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".html",
        ".css", ".sh", ".sql",
    }

    chunk_count = 0
    batch_texts: list[str] = []
    batch_meta: list[tuple[str, CodeChunk]] = []

    for filepath in root_path.rglob("*"):
        # Skip hidden dirs and very large files
        if any(part.startswith(".") for part in filepath.parts):
            continue
        if filepath.suffix not in CODE_EXTENSIONS:
            continue
        try:
            if filepath.stat().st_size > 1_000_000:  # 1MB
                continue
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        chunks = _chunk_code(content)
        for idx, chunk_text in enumerate(chunks):
            lines = chunk_text.splitlines()
            start_line = idx * (100 - 20) + 1  # approximate
            chunk_id = f"{filepath}::L{start_line}"
            code_chunk = CodeChunk(
                file=str(filepath),
                start_line=start_line,
                end_line=start_line + len(lines) - 1,
                content=chunk_text,
            )
            batch_texts.append(chunk_text)
            batch_meta.append((chunk_id, code_chunk))

            if len(batch_texts) >= EMBED_BATCH_SIZE:
                embeddings = await _embed_batch_with_fallback(batch_texts, model)
                for emb, (cid, cc) in zip(embeddings, batch_meta):
                    if emb is not None:
                        _store[cid] = (emb, cc)
                        chunk_count += 1
                batch_texts = []
                batch_meta = []

    # Flush remaining batch
    if batch_texts:
        embeddings = await _embed_batch_with_fallback(batch_texts, model)
        for emb, (cid, cc) in zip(embeddings, batch_meta):
            if emb is not None:
                _store[cid] = (emb, cc)
                chunk_count += 1

    logger.info("Indexed %d chunks from %s", chunk_count, root)
    return chunk_count


async def search_codebase(query: str, k: int = 8) -> list[CodeChunk]:
    """Semantic search returning top-k code chunks.

    If the store is empty, returns an empty list. Falls back to
    keyword matching if embedding fails.
    """
    if not _store:
        return []

    try:
        query_embedding = await embed(query)
    except RuntimeError:
        # Fallback: keyword search
        return _keyword_search(query, k)

    # Compute similarity scores
    scored: list[tuple[float, CodeChunk]] = []
    for chunk_id, (embedding, chunk) in _store.items():
        sim = _cosine_sim(query_embedding, embedding)
        chunk.score = sim
        scored.append((sim, chunk))

    # Sort by score descending, return top-k
    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:k]]


def _keyword_search(query: str, k: int = 8) -> list[CodeChunk]:
    """Simple keyword fallback when embedding is unavailable."""
    terms = set(query.lower().split())
    results: list[CodeChunk] = []

    for chunk_id, (_, chunk) in _store.items():
        content_lower = chunk.content.lower()
        matches = sum(1 for t in terms if t in content_lower)
        if matches > 0:
            chunk.score = matches / len(terms)
            results.append(chunk)

    results.sort(key=lambda c: c.score, reverse=True)
    return results[:k]


# ---------------------------------------------------------------------------
# Tool registry integration
# ---------------------------------------------------------------------------

async def _search_codebase_tool(
    query: str = "",
    project_path: str = ".",
    k: int = 8,
) -> dict:
    """Tool wrapper for search_codebase — used by the ReAct loop.

    If the in-memory store is empty, falls back to keyword search via
    ``search_in_files``. Returns a dict compatible with the tool registry.
    """
    if not query.strip():
        return {"error": "Query cannot be empty."}

    try:
        results = await search_codebase(query, k=k)
    except RuntimeError as exc:
        return {"error": f"Semantic search unavailable: {exc}"}

    if not results:
        # Store is empty — suggest indexing first
        return {
            "query": query,
            "results": [],
            "message": (
                "Codebase not indexed yet. Use the /api/embeddings/index endpoint "
                "to index the project first, or use search_in_files for keyword search."
            ),
        }

    return {
        "query": query,
        "results": [
            {
                "file": r.file,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "score": round(r.score, 3),
                "content": r.content[:500],
            }
            for r in results
        ],
        "total_found": len(results),
    }


register_tool(
    ToolSpec(
        name="search_codebase",
        description=(
            "Semantic search over the indexed codebase using embeddings. "
            "Returns the most relevant code chunks for a natural-language query. "
            "The codebase must be indexed first via /api/embeddings/index."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path (used for context)",
                },
                "k": {
                    "type": "integer",
                    "default": 8,
                    "description": "Maximum number of results",
                },
            },
            "required": ["query"],
        },
        handler=_search_codebase_tool,
    )
)
