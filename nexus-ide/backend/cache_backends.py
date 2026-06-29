"""Cache backends for the routing layer.

This module defines a small :class:`CacheBackend` abstraction used by the
:class:`backend.orchestrator.router_engine.Router` to memoize routing decisions
without coupling the engine to a particular cache implementation.

Implementations provided:

* :class:`TTLCacheBackend` — production-grade in-process cache. Uses
  :class:`cachetools.TTLCache` when available and falls back to a
  ``OrderedDict``-based implementation when ``cachetools`` is not installed.
  All access is serialized through :class:`asyncio.Lock` so the cache is safe
  to share across coroutines.
* :class:`InMemoryCacheBackend` — process-local fallback. Same semantics as the
  TTL backend but using a plain ``dict`` and manual expiry timestamps.
* :class:`NullCacheBackend` — no-op cache. ``get`` always returns ``None`` and
  ``set`` is a no-op. Useful in tests or when caching is disabled.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard
    from cachetools import TTLCache as _CachetoolsTTLCache  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - fallback path
    _CachetoolsTTLCache = None


class CacheBackend(ABC):
    """Abstract async cache backend used by the router engine."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Return the cached value for ``key`` or ``None`` on miss/expired."""

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store ``value`` for ``key`` with a TTL in seconds."""

    @abstractmethod
    async def clear(self) -> None:
        """Remove all entries from the cache."""


class NullCacheBackend(CacheBackend):
    """No-op cache backend. Used in tests and when caching is disabled."""

    async def get(self, key: str) -> Any | None:
        return None

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        return None

    async def clear(self) -> None:
        return None


class InMemoryCacheBackend(CacheBackend):
    """Process-local cache with manual expiry timestamps.

    A lightweight fallback that does not depend on ``cachetools``. Entries are
    stored in a plain ``dict`` and lazy-expired on read.
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at <= time.time():
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        async with self._lock:
            if len(self._store) >= self._max_size and key not in self._store:
                # Evict the oldest insertion (FIFO)
                oldest = next(iter(self._store))
                self._store.pop(oldest, None)
            self._store[key] = (value, time.time() + float(ttl_seconds))

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()


class TTLCacheBackend(CacheBackend):
    """TTL cache backend backed by :mod:`cachetools` when available.

    Falls back to :class:`InMemoryCacheBackend` semantics (with an
    :class:`collections.OrderedDict` to provide FIFO eviction) when
    ``cachetools`` is not installed. Access is serialized via
    :class:`asyncio.Lock` to keep the backend safe under concurrent
    coroutines.
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
        if _CachetoolsTTLCache is not None:
            self._cache: Any = _CachetoolsTTLCache(maxsize=max_size, ttl=default_ttl)
        else:
            # Manual TTL store backed by OrderedDict to preserve insertion order.
            self._cache = OrderedDict()
            self._expiry: dict[str, float] = {}

    def _evict_expired_sync(self) -> None:
        """Drop expired entries. Caller must hold ``self._lock``."""
        now = time.time()
        if _CachetoolsTTLCache is not None:
            # cachetools handles eviction lazily; nothing to do here.
            return
        expired = [k for k, exp in self._expiry.items() if exp <= now]
        for k in expired:
            self._expiry.pop(k, None)
            self._cache.pop(k, None)

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            if _CachetoolsTTLCache is not None:
                try:
                    return self._cache.get(key)
                except KeyError:
                    return None
            self._evict_expired_sync()
            entry = self._cache.get(key)
            if entry is None:
                return None
            return entry

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        async with self._lock:
            if _CachetoolsTTLCache is not None:
                self._cache[key] = value
                return
            if key in self._cache:
                # Refresh insertion order for LRU-ish semantics.
                self._cache.move_to_end(key)
            self._cache[key] = value
            self._expiry[key] = time.time() + float(ttl_seconds)
            if len(self._cache) > self._max_size:
                oldest = next(iter(self._cache))
                self._cache.pop(oldest, None)
                self._expiry.pop(oldest, None)

    async def clear(self) -> None:
        async with self._lock:
            if _CachetoolsTTLCache is not None:
                self._cache.clear()
                return
            self._cache.clear()
            self._expiry.clear()


__all__ = [
    "CacheBackend",
    "TTLCacheBackend",
    "InMemoryCacheBackend",
    "NullCacheBackend",
]
