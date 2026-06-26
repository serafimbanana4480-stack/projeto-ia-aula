"""Redis caching layer for NEXUS IDE.

This module is shadowed by the ``backend/cache/`` package directory.
All functionality has been moved to ``backend/redis_cache.py``.
Import from ``backend.redis_cache`` or from ``backend.cache`` (the package)
which re-exports the same symbols.
"""

from backend.redis_cache import (
    DEFAULT_TTL,
    LONG_TTL,
    SHORT_TTL,
    CacheClient,
    CacheError,
    SyncCacheClient,
    cache_invalidate_pattern,
    cache_result,
    get_cache,
    get_sync_cache,
    sync_cache_invalidate_pattern,
    sync_cache_result,
)

__all__ = [
    "CacheClient",
    "SyncCacheClient",
    "cache_result",
    "sync_cache_result",
    "cache_invalidate_pattern",
    "sync_cache_invalidate_pattern",
    "get_cache",
    "get_sync_cache",
    "CacheError",
    "DEFAULT_TTL",
    "SHORT_TTL",
    "LONG_TTL",
]
