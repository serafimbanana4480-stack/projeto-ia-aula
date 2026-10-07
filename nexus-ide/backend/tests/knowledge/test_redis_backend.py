"""Tests for RedisBackend persistence."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.knowledge.memory import Memory, MemoryType
from backend.knowledge.redis_backend import RedisBackend


class TestRedisBackend:
    def test_store_and_retrieve(self) -> None:
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True

        with patch("backend.knowledge.redis_backend.redis.from_url", return_value=mock_redis):
            backend = RedisBackend()
            backend._enabled = True
            backend._client = mock_redis

            mem = Memory(
                memory_id="mem-1",
                memory_type=MemoryType.SESSION,
                session_id="sess-1",
                content="test content",
                embedding=[0.1, 0.2, 0.3],
            )

            backend.store(mem)
            assert mock_redis.hset.called
            assert mock_redis.expire.called

    def test_retrieve_not_found(self) -> None:
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {}
        mock_redis.ping.return_value = True

        with patch("backend.knowledge.redis_backend.redis.from_url", return_value=mock_redis):
            backend = RedisBackend()
            backend._enabled = True
            backend._client = mock_redis

            result = backend.retrieve("nonexistent")
            assert result is None

    def test_get_session_memories(self) -> None:
        mock_redis = MagicMock()
        mock_redis.smembers.return_value = {"mem-1", "mem-2"}
        mock_redis.hgetall.side_effect = [
            {
                "memory_id": "mem-1",
                "memory_type": "session",
                "session_id": "sess-1",
                "content": "content 1",
                "embedding": "[0.1]",
                "created_at": "0",
                "last_accessed_at": "0",
                "access_count": "0",
                "importance": "0.5",
                "tags": "[]",
                "related_memory_ids": "[]",
            },
            {
                "memory_id": "mem-2",
                "memory_type": "session",
                "session_id": "sess-1",
                "content": "content 2",
                "embedding": "[0.2]",
                "created_at": "0",
                "last_accessed_at": "0",
                "access_count": "0",
                "importance": "0.5",
                "tags": "[]",
                "related_memory_ids": "[]",
            },
        ]
        mock_redis.ping.return_value = True

        with patch("backend.knowledge.redis_backend.redis.from_url", return_value=mock_redis):
            backend = RedisBackend()
            backend._enabled = True
            backend._client = mock_redis

            memories = backend.get_session_memories("sess-1")
            assert len(memories) == 2
            assert memories[0].content == "content 1"
            assert memories[1].content == "content 2"

    def test_default_ttl_values(self) -> None:
        assert RedisBackend.DEFAULT_TTL[MemoryType.SESSION] == 3600
        assert RedisBackend.DEFAULT_TTL[MemoryType.PROJECT] == 86400
        assert RedisBackend.DEFAULT_TTL[MemoryType.GLOBAL] == 604800
        assert RedisBackend.DEFAULT_TTL[MemoryType.CODE_SNIPPET] == 2592000
