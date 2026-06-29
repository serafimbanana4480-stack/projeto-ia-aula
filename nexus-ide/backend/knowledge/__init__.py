"""Knowledge package — memory, code intelligence, and semantic search.

See ARCHITECTURE.md §5.
"""

from backend.knowledge.memory import (
    EmbeddingService,
    Memory,
    MemoryStore,
    MemoryType,
    get_memory_store,
)

__all__ = [
    "MemoryStore",
    "Memory",
    "MemoryType",
    "EmbeddingService",
    "get_memory_store",
]
