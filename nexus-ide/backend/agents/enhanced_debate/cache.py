"""Simple caching utility for expensive operations.

Provides in-memory caching with TTL (time-to-live) support.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class CacheEntry:
    """Cache entry with value and expiration."""
    value: Any
    expires_at: float
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at


class Cache:
    """Simple in-memory cache with TTL support.
    
    Features:
    - Time-to-live (TTL) for cache entries
    - Automatic eviction of expired entries
    - Size limit with LRU eviction
    - Cache statistics
    """
    
    def __init__(
        self,
        default_ttl: float = 300.0,  # 5 minutes
        max_size: int = 1000
    ):
        """Initialize cache.
        
        Args:
            default_ttl: Default time-to-live in seconds
            max_size: Maximum number of entries in cache
        """
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._cache: dict[str, CacheEntry] = {}
        self._access_order: list[str] = []  # For LRU eviction
        
        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        
        logger.info(
            f"Cache initialized: default_ttl={default_ttl}s, max_size={max_size}"
        )
    
    def _generate_key(self, *args: Any, **kwargs: Any) -> str:
        """Generate cache key from function arguments."""
        # Convert args and kwargs to a hashable string
        key_data = {
            "args": args,
            "kwargs": kwargs
        }
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        if key not in self._cache:
            self.misses += 1
            return None
        
        entry = self._cache[key]
        
        # Check if expired
        if entry.is_expired():
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            self.misses += 1
            return None
        
        # Update access order for LRU
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
        
        self.hits += 1
        logger.debug(f"Cache hit: {key}")
        return entry.value
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None
    ) -> None:
        """Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        # Evict if at capacity
        if len(self._cache) >= self.max_size and key not in self._cache:
            self._evict_lru()
        
        # Set entry
        expires_at = time.time() + (ttl or self.default_ttl)
        self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
        
        # Update access order
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
        
        logger.debug(f"Cache set: {key}, ttl={ttl or self.default_ttl}s")
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._access_order:
            return
        
        lru_key = self._access_order.pop(0)
        if lru_key in self._cache:
            del self._cache[lru_key]
            self.evictions += 1
            logger.debug(f"Cache evicted LRU: {lru_key}")
    
    def invalidate(self, key: str) -> None:
        """Invalidate specific cache entry.
        
        Args:
            key: Cache key to invalidate
        """
        if key in self._cache:
            del self._cache[key]
        if key in self._access_order:
            self._access_order.remove(key)
        logger.debug(f"Cache invalidated: {key}")
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._access_order.clear()
        logger.info("Cache cleared")
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
        
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
        
        return len(expired_keys)
    
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0.0
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": hit_rate,
        }
    
    def cached(self, ttl: Optional[float] = None):
        """Decorator for caching function results.
        
        Args:
            ttl: Time-to-live in seconds (uses default if None)
            
        Returns:
            Decorator function
        """
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            async def wrapper(*args: Any, **kwargs: Any) -> T:
                # Generate cache key
                key = self._generate_key(func.__name__, *args, **kwargs)
                
                # Try to get from cache
                cached_value = self.get(key)
                if cached_value is not None:
                    return cached_value
                
                # Call function
                result = await func(*args, **kwargs)
                
                # Cache result
                self.set(key, result, ttl)
                
                return result
            
            return wrapper
        
        return decorator


# Global cache instance
_global_cache: Optional[Cache] = None


def get_global_cache() -> Cache:
    """Get or create global cache instance.
    
    Returns:
        Global cache instance
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = Cache()
    return _global_cache
