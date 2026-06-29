from __future__ import annotations

# Re-export the Redis-based caching layer from redis_cache module
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

from .semantic_cache import SemanticCache
from .tool_result_cache import ToolResultCache

__all__ = [
    "SemanticCache",
    "ToolResultCache",
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
