"""
cache — A production-ready caching system with pluggable eviction policies,
TTL support, thread safety, and statistics.

Public API:
    Cache              – generic cache with configurable eviction policy
    EvictionPolicy     – enum of supported policies
    CacheStats         – hit/miss/eviction statistics
    ThreadSafeCache    – thread-safe wrapper around Cache
    CacheFactory       – convenience factory for common configurations

Example:
    >>> from cache import Cache, EvictionPolicy
    >>> c = Cache(max_size=3, policy=EvictionPolicy.LRU)
    >>> c.put("a", 1)
    >>> c.get("a")
    1
"""

from cache.core import Cache, CacheEntry, EvictionPolicy, CacheStats
from cache.threaded import ThreadSafeCache
from cache.factory import CacheFactory

__all__ = [
    "Cache",
    "CacheEntry",
    "EvictionPolicy",
    "CacheStats",
    "ThreadSafeCache",
    "CacheFactory",
]

__version__ = "1.0.0"
