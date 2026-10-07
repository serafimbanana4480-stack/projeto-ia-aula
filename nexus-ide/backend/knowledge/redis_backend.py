"""Redis Backend — persistent short-term memory with TTL.

Provides Redis-backed storage for MemoryStore with automatic expiration,
enabling session recovery and cross-session context.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from backend.knowledge.memory import Memory, MemoryType

logger = logging.getLogger(__name__)


class RedisBackend:
    """Redis-backed persistence for MemoryStore."""

    # Default TTL in seconds per memory type
    DEFAULT_TTL: dict[MemoryType, int] = {
        MemoryType.SESSION: 3600,       # 1 hour
        MemoryType.PROJECT: 86400,      # 24 hours
        MemoryType.GLOBAL: 604800,      # 7 days
        MemoryType.CODE_SNIPPET: 2592000,  # 30 days
        MemoryType.FILE_CONTENT: 86400,
        MemoryType.CONVERSATION: 3600,
        MemoryType.TOOL_RESULT: 3600,
    }

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "nexus:memory",
    ) -> None:
        if not REDIS_AVAILABLE:
            raise ImportError(
                "redis-py is required. Install: pip install redis[hiredis]"
            )
        self._client = redis.from_url(redis_url, decode_responses=True)
        self._prefix = key_prefix
        self._enabled = True

        # Test connection
        try:
            self._client.ping()
            logger.info("Redis backend connected: %s", redis_url)
        except Exception as exc:
            logger.warning("Redis connection failed: %s", exc)
            self._enabled = False

    def _key(self, memory_id: str) -> str:
        return f"{self._prefix}:{memory_id}"

    def _session_key(self, session_id: str) -> str:
        return f"{self._prefix}:session:{session_id}"

    @property
    def is_connected(self) -> bool:
        return self._enabled

    def store(self, memory: Memory, ttl: int | None = None) -> bool:
        """Store a memory in Redis with TTL.

        Args:
            memory: Memory object to store.
            ttl: Time-to-live in seconds. Uses DEFAULT_TTL if None.

        Returns:
            True if stored successfully.
        """
        if not self._enabled:
            return False

        try:
            ttl = ttl or self.DEFAULT_TTL.get(memory.memory_type, 3600)
            data = asdict(memory)
            data["memory_type"] = memory.memory_type.value
            data["embedding"] = json.dumps(data["embedding"])

            key = self._key(memory.memory_id)
            self._client.hset(key, mapping={
                k: json.dumps(v) if isinstance(v, (list, dict)) else str(v)
                for k, v in data.items()
            })
            self._client.expire(key, ttl)

            # Index by session
            if memory.session_id:
                session_key = self._session_key(memory.session_id)
                self._client.sadd(session_key, memory.memory_id)
                self._client.expire(session_key, ttl)

            logger.debug("Stored memory %s in Redis (TTL=%ds)", memory.memory_id, ttl)
            return True

        except Exception as exc:
            logger.warning("Failed to store memory in Redis: %s", exc)
            return False

    def retrieve(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID from Redis.

        Args:
            memory_id: Memory identifier.

        Returns:
            Memory object or None if not found.
        """
        if not self._enabled:
            return None

        try:
            key = self._key(memory_id)
            data = self._client.hgetall(key)
            if not data:
                return None

            return self._deserialize(data)

        except Exception as exc:
            logger.warning("Failed to retrieve memory from Redis: %s", exc)
            return None

    def get_session_memories(self, session_id: str) -> list[Memory]:
        """Get all memories for a session.

        Args:
            session_id: Session identifier.

        Returns:
            List of Memory objects.
        """
        if not self._enabled:
            return []

        try:
            session_key = self._session_key(session_id)
            memory_ids = self._client.smembers(session_key)
            memories: list[Memory] = []
            for mid in memory_ids:
                mem = self.retrieve(mid)
                if mem:
                    memories.append(mem)
            return memories

        except Exception as exc:
            logger.warning("Failed to get session memories: %s", exc)
            return []

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        min_similarity: float = 0.3,
    ) -> list[tuple[Memory, float]]:
        """Search memories by embedding similarity.

        Note: Redis doesn't natively support vector search in OSS.
        This implementation does a linear scan over session keys.
        For production, use Redis Search module or Qdrant.
        """
        if not self._enabled:
            return []

        try:
            # Get all memory keys
            pattern = f"{self._prefix}:*"
            keys = self._client.scan_iter(match=pattern, count=1000)

            results: list[tuple[Memory, float]] = []
            for key in keys:
                if ":session:" in key:
                    continue
                data = self._client.hgetall(key)
                if not data:
                    continue
                mem = self._deserialize(data)
                if mem and mem.embedding:
                    sim = self._cosine_similarity(query_embedding, mem.embedding)
                    if sim >= min_similarity:
                        results.append((mem, sim))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]

        except Exception as exc:
            logger.warning("Redis search failed: %s", exc)
            return []

    def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        if not self._enabled:
            return False
        try:
            self._client.delete(self._key(memory_id))
            return True
        except Exception as exc:
            logger.warning("Failed to delete memory: %s", exc)
            return False

    def _deserialize(self, data: dict[str, str]) -> Memory | None:
        """Deserialize Redis hash data to Memory."""
        try:
            memory_type = MemoryType(data.get("memory_type", "session"))
            embedding = json.loads(data.get("embedding", "[]"))
            tags = json.loads(data.get("tags", "[]"))
            related = json.loads(data.get("related_memory_ids", "[]"))

            return Memory(
                memory_id=data.get("memory_id", ""),
                memory_type=memory_type,
                session_id=data.get("session_id", ""),
                project_id=data.get("project_id", ""),
                content=data.get("content", ""),
                summary=data.get("summary", ""),
                embedding=embedding,
                tags=tags,
                source=data.get("source", ""),
                file_path=data.get("file_path", ""),
                language=data.get("language", ""),
                created_at=float(data.get("created_at", 0)),
                last_accessed_at=float(data.get("last_accessed_at", 0)),
                access_count=int(data.get("access_count", 0)),
                importance=float(data.get("importance", 0.5)),
                kind=data.get("kind", "semantic"),
                related_memory_ids=related,
            )
        except Exception as exc:
            logger.warning("Failed to deserialize memory: %s", exc)
            return None

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
