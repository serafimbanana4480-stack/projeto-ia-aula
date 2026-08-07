"""Semantic search over the codebase using the configured local embedding backend.

Uses ``nomic-embed-text`` by default when Ollama is the primary provider.
If no embedding model is available, returns empty results gracefully.

The vector store now supports:
- Syntax-aware chunking for Python (function/class level) with line-based fallback
- Rich metadata (file path, language, symbol info, line ranges, content hash)
- Incremental re-indexing (detects changed files via mtime + SHA-256 hash)
- On-disk persistence of the index (JSON snapshot in ``data/embeddings_index.json``)
- Thread-safe concurrent access via an asyncio lock

For production, swap the JSON snapshot for ChromaDB / Qdrant — the public
interface stays the same.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# FAISS ANN index — optional; falls back to O(n) scan if unavailable
try:
    import faiss
    import numpy as np

    _HAVE_FAISS = True
except ImportError:
    _HAVE_FAISS = False
    faiss = None
    np = None

# Preferred embedding models in order of preference
_EMBED_MODELS = ["nomic-embed-text", "sentence-transformers/all-MiniLM-L6-v2"]
_EMBED_DIM = 384  # default dimension; overridden by actual model output

# Batch size for embedding generation. Tuned for local Ollama; increase
# for cloud providers with higher throughput.
EMBED_BATCH_SIZE = 16

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
INDEX_SNAPSHOT_PATH = DATA_DIR / "embeddings_index.json"
INDEX_META_PATH = DATA_DIR / "embeddings_index_meta.json"

# In-memory vector store: {chunk_id: (embedding, CodeChunk)}
_store: dict[str, tuple[list[float], CodeChunk]] = {}
_store_lock: asyncio.Lock = asyncio.Lock()

# FAISS index for fast ANN search (mirrors _store contents)
_faiss_index: Any = None
_faiss_dim: int = _EMBED_DIM
_faiss_id_map: dict[int, str] = {}  # FAISS vector ID → chunk_id


@dataclass
class CodeChunk:
    file: str
    start_line: int
    end_line: int
    content: str
    score: float = 0.0
    language: str = ""
    symbol_name: str = ""
    symbol_type: str = ""
    chunk_hash: str = ""
    indexed_at: float = field(default_factory=lambda: float(os.times()[0]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "score": self.score,
            "language": self.language,
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
            "chunk_hash": self.chunk_hash,
            "indexed_at": self.indexed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodeChunk:
        return cls(
            file=data["file"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            content=data["content"],
            score=data.get("score", 0.0),
            language=data.get("language", ""),
            symbol_name=data.get("symbol_name", ""),
            symbol_type=data.get("symbol_type", ""),
            chunk_hash=data.get("chunk_hash", ""),
            indexed_at=data.get("indexed_at", 0.0),
        )


async def _get_available_model() -> str | None:
    """Return the first available embedding model."""
    return _EMBED_MODELS[0]


async def _call_embed(provider, texts: list[str], model: str) -> list[list[float] | None] | None:
    """Call provider.embed(...) robustly.

    Some provider implementations return a coroutine/awaitable instead of
    the concrete list. Detect that case and await it once. Any failure
    is surfaced as None so the caller can fall back cleanly.
    """
    try:
        maybe_awaitable = provider.embed(texts, model=model)
        if inspect.isawaitable(maybe_awaitable):
            maybe_awaitable = await asyncio.ensure_future(maybe_awaitable)
        # Some providers (e.g. sentence-transformers, ONNX runtime) return
        # numpy arrays with a leading batch dimension even for single texts.
        # Normalise to list[list[float]] so the FAISS indexer always sees a
        # 2-D array of shape (n, dim).
        try:
            import numpy as _np

            if isinstance(maybe_awaitable, _np.ndarray):
                arr = maybe_awaitable
                if arr.ndim == 3:
                    arr = arr.squeeze(axis=0)
                if arr.ndim == 1:
                    arr = arr.reshape(1, -1)
                maybe_awaitable = arr.tolist()
        except Exception:
            pass
        return maybe_awaitable
    except Exception as exc:
        logger.warning("Embed provider call failed: %s", exc)
        return None


async def _embed_batch_with_fallback(texts: list[str], model: str) -> list[list[float] | None]:
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
        result = await _call_embed(provider, texts, model)
        if result is None:
            raise RuntimeError("Embedding provider returned no result")
        if not isinstance(result, list):
            logger.warning("Embedding provider returned non-list result — falling back")
            raise RuntimeError("Embedding provider returned non-list result")
        if len(result) != len(texts):
            logger.warning(
                "Embedding batch returned %d results for %d texts — falling back",
                len(result),
                len(texts),
            )
            raise RuntimeError("Embedding batch size mismatch")
        return result
    except Exception as exc:
        if len(texts) == 1:
            logger.warning("Embedding failed for single text: %s", exc)
            return [None]
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
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _sha256(text: str) -> str:
    """Return SHA-256 hex digest of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _detect_language(filepath: Path) -> str:
    """Infer programming language from file extension."""
    ext = filepath.suffix.lower()
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript-react",
        ".js": "javascript",
        ".jsx": "javascript-react",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".kt": "kotlin",
        ".md": "markdown",
        ".txt": "text",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".html": "html",
        ".css": "css",
        ".sh": "shell",
        ".sql": "sql",
    }
    return mapping.get(ext, "")


def _init_faiss_index(dim: int | None = None) -> None:
    """Initialize or reset the FAISS index with the given dimension."""
    global _faiss_index, _faiss_dim, _faiss_id_map
    if not _HAVE_FAISS:
        return
    _faiss_dim = dim or _EMBED_DIM
    _faiss_id_map = {}
    quantizer = faiss.IndexFlatL2(_faiss_dim)
    # FAISS IndexIVFFlat requires at least nlist training vectors. With a
    # very small corpus (e.g. 1 chunk during unit tests) the default
    # ``max(10, len(_store) // 10)`` produces nlist > corpus, so the index
    # is never trained and ``add`` fails with "is_trained failed".
    # Clamp nlist to never exceed the available training data.
    requested = max(1, len(_store) // 10)
    nlist = max(1, min(100, requested, max(1, len(_store))))
    _faiss_index = faiss.IndexIVFFlat(quantizer, _faiss_dim, nlist)
    if len(_store) >= nlist:
        vectors = []
        for emb, _ in _store.values():
            if len(emb) == _faiss_dim:
                vectors.append(emb)
        if vectors:
            _faiss_index.train(np.array(vectors, dtype=np.float32))


def _rebuild_faiss_index() -> None:
    """Rebuild the FAISS index from the current _store contents."""
    global _faiss_index, _faiss_id_map
    if not _HAVE_FAISS or not _store:
        return

    dims = {len(emb) for emb, _ in _store.values()}
    if not dims:
        return
    dim = max(dims)
    _init_faiss_index(dim)

    if _faiss_index is None:
        return

    vectors = []
    _faiss_id_map = {}
    for idx, (chunk_id, (embedding, _)) in enumerate(_store.items()):
        if len(embedding) == dim:
            vectors.append(embedding)
            _faiss_id_map[idx] = chunk_id

    if not vectors:
        return

    vec_array = np.array(vectors, dtype=np.float32)
    if not _faiss_index.is_trained:
        # FAISS IVF needs at least nlist training points. With a tiny
        # corpus the training step is harmless — we just expose the
        # current batch as the training set so add() does not fail.
        _faiss_index.train(vec_array)
    _faiss_index.add(vec_array)


def _chunk_by_lines(
    content: str, chunk_size: int = 100, overlap: int = 20
) -> list[tuple[int, int, str]]:
    """Split content into overlapping line-based chunks.

    Returns a list of (start_line, end_line, chunk_text).
    """
    lines = content.splitlines()
    chunks: list[tuple[int, int, str]] = []
    i = 0
    step = max(1, chunk_size - overlap)
    while i < len(lines):
        end = min(i + chunk_size, len(lines))
        chunk_lines = lines[i:end]
        chunks.append((i + 1, end, "\n".join(chunk_lines)))
        if end == len(lines):
            break
        i += step
    return chunks


def _chunk_python(content: str) -> list[tuple[int, int, str, str, str]]:
    """Syntax-aware chunking for Python source files.

    Returns a list of (start_line, end_line, chunk_text, symbol_type, symbol_name).
    Falls back to line-based chunking if parsing fails.
    """
    try:
        import ast

        tree = ast.parse(content)
    except SyntaxError:
        return [(start, end, text, "", "") for start, end, text in _chunk_by_lines(content)]

    chunks: list[tuple[int, int, str, str, str]] = []
    lines = content.splitlines()

    def _extract(start: int, end: int, symbol_type: str, symbol_name: str) -> None:
        chunk_lines = lines[start - 1 : end]
        chunk_text = "\n".join(chunk_lines)
        chunks.append((start, end, chunk_text, symbol_type, symbol_name))

    for node in ast.iter_child_nodes(tree):
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            _extract(start, end, "function", node.name)
        elif isinstance(node, ast.ClassDef):
            _extract(start, end, "class", node.name)
        elif isinstance(node, ast.Import):
            _extract(start, end, "import", "")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(alias.name for alias in node.names)
            _extract(start, end, "import", f"{module}.{names}" if module else names)

    if not chunks:
        return [(start, end, text, "", "") for start, end, text in _chunk_by_lines(content)]

    if len(chunks) > 1:
        overview = "\n".join(
            f"{symbol_type} {symbol_name}" if symbol_name else text.splitlines()[0]
            for _, _, text, symbol_type, symbol_name in chunks
        )
        chunks.insert(0, (1, min(20, len(lines)), overview, "overview", ""))

    return chunks


def _chunk_file(content: str, language: str) -> list[tuple[int, int, str, str, str]]:
    """Choose chunking strategy based on language."""
    if language == "python":
        return _chunk_python(content)
    return [
        (start, end, text, "", "")
        for start, end, text in _chunk_by_lines(content, chunk_size=60, overlap=10)
    ]


def _load_index_snapshot() -> dict[str, tuple[list[float], CodeChunk]]:
    """Load the embedding index snapshot from disk if it exists."""
    if not INDEX_SNAPSHOT_PATH.exists():
        return {}

    try:
        with INDEX_SNAPSHOT_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        store: dict[str, tuple[list[float], CodeChunk]] = {}
        for chunk_id, item in raw.items():
            if not isinstance(item, dict) or "embedding" not in item or "chunk" not in item:
                continue
            embedding = item["embedding"]
            chunk = CodeChunk.from_dict(item["chunk"])
            store[chunk_id] = (embedding, chunk)

        logger.info("Loaded %d chunks from embedding snapshot", len(store))
        _rebuild_faiss_index()
        return store
    except Exception as exc:
        logger.warning("Failed to load embedding snapshot: %s", exc)
        return {}


def _save_index_snapshot(store: dict[str, tuple[list[float], CodeChunk]]) -> None:
    """Persist the embedding index snapshot to disk."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        snapshot: dict[str, dict[str, Any]] = {}
        for chunk_id, (embedding, chunk) in store.items():
            snapshot[chunk_id] = {
                "embedding": embedding,
                "chunk": chunk.to_dict(),
            }
        with INDEX_SNAPSHOT_PATH.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)

        with INDEX_META_PATH.open("w", encoding="utf-8") as f:
            json.dump(
                {"chunk_count": len(store), "format_version": 1},
                f,
                ensure_ascii=False,
            )

        logger.info("Saved %d chunks to embedding snapshot", len(store))
    except Exception as exc:
        logger.warning("Failed to save embedding snapshot: %s", exc)


def _load_index_meta() -> dict[str, Any]:
    """Load lightweight index metadata."""
    if not INDEX_META_PATH.exists():
        return {}
    try:
        with INDEX_META_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


async def index_codebase(
    root: str,
    *,
    exclude_dirs: list[str] | None = None,
    force_reindex: bool = False,
) -> int:
    """Walk `root`, chunk files, embed and store. Returns chunk count.

    Only indexes files with common code extensions. Skips binary files,
    hidden directories, and very large files (>1MB).

    Args:
        root: Project root path to index.
        exclude_dirs: Directory names to skip.
        force_reindex: If True, ignore the on-disk snapshot and rebuild.
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

    exclude = set(
        exclude_dirs
        or [
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            ".next",
            "dist",
            "build",
            ".pytest_cache",
        ]
    )

    CODE_EXTENSIONS = {
        ".py",
        ".ts",
        ".js",
        ".tsx",
        ".jsx",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".html",
        ".css",
        ".sh",
        ".sql",
    }

    async with _store_lock:
        if force_reindex or not _store:
            _store = {} if force_reindex else _load_index_snapshot()

        existing_by_file: dict[str, set[str]] = {}
        for chunk_id, (_, chunk) in _store.items():
            existing_by_file.setdefault(chunk.file, set()).add(chunk_id)

        chunk_count = 0
        batch_texts: list[str] = []
        batch_meta: list[tuple[str, CodeChunk]] = []
        current_file_chunks: set[str] = set()

        for filepath in root_path.rglob("*"):
            if any(part.startswith(".") for part in filepath.parts):
                continue
            if filepath.suffix not in CODE_EXTENSIONS:
                continue
            if any(part in exclude for part in filepath.parts):
                continue

            try:
                stat = filepath.stat()
                if stat.st_size > 1_000_000:
                    continue
                content = filepath.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            language = _detect_language(filepath)
            file_key = str(filepath)
            current_file_chunks = set()
            file_mtime = stat.st_mtime

            chunks = _chunk_file(content, language)
            for start_line, end_line, chunk_text, symbol_type, symbol_name in chunks:
                chunk_hash = _sha256(chunk_text)
                chunk_id = f"{file_key}::{symbol_type}:{symbol_name or start_line}"

                if chunk_id in _store:
                    existing_embedding, existing_chunk = _store[chunk_id]
                    if (
                        existing_chunk.chunk_hash == chunk_hash
                        and existing_chunk.indexed_at >= file_mtime
                    ):
                        current_file_chunks.add(chunk_id)
                        continue

                code_chunk = CodeChunk(
                    file=file_key,
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_text,
                    language=language,
                    symbol_name=symbol_name,
                    symbol_type=symbol_type,
                    chunk_hash=chunk_hash,
                    indexed_at=file_mtime,
                )
                batch_texts.append(chunk_text)
                batch_meta.append((chunk_id, code_chunk))
                current_file_chunks.add(chunk_id)

                if len(batch_texts) >= EMBED_BATCH_SIZE:
                    embeddings = await _embed_batch_with_fallback(batch_texts, model)
                    for emb, (cid, cc) in zip(embeddings, batch_meta, strict=False):
                        if emb is None:
                            continue
                        # Normalise provider output to a flat list[float] so
                        # the FAISS indexer always sees 2-D arrays.
                        try:
                            import numpy as _np

                            if isinstance(emb, _np.ndarray):
                                arr = emb
                                while arr.ndim > 1:
                                    arr = arr[0]
                                emb = arr.tolist()
                        except Exception:
                            pass
                            _store[cid] = (emb, cc)
                            chunk_count += 1
                    batch_texts = []
                    batch_meta = []

            stale = existing_by_file.get(file_key, set()) - current_file_chunks
            for stale_id in stale:
                _store.pop(stale_id, None)

        if batch_texts:
            embeddings = await _embed_batch_with_fallback(batch_texts, model)
            for emb, (cid, cc) in zip(embeddings, batch_meta, strict=False):
                if emb is None:
                    continue
                # Normalise provider output to a flat list[float] so the
                # FAISS indexer always sees 2-D arrays.
                try:
                    import numpy as _np

                    if isinstance(emb, _np.ndarray):
                        arr = emb
                        while arr.ndim > 1:
                            arr = arr[0]
                        emb = arr.tolist()
                except Exception:
                    pass
                _store[cid] = (emb, cc)
                chunk_count += 1

        _save_index_snapshot(_store)
        _rebuild_faiss_index()

    logger.info("Indexed %d new/updated chunks from %s (total %d)", chunk_count, root, len(_store))
    return chunk_count


async def search_codebase(query: str, k: int = 8) -> list[CodeChunk]:
    """Semantic search returning top-k code chunks.

    Uses FAISS ANN index when available (O(log n)), falls back to
    linear scan (O(n)) when FAISS is not installed.
    """
    if not _store:
        return []

    try:
        query_embedding = await embed(query)
    except RuntimeError:
        return _keyword_search(query, k)

    # Try FAISS first (O(log n))
    if _HAVE_FAISS and _faiss_index is not None and _faiss_index.ntotal > 0:
        try:
            query_vec = np.array([query_embedding], dtype=np.float32)
            if query_vec.shape[1] != _faiss_index.d:
                _rebuild_faiss_index()

            actual_k = min(k, _faiss_index.ntotal)
            if _faiss_index.ntotal > 0:
                distances, indices = _faiss_index.search(query_vec, actual_k)

                results = []
                for dist, idx in zip(distances[0], indices[0], strict=False):
                    if idx >= 0 and idx in _faiss_id_map:
                        chunk_id = _faiss_id_map[int(idx)]
                        embedding, chunk = _store[chunk_id]
                        chunk.score = 1.0 / (1.0 + float(dist))
                        results.append(chunk)

                if results:
                    return results
        except Exception as exc:
            logger.debug("FAISS search failed, falling back to linear scan: %s", exc)

    # Fallback: linear O(n) scan (original behavior)
    scored: list[tuple[float, CodeChunk]] = []
    for _chunk_id, (embedding, chunk) in _store.items():
        sim = _cosine_sim(query_embedding, embedding)
        chunk.score = sim
        scored.append((sim, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:k]]


def _keyword_search(query: str, k: int = 8) -> list[CodeChunk]:
    """Simple keyword fallback when embedding is unavailable."""
    terms = set(query.lower().split())
    results: list[CodeChunk] = []

    for _chunk_id, (_, chunk) in _store.items():
        content_lower = chunk.content.lower()
        matches = sum(1 for t in terms if t in content_lower)
        if matches > 0:
            chunk.score = matches / len(terms)
            results.append(chunk)

    results.sort(key=lambda c: c.score, reverse=True)
    return results[:k]


async def get_index_stats() -> dict[str, Any]:
    """Return statistics about the current embedding index."""
    async with _store_lock:
        files: set[str] = set()
        languages: dict[str, int] = {}
        symbol_types: dict[str, int] = {}
        for _, chunk in _store.values():
            files.add(chunk.file)
            if chunk.language:
                languages[chunk.language] = languages.get(chunk.language, 0) + 1
            if chunk.symbol_type:
                symbol_types[chunk.symbol_type] = symbol_types.get(chunk.symbol_type, 0) + 1

        faiss_stats = {}
        if _HAVE_FAISS and _faiss_index is not None:
            faiss_stats = {
                "faiss_available": True,
                "faiss_ntotal": _faiss_index.ntotal,
                "faiss_dim": _faiss_dim,
                "faiss_trained": _faiss_index.is_trained
                if hasattr(_faiss_index, "is_trained")
                else True,
            }
        else:
            faiss_stats = {"faiss_available": False}

        return {
            "total_chunks": len(_store),
            "total_files": len(files),
            "by_language": languages,
            "by_symbol_type": symbol_types,
            "snapshot_path": str(INDEX_SNAPSHOT_PATH),
            **faiss_stats,
        }


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
                "language": r.language,
                "symbol_name": r.symbol_name,
                "symbol_type": r.symbol_type,
                "content": r.content[:500],
            }
            for r in results
        ],
        "total_found": len(results),
    }


async def _index_codebase_tool(
    project_path: str = ".",
    force_reindex: bool = False,
) -> dict:
    """Tool wrapper for index_codebase."""
    root = Path(project_path).resolve()
    if not root.is_dir():
        return {"error": f"Path is not a directory: {project_path}"}

    count = await index_codebase(str(root), force_reindex=force_reindex)
    stats = await get_index_stats()
    return {
        "chunks_indexed": count,
        "total_chunks": stats["total_chunks"],
        "project_path": str(root),
    }


async def _index_stats_tool() -> dict:
    """Tool wrapper for get_index_stats."""
    return await get_index_stats()


register_tool(
    ToolSpec(
        name="search_codebase",
        description=(
            "Semantic search over the indexed codebase using embeddings. "
            "Returns the most relevant code chunks for a natural-language query. "
            "The codebase must be indexed first via /api/embeddings/index or the "
            "index_codebase tool."
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

register_tool(
    ToolSpec(
        name="index_codebase",
        description=(
            "Index a project directory for semantic search. "
            "Chunks source files, generates embeddings, and stores them. "
            "Supports incremental updates based on file hashes."
        ),
        schema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path to index",
                },
                "force_reindex": {
                    "type": "boolean",
                    "default": False,
                    "description": "Ignore the existing snapshot and reindex everything",
                },
            },
            "required": [],
        },
        handler=_index_codebase_tool,
    )
)

register_tool(
    ToolSpec(
        name="index_stats",
        description="Return statistics about the current codebase embedding index.",
        schema={
            "type": "object",
            "properties": {},
        },
        handler=_index_stats_tool,
    )
)

# ---------------------------------------------------------------------------
# Symbol-search tools — used by agents via auto-upgrade (base.py:857-872)
# Expose filtered semantic search over code symbols and a dedicated
# index action so agents can trigger indexing independently.
# ---------------------------------------------------------------------------


async def _search_symbols_handler(
    query: str = "",
    kind: str = "any",
    limit: int = 20,
) -> dict:
    """Search for symbols (functions, classes, variables) in the indexed codebase.

    Wraps ``search_codebase`` with an optional ``kind`` filter so the
    agent can narrow results to a particular symbol type.
    """
    if not query.strip():
        return {"error": "Query cannot be empty."}

    try:
        results = await search_codebase(query, k=limit)
    except RuntimeError as exc:
        return {"error": f"Semantic search unavailable: {exc}"}

    if not results:
        return {
            "query": query,
            "results": [],
            "message": (
                "Codebase not indexed yet. Use the index_symbols tool "
                "to index the project first."
            ),
        }

    # Apply optional kind filter (function, class, variable, any)
    if kind != "any":
        results = [r for r in results if r.symbol_type.lower() == kind.lower()]

    # Deduplicate by (file, symbol_name) — keep highest score
    seen: set[tuple[str, str]] = set()
    deduped = []
    for r in results:
        key = (r.file, r.symbol_name or f"{r.start_line}")
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    results = deduped[:limit]

    return {
        "query": query,
        "results": [
            {
                "file": r.file,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "score": round(r.score, 3),
                "language": r.language,
                "symbol_name": r.symbol_name,
                "symbol_type": r.symbol_type,
                "content": r.content[:500],
            }
            for r in results
        ],
        "total_found": len(results),
    }


async def _index_symbols_handler(
    project_path: str = ".",
    force: bool = False,
    force_reindex: bool | None = None,
) -> dict:
    """Index the project for symbol search.

    Delegates to ``index_codebase`` which walks the project, chunks
    source files, generates embeddings, and persists the index to disk.
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        return {"error": f"Path is not a directory: {project_path}"}

    try:
        # ``force_reindex`` was the original public argument. Keep accepting
        # it while exposing the shorter ``force`` name in new prompts.
        should_force = force if force_reindex is None else force_reindex
        count = await index_codebase(str(root), force_reindex=should_force)
    except Exception as exc:
        return {"error": f"Indexing failed: {exc}"}

    stats = await get_index_stats()
    return {
        "chunks_indexed": count,
        "total_chunks": stats["total_chunks"],
        "project_path": str(root),
    }


register_tool(ToolSpec(
    name="search_symbols",
    description=(
        "Search for symbols (functions, classes, variables) in the indexed codebase. "
        "The codebase must be indexed first via index_symbols."
    ),
    schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Symbol name or partial name to search"},
            "kind": {
                "type": "string",
                "enum": ["function", "class", "variable", "any"],
                "default": "any",
                "description": "Filter by symbol type",
            },
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "Maximum number of results",
            },
        },
        "required": ["query"],
    },
    handler=_search_symbols_handler,
))

register_tool(ToolSpec(
    name="index_symbols",
    description="Index the project for symbol search. Chunks source files and generates embeddings.",
    schema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Project root path (default: current working directory)",
            },
            "force": {
                "type": "boolean",
                "default": False,
                "description": "Force re-index even if cache exists",
            },
            "force_reindex": {
                "type": "boolean",
                "default": False,
                "description": "Deprecated alias for force; force a full re-index",
            },
        },
    },
    handler=_index_symbols_handler,
))
