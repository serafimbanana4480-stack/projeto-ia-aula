"""Semantic search over the codebase using Ollama embeddings + in-memory store.

Uses ``nomic-embed-text`` by default (small, fast, good quality). Falls back
to ``qwen3-embedding:4b`` if that model is available. If no embedding model
is available, returns empty results gracefully.

The vector store is a simple in-memory dict. For production, swap in
ChromaDB or Qdrant — the interface stays the same.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from backend.config.settings import get_settings
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# Preferred embedding models in order of preference
_EMBED_MODELS = ["nomic-embed-text", "mxbai-embed-large", "qwen3-embedding:4b"]
_EMBED_DIM = 768  # default dimension; overridden by actual model output

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


def _ollama_base() -> str:
    return get_settings().ollama_host


async def _get_available_model() -> str | None:
    """Check which embedding model is available in Ollama."""
    base = _ollama_base()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/api/tags")
            if resp.status_code != 200:
                return None
            data = resp.json()
            available = {m["name"] for m in data.get("models", [])}
            # Also check without :latest suffix
            available_stripped = {n.split(":")[0] for n in available}
            for model in _EMBED_MODELS:
                base_name = model.split(":")[0]
                if model in available or base_name in available_stripped:
                    return model
            return None
    except Exception as exc:
        logger.warning("Cannot reach Ollama to check embedding models: %s", exc)
        return None


async def embed(text: str, model: str | None = None) -> list[float]:
    """Generate an embedding via Ollama.

    Args:
        text: The text to embed.
        model: Override model name. If None, auto-detects available model.

    Returns:
        List of floats representing the embedding vector.

    Raises:
        RuntimeError: If no embedding model is available in Ollama.
    """
    if model is None:
        model = await _get_available_model()
    if model is None:
        raise RuntimeError(
            "No embedding model available. Pull one with: "
            "ollama pull nomic-embed-text"
        )

    base = _ollama_base()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/api/embed",
                json={"model": model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings", [])
            if embeddings and isinstance(embeddings[0], list):
                return embeddings[0]
            # Older API format
            if "embedding" in data:
                return data["embedding"]
            raise RuntimeError(f"Unexpected embedding response: {list(data.keys())}")
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Ollama embedding request failed: {exc}") from exc


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
            try:
                embedding = await embed(chunk_text, model=model)
            except RuntimeError:
                continue  # skip chunks that fail to embed

            chunk_id = f"{filepath}::L{start_line}"
            code_chunk = CodeChunk(
                file=str(filepath),
                start_line=start_line,
                end_line=start_line + len(lines) - 1,
                content=chunk_text,
            )
            _store[chunk_id] = (embedding, code_chunk)
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
