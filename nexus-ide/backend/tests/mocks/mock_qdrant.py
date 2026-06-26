"""Mock Qdrant backend for testing."""
from __future__ import annotations

from typing import Any
from dataclasses import dataclass


@dataclass
class MockCollection:
    """Mock Qdrant collection."""
    name: str
    vectors_count: int = 0


@dataclass
class MockCollectionsResult:
    """Mock Qdrant collections result."""
    collections: list[MockCollection]


class MockQdrantClient:
    """Mock Qdrant client for testing."""
    
    def __init__(self):
        self._collections = {
            "test_collection": MockCollection("test_collection", 100)
        }
    
    def get_collections(self) -> MockCollectionsResult:
        """Mock get_collections operation."""
        return MockCollectionsResult(list(self._collections.values()))
    
    def count(self, collection_name: str = "test_collection") -> int:
        """Mock count operation."""
        if collection_name in self._collections:
            return self._collections[collection_name].vectors_count
        return 0
    
    def search(self, collection_name: str, query_vector: list[float], limit: int = 10) -> list[Any]:
        """Mock search operation."""
        return []
    
    def upsert(self, collection_name: str, points: list[Any]) -> Any:
        """Mock upsert operation."""
        if collection_name not in self._collections:
            self._collections[collection_name] = MockCollection(collection_name, 0)
        self._collections[collection_name].vectors_count += len(points)
        return {"status": "completed"}


class MockQdrantBackend:
    """Mock Qdrant backend for testing."""
    
    def __init__(self):
        self._client = MockQdrantClient()
    
    def count(self) -> int:
        """Count vectors in default collection."""
        return self._client.count()
    
    def search(self, query_vector: list[float], limit: int = 10) -> list[Any]:
        """Search for similar vectors."""
        return self._client.search("test_collection", query_vector, limit)
    
    def upsert(self, points: list[Any]) -> Any:
        """Upsert vectors."""
        return self._client.upsert("test_collection", points)
