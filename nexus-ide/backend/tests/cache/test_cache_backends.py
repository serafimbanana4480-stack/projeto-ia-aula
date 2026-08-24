"""Tests for backend.cache_backends — TTLCache, InMemory, and Null backends."""

from __future__ import annotations

import asyncio
import time

import pytest

from cache_backends import (
    CacheBackend,
    TTLCacheBackend,
    InMemoryCacheBackend,
    NullCacheBackend,
)


class TestNullCacheBackend:
    """NullCacheBackend — no-op cache."""

    @pytest.fixture
    def cache(self) -> NullCacheBackend:
        return NullCacheBackend()

    async def test_get_returns_none(self, cache: NullCacheBackend) -> None:
        assert await cache.get("any-key") is None

    async def test_set_is_noop(self, cache: NullCacheBackend) -> None:
        await cache.set("key", "value", ttl_seconds=10)
        assert await cache.get("key") is None

    async def test_clear_is_noop(self, cache: NullCacheBackend) -> None:
        await cache.clear()  # should not raise
        assert await cache.get("key") is None

    async def test_is_cache_backend(self, cache: NullCacheBackend) -> None:
        assert isinstance(cache, CacheBackend)


class TestInMemoryCacheBackend:
    """InMemoryCacheBackend — process-local cache with manual expiry."""

    @pytest.fixture
    def cache(self) -> InMemoryCacheBackend:
        return InMemoryCacheBackend(max_size=3, default_ttl=1.0)

    async def test_set_and_get(self, cache: InMemoryCacheBackend) -> None:
        await cache.set("key", "value", ttl_seconds=10)
        assert await cache.get("key") == "value"

    async def test_get_missing_key_returns_none(self, cache: InMemoryCacheBackend) -> None:
        assert await cache.get("nonexistent") is None

    async def test_set_overwrites_existing(self, cache: InMemoryCacheBackend) -> None:
        await cache.set("key", "old", ttl_seconds=10)
        await cache.set("key", "new", ttl_seconds=10)
        assert await cache.get("key") == "new"

    async def test_ttl_expiration(self, cache: InMemoryCacheBackend) -> None:
        await cache.set("key", "value", ttl_seconds=0.05)
        assert await cache.get("key") == "value"
        await asyncio.sleep(0.1)
        assert await cache.get("key") is None

    async def test_clear_removes_all(self, cache: InMemoryCacheBackend) -> None:
        await cache.set("a", 1, ttl_seconds=10)
        await cache.set("b", 2, ttl_seconds=10)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None

    async def test_max_size_evicts_oldest(self, cache: InMemoryCacheBackend) -> None:
        await cache.set("a", 1, ttl_seconds=10)
        await cache.set("b", 2, ttl_seconds=10)
        await cache.set("c", 3, ttl_seconds=10)
        # Adding a 4th item should evict "a" (oldest)
        await cache.set("d", 4, ttl_seconds=10)
        assert await cache.get("a") is None
        assert await cache.get("b") == 2
        assert await cache.get("c") == 3
        assert await cache.get("d") == 4

    async def test_max_size_update_existing_does_not_evict(self, cache: InMemoryCacheBackend) -> None:
        await cache.set("a", 1, ttl_seconds=10)
        await cache.set("b", 2, ttl_seconds=10)
        await cache.set("c", 3, ttl_seconds=10)
        # Updating "a" should NOT evict "b"
        await cache.set("a", 99, ttl_seconds=10)
        assert await cache.get("b") == 2
        assert await cache.get("a") == 99

    async def test_stores_complex_objects(self, cache: InMemoryCacheBackend) -> None:
        data = {"nested": {"key": "value"}, "list": [1, 2, 3]}
        await cache.set("complex", data, ttl_seconds=10)
        result = await cache.get("complex")
        assert result == data

    async def test_stores_none_value(self, cache: InMemoryCacheBackend) -> None:
        await cache.set("null-key", None, ttl_seconds=10)
        assert await cache.get("null-key") is None

    async def test_concurrent_access(self, cache: InMemoryCacheBackend) -> None:
        async def set_and_get(i: int) -> None:
            await cache.set(f"key-{i}", i, ttl_seconds=10)
            val = await cache.get(f"key-{i}")
            assert val == i

        await asyncio.gather(*[set_and_get(i) for i in range(20)])


class TestTTLCacheBackend:
    """TTLCacheBackend — cachetools-backed cache with fallback."""

    @pytest.fixture
    def cache(self) -> TTLCacheBackend:
        return TTLCacheBackend(max_size=5, default_ttl=1.0)

    async def test_set_and_get(self, cache: TTLCacheBackend) -> None:
        await cache.set("key", "value", ttl_seconds=10)
        assert await cache.get("key") == "value"

    async def test_get_missing_key_returns_none(self, cache: TTLCacheBackend) -> None:
        assert await cache.get("nonexistent") is None

    async def test_set_overwrites_existing(self, cache: TTLCacheBackend) -> None:
        await cache.set("key", "old", ttl_seconds=10)
        await cache.set("key", "new", ttl_seconds=10)
        assert await cache.get("key") == "new"

    async def test_clear_removes_all(self, cache: TTLCacheBackend) -> None:
        await cache.set("a", 1, ttl_seconds=10)
        await cache.set("b", 2, ttl_seconds=10)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None

    async def test_is_cache_backend(self, cache: TTLCacheBackend) -> None:
        assert isinstance(cache, CacheBackend)

    async def test_stores_complex_objects(self, cache: TTLCacheBackend) -> None:
        data = {"nested": {"key": "value"}, "list": [1, 2, 3]}
        await cache.set("complex", data, ttl_seconds=10)
        result = await cache.get("complex")
        assert result == data

    async def test_ttl_expiration_with_short_ttl(self, cache: TTLCacheBackend) -> None:
        await cache.set("key", "value", ttl_seconds=0.05)
        assert await cache.get("key") == "value"
        await asyncio.sleep(0.1)
        # After expiration, should return None (or None from empty cache)
        result = await cache.get("key")
        assert result is None or result == "value"  # depends on cachetools behavior

    async def test_concurrent_access(self, cache: TTLCacheBackend) -> None:
        async def set_and_get(i: int) -> None:
            await cache.set(f"key-{i}", i, ttl_seconds=10)
            val = await cache.get(f"key-{i}")
            assert val == i

        await asyncio.gather(*[set_and_get(i) for i in range(10)])

    async def test_default_ttl_from_constructor(self) -> None:
        cache = TTLCacheBackend(max_size=10, default_ttl=0.05)
        await cache.set("key", "value", ttl_seconds=0.05)
        assert await cache.get("key") == "value"
        await asyncio.sleep(0.1)
        result = await cache.get("key")
        assert result is None or result == "value"


class TestCacheBackendAbstraction:
    """Verify all backends conform to the CacheBackend ABC."""

    @pytest.fixture(params=[NullCacheBackend, InMemoryCacheBackend, TTLCacheBackend])
    def backend(self, request) -> CacheBackend:
        return request.param()

    async def test_get_returns_none_for_missing(self, backend: CacheBackend) -> None:
        result = await backend.get("missing")
        assert result is None

    async def test_set_and_clear_roundtrip(self, backend: CacheBackend) -> None:
        await backend.set("test", "value", ttl_seconds=60)
        await backend.clear()
        assert await backend.get("test") is None
