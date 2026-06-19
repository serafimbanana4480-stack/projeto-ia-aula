"""
Vector Store — FAISS-based ANN index for sub-linear embedding search.

Replaces the O(n) dict scan in tool/embeddings.py with a FAISS IVF index
for O(log n) approximate nearest neighbor search.

Supports:
- IVF (Inverted File) index for fast approximate search
- L2 distance converted to cosine similarity score
- Metadata persistence alongside vectors
- On-disk persistence for reuse across restarts
- Batch add and search operations
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _require_faiss():
    """Import and return the ``faiss`` module.

    ``faiss``/``faiss-cpu`` is an optional dependency. The module
    ``backend.cache.vector_store`` must remain importable without it so the
    rest of the backend keeps working; only callers that actually need the
    vector store pay the cost. When faiss is missing we raise a clear,
    actionable error instead of a raw ``ModuleNotFoundError``.
    """
    try:
        import faiss  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on env
        raise RuntimeError("faiss-cpu não instalado — instale com: pip install faiss-cpu") from exc
    return faiss


class FAISSEmbeddingStore:
    """Vector store using FAISS IVF index for sub-linear similarity search.

    Args:
        dimension: Embedding dimension (default 384 for nomic-embed-text).
        index_path: Directory path for index persistence.
        nlist: Number of IVF centroids (clusters). More = faster search but
               lower recall. Default 100.
    """

    def __init__(
        self,
        dimension: int = 384,
        index_path: str = ".embeddings_index",
        nlist: int = 100,
    ):
        self.dimension = dimension
        self.index_path = Path(index_path)
        self.nlist = nlist

        self._index: Any = None
        self._metadata: list[dict] = []
        self._id_counter = 0

        # Performance metrics
        self._total_searches = 0
        self._total_search_time_ms = 0.0

        self._load_or_create_index()

    # ------------------------------------------------------------------
    # Index lifecycle
    # ------------------------------------------------------------------

    def _load_or_create_index(self) -> None:
        """Load existing index from disk or create a new one."""
        faiss = _require_faiss()

        idx_file = self.index_path / "faiss.index"
        meta_file = self.index_path / "metadata.jsonl"

        if idx_file.exists() and meta_file.exists():
            try:
                self._index = faiss.read_index(str(idx_file))
                with open(meta_file, encoding="utf-8") as f:
                    self._metadata = [json.loads(line) for line in f if line.strip()]
                self._id_counter = len(self._metadata)
                logger.info(
                    "Loaded FAISS index: %d vectors, %d dims",
                    len(self._metadata),
                    self.dimension,
                )
                return
            except Exception as e:
                logger.warning("Failed to load FAISS index, creating new: %s", e)

        # Create new IVF index
        quantizer = faiss.IndexFlatL2(self.dimension)
        self._index = faiss.IndexIVFFlat(quantizer, self.dimension, self.nlist)
        if not self._index.is_trained:
            # Train with random data for initial state
            random_data = np.random.rand(max(self.nlist, 10), self.dimension).astype(np.float32)
            self._index.train(random_data)
        logger.info("Created new FAISS IVF index (dim=%d, nlist=%d)", self.dimension, self.nlist)

    def persist(self) -> None:
        """Persist index and metadata to disk."""
        faiss = _require_faiss()

        if self._index is None:
            logger.warning("Cannot persist: no index loaded")
            return

        self.index_path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self.index_path / "faiss.index"))
        with open(self.index_path / "metadata.jsonl", "w", encoding="utf-8") as f:
            for meta in self._metadata:
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")

        logger.debug("Persisted FAISS index: %d vectors", len(self._metadata))

    # ------------------------------------------------------------------
    # Vector operations
    # ------------------------------------------------------------------

    def add(self, embedding: list[float], metadata: dict) -> int:
        """Add a vector with metadata to the index.

        Args:
            embedding: Vector embedding (list of floats).
            metadata: Associated metadata dict (e.g., chunk ID, content, file).

        Returns:
            Internal vector ID.
        """
        faiss = _require_faiss()

        vec = np.array([embedding], dtype=np.float32)

        # Ensure index is trained
        if not self._index.is_trained:
            flat_idx = faiss.IndexFlatL2(self.dimension)
            flat_idx.add(vec)
            self._index = flat_idx
        else:
            self._index.add(vec)

        vector_id = self._id_counter
        self._metadata.append(
            {
                "id": vector_id,
                **metadata,
                "added_at": time.time(),
            }
        )
        self._id_counter += 1
        return vector_id

    def add_batch(self, embeddings: list[list[float]], metadatas: list[dict]) -> list[int]:
        """Add multiple vectors in a single operation (more efficient).

        Args:
            embeddings: List of vectors.
            metadatas: List of metadata dicts (same length as embeddings).

        Returns:
            List of internal vector IDs.
        """
        faiss = _require_faiss()

        if len(embeddings) != len(metadatas):
            raise ValueError(
                f"embeddings ({len(embeddings)}) and metadatas ({len(metadatas)}) must match"
            )

        vectors = np.array(embeddings, dtype=np.float32)

        if not self._index.is_trained:
            flat_idx = faiss.IndexFlatL2(self.dimension)
            flat_idx.add(vectors)
            self._index = flat_idx
        else:
            self._index.add(vectors)

        ids = []
        for _i, meta in enumerate(metadatas):
            vector_id = self._id_counter
            self._metadata.append(
                {
                    "id": vector_id,
                    **meta,
                    "added_at": time.time(),
                }
            )
            ids.append(vector_id)
            self._id_counter += 1

        return ids

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        nprobe: int = 10,
    ) -> list[tuple[float, dict]]:
        """Search for nearest neighbors.

        Args:
            query_embedding: Query vector.
            top_k: Number of results to return.
            nprobe: Number of IVF cells to probe (tradeoff: accuracy vs speed).
                    Higher = more accurate but slower.

        Returns:
            List of (score, metadata) tuples, sorted by score descending.
            Score is cosine-similarity-like (0 to 1, higher = more similar).
        """
        if self._index is None or len(self._metadata) == 0:
            return []

        start = time.monotonic()

        # Set probe count for accuracy/speed tradeoff
        if hasattr(self._index, "nprobe"):
            self._index.nprobe = nprobe

        query_vec = np.array([query_embedding], dtype=np.float32)
        actual_k = min(top_k, len(self._metadata))

        distances, indices = self._index.search(query_vec, actual_k)

        results = []
        for dist, idx in zip(distances[0], indices[0], strict=False):
            if 0 <= idx < len(self._metadata):
                # Convert L2 distance to similarity score (0-1)
                # score = 1 / (1 + distance)
                score = 1.0 / (1.0 + float(dist))
                results.append((score, self._metadata[idx]))

        self._total_searches += 1
        self._total_search_time_ms += (time.monotonic() - start) * 1000

        return sorted(results, key=lambda x: x[0], reverse=True)

    def remove(self, vector_id: int) -> bool:
        """Remove a vector by ID. Note: FAISS does not support removal natively,
        so we mark it as removed in metadata and rebuild when needed.

        Args:
            vector_id: Internal vector ID to remove.

        Returns:
            True if found and marked.
        """
        for meta in self._metadata:
            if meta.get("id") == vector_id:
                meta["_removed"] = True
                return True
        return False

    def remove_by_filter(self, filter_fn) -> int:
        """Remove vectors matching a filter function.

        Args:
            filter_fn: Callable(metadata) -> bool.

        Returns:
            Number of vectors marked as removed.
        """
        count = 0
        for meta in self._metadata:
            if filter_fn(meta):
                meta["_removed"] = True
                count += 1
        return count

    def rebuild_index(self) -> None:
        """Rebuild the FAISS index, removing marked vectors.
        Should be called periodically to clean up removed vectors.
        """
        _require_faiss()

        active = [m for m in self._metadata if not m.get("_removed", False)]
        if len(active) == 0:
            return

        # Extract vectors from stored data — need original embeddings
        # This requires re-embedding. For now, log the rebuild.
        logger.info(
            "Rebuild requested: %d active of %d total vectors", len(active), len(self._metadata)
        )

        # In a production system, store embeddings alongside metadata
        # and recreate the index from scratch
        self._metadata = active

    # ------------------------------------------------------------------
    # Stats and metrics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return index statistics for monitoring."""
        active = sum(1 for m in self._metadata if not m.get("_removed", False))
        return {
            "total_vectors": len(self._metadata),
            "active_vectors": active,
            "removed_vectors": len(self._metadata) - active,
            "dimension": self.dimension,
            "nlist": self.nlist,
            "index_trained": self._index.is_trained if hasattr(self._index, "is_trained") else True,
            "total_searches": self._total_searches,
            "avg_search_time_ms": (self._total_search_time_ms / max(1, self._total_searches)),
        }

    def clear(self) -> None:
        """Clear all vectors and reset index."""
        faiss = _require_faiss()

        quantizer = faiss.IndexFlatL2(self.dimension)
        self._index = faiss.IndexIVFFlat(quantizer, self.dimension, self.nlist)
        self._metadata.clear()
        self._id_counter = 0


# Global singleton
_faiss_store: FAISSEmbeddingStore | None = None


def get_vector_store() -> FAISSEmbeddingStore:
    global _faiss_store
    if _faiss_store is None:
        _faiss_store = FAISSEmbeddingStore()
    return _faiss_store
