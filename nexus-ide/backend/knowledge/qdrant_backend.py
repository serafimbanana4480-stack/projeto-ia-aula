"""Qdrant Backend — persistent vector storage for code and document embeddings.

Provides semantic search over indexed code symbols and documentation
using Qdrant vector database.
"""
from __future__ import annotations

import logging
from typing import Any

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

logger = logging.getLogger(__name__)


class QdrantBackend:
    """Qdrant vector database backend for semantic code search."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection_name: str = "nexus_code",
        vector_size: int = 768,
    ) -> None:
        if not QDRANT_AVAILABLE:
            raise ImportError(
                "qdrant-client is required. Install: pip install qdrant-client"
            )
        self._client = QdrantClient(url=url)
        self._collection = collection_name
        self._vector_size = vector_size
        self._connected = True

        # Ensure collection exists
        try:
            self.ensure_collection(vector_size)
        except Exception as exc:
            logger.warning("Qdrant collection init failed: %s", exc)
            self._connected = False

    def ensure_collection(self, vector_size: int) -> None:
        """Create collection if it doesn't exist."""
        collections = self._client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self._collection not in collection_names:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection: %s", self._collection)

    def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> bool:
        """Insert or update a vector point.

        Args:
            point_id: Unique point identifier.
            vector: Embedding vector.
            payload: Metadata payload.

        Returns:
            True if successful.
        """
        if not self._connected:
            return False
        try:
            self._client.upsert(
                collection_name=self._collection,
                points=[PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )],
            )
            return True
        except Exception as exc:
            logger.warning("Qdrant upsert failed: %s", exc)
            return False

    def search(
        self,
        vector: list[float],
        top_k: int = 10,
        filter_dict: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors.

        Args:
            vector: Query embedding.
            top_k: Number of results.
            filter_dict: Optional filter conditions.

        Returns:
            List of results with score and payload.
        """
        if not self._connected:
            return []
        try:
            results = self._client.search(
                collection_name=self._collection,
                query_vector=vector,
                limit=top_k,
                query_filter=filter_dict,
            )
            return [
                {
                    "id": r.id,
                    "score": r.score,
                    "payload": r.payload,
                }
                for r in results
            ]
        except Exception as exc:
            logger.warning("Qdrant search failed: %s", exc)
            return []

    def delete(self, point_id: str) -> bool:
        """Delete a point by ID."""
        if not self._connected:
            return False
        try:
            self._client.delete(
                collection_name=self._collection,
                points_selector=[point_id],
            )
            return True
        except Exception as exc:
            logger.warning("Qdrant delete failed: %s", exc)
            return False

    def count(self) -> int:
        """Get total number of points."""
        if not self._connected:
            return 0
        try:
            result = self._client.count(collection_name=self._collection)
            return result.count
        except Exception:
            return 0
