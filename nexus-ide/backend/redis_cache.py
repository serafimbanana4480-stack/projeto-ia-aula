"""Redis caching layer for NEXUS IDE.

Provides high-performance caching for frequently accessed data with TTL support.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from backend.cache_backends import NullCacheBackend

logger = logging.getLogger(__name__)

# Default TTL values (in seconds)
DEFAULT_TTL = 300  # 5 minutes
SHORT_TTL = 60  # 1 minute
LONG_TTL = 3600  # 1 hour


class CacheError(RuntimeError):
    """Raised when cache operations fail."""


try:
    import redis as redis_sync
    import redis.asyncio as redis

    _redis_available = True
except ImportError:
    _redis_available = False
    logger.warning("redis package not installed — caching disabled")


if _redis_available:

    class SyncCacheClient:
        """Synchronous Redis client with connection pooling and error handling."""

        def __init__(
            self,
            host: str = "localhost",
            port: int = 6379,
            db: int = 0,
            password: str | None = None,
            *,
            max_connections: int = 50,
            decode_responses: bool = True,
        ) -> None:
            self._pool = redis_sync.ConnectionPool(
                host=host,
                port=port,
                db=db,
                password=password,
                max_connections=max_connections,
                decode_responses=decode_responses,
            )
            self._client = redis_sync.Redis(connection_pool=self._pool)
            self._fallback = False

        def get(self, key: str) -> str | None:
            """Get a value from cache."""
            if self._fallback:
                return None
            try:
                return self._client.get(key)
            except redis_sync.RedisError as e:
                logger.warning("Cache get failed for key %s: %s", key, e)
                return None

        def set(
            self,
            key: str,
            value: str,
            ttl: int = DEFAULT_TTL,
        ) -> bool:
            """Set a value in cache with TTL."""
            if self._fallback:
                return False
            try:
                self._client.setex(key, ttl, value)
                return True
            except redis_sync.RedisError as e:
                logger.warning("Cache set failed for key %s: %s", key, e)
                return False

        def delete(self, key: str) -> bool:
            """Delete a key from cache."""
            if self._fallback:
                return False
            try:
                self._client.delete(key)
                return True
            except redis_sync.RedisError as e:
                logger.warning("Cache delete failed for key %s: %s", key, e)
                return False

        def delete_pattern(self, pattern: str) -> int:
            """Delete all keys matching a pattern."""
            if self._fallback:
                return 0
            try:
                keys = self._client.keys(pattern)
                if keys:
                    self._client.delete(*keys)
                return len(keys)
            except redis_sync.RedisError as e:
                logger.warning("Cache delete_pattern failed for %s: %s", pattern, e)
                return 0

        def exists(self, key: str) -> bool:
            """Check if a key exists in cache."""
            if self._fallback:
                return False
            try:
                return bool(self._client.exists(key))
            except redis_sync.RedisError as e:
                logger.warning("Cache exists check failed for key %s: %s", key, e)
                return False

        def close(self) -> None:
            """Close the Redis connection pool."""
            if self._client is None:
                return
            self._client.close()

    class CacheClient:
        """Async Redis client with connection pooling and error handling."""

        def __init__(
            self,
            host: str = "localhost",
            port: int = 6379,
            db: int = 0,
            password: str | None = None,
            *,
            max_connections: int = 50,
            decode_responses: bool = True,
        ) -> None:
            self._pool = redis.ConnectionPool(
                host=host,
                port=port,
                db=db,
                password=password,
                max_connections=max_connections,
                decode_responses=decode_responses,
            )
            self._client = redis.Redis(connection_pool=self._pool)
            self._fallback = False

        async def get(self, key: str) -> str | None:
            """Get a value from cache."""
            if self._fallback:
                return None
            try:
                return await self._client.get(key)
            except redis_sync.RedisError as e:
                logger.warning("Cache get failed for key %s: %s", key, e)
                return None

        async def set(
            self,
            key: str,
            value: str,
            ttl: int = DEFAULT_TTL,
        ) -> bool:
            """Set a value in cache with TTL."""
            if self._fallback:
                return False
            try:
                await self._client.setex(key, ttl, value)
                return True
            except redis_sync.RedisError as e:
                logger.warning("Cache set failed for key %s: %s", key, e)
                return False

        async def delete(self, key: str) -> bool:
            """Delete a key from cache."""
            if self._fallback:
                return False
            try:
                await self._client.delete(key)
                return True
            except redis_sync.RedisError as e:
                logger.warning("Cache delete failed for key %s: %s", key, e)
                return False

        async def delete_pattern(self, pattern: str) -> int:
            """Delete all keys matching a pattern."""
            if self._fallback:
                return 0
            try:
                keys = []
                async for key in self._client.scan_iter(match=pattern):
                    keys.append(key)
                if keys:
                    await self._client.delete(*keys)
                return len(keys)
            except redis_sync.RedisError as e:
                logger.warning("Cache delete_pattern failed for %s: %s", pattern, e)
                return 0

        async def exists(self, key: str) -> bool:
            """Check if a key exists in cache."""
            if self._fallback:
                return False
            try:
                return bool(await self._client.exists(key))
            except redis_sync.RedisError as e:
                logger.warning("Cache exists check failed for key %s: %s", key, e)
                return False

        async def close(self) -> None:
            """Close the Redis connection pool."""
            if self._client is None:
                return
            await self._client.close()

else:

    class SyncCacheClient:
        """Stub — redis package not installed."""

        def __init__(
            self,
            host: str = "localhost",
            port: int = 6379,
            db: int = 0,
            password: str | None = None,
            *,
            max_connections: int = 50,
            decode_responses: bool = True,
        ) -> None:
            pass

        def get(self, key: str) -> None:
            return None

        def set(self, key: str, value: str, ttl: int = DEFAULT_TTL) -> bool:
            return False

        def delete(self, key: str) -> bool:
            return False

        def delete_pattern(self, pattern: str) -> int:
            return 0

        def exists(self, key: str) -> bool:
            return False

        def close(self) -> None:
            return None

    class CacheClient:
        """Stub — redis package not installed."""

        def __init__(
            self,
            host: str = "localhost",
            port: int = 6379,
            db: int = 0,
            password: str | None = None,
            *,
            max_connections: int = 50,
            decode_responses: bool = True,
        ) -> None:
            pass

        async def get(self, key: str) -> None:
            return None

        async def set(self, key: str, value: str, ttl: int = DEFAULT_TTL) -> bool:
            return False

        async def delete(self, key: str) -> bool:
            return False

        async def delete_pattern(self, pattern: str) -> int:
            return 0

        async def exists(self, key: str) -> bool:
            return False

        async def close(self) -> None:
            return None


# Global cache client instances
_sync_cache_client: SyncCacheClient | None = None
_cache_client: CacheClient | None = None


def get_sync_cache() -> SyncCacheClient | NullCacheBackend:
    """Get or create the global sync cache client instance."""
    global _sync_cache_client
    if _sync_cache_client is None:
        try:
            import os

            redis_url = os.environ.get("REDIS_URL", "")
            if redis_url:
                from urllib.parse import urlparse

                parsed = urlparse(redis_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 6379
                _sync_cache_client = SyncCacheClient(host=host, port=port)
            else:
                _sync_cache_client = SyncCacheClient()
        except Exception as exc:
            logger.warning("Falling back to NullCacheBackend: %s", exc)
            return NullCacheBackend()
    return _sync_cache_client


def get_cache() -> CacheClient | NullCacheBackend:
    """Get or create the global cache client instance."""
    global _cache_client
    if _cache_client is None:
        try:
            _cache_client = CacheClient()
        except Exception as exc:
            logger.warning("Falling back to NullCacheBackend: %s", exc)
            return NullCacheBackend()
    return _cache_client


def sync_cache_result(
    key_prefix: str,
    ttl: int = DEFAULT_TTL,
    serialize: bool = True,
) -> Callable:
    """Decorator to cache synchronous function results.

    Args:
        key_prefix: Prefix for cache keys
        ttl: Time to live in seconds
        serialize: Whether to serialize/deserialize as JSON

    Example:
        @sync_cache_result("project:", ttl=3600)
        def get_project(project_id: str) -> dict:
            # Expensive database query
            return db.fetch_project(project_id)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = get_sync_cache()

            # Generate cache key from function arguments
            key_parts = [key_prefix]
            if args:
                key_parts.extend(str(arg) for arg in args)
            if kwargs:
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            # Try to get from cache
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit for key: %s", cache_key)
                if serialize:
                    return json.loads(cached)
                return cached

            # Execute function and cache result
            logger.debug("Cache miss for key: %s", cache_key)
            result = func(*args, **kwargs)

            value = json.dumps(result) if serialize else str(result)

            cache.set(cache_key, value, ttl=ttl)

            return result

        return wrapper

    return decorator


def cache_result(
    key_prefix: str,
    ttl: int = DEFAULT_TTL,
    serialize: bool = True,
) -> Callable:
    """Decorator to cache function results.

    Args:
        key_prefix: Prefix for cache keys
        ttl: Time to live in seconds
        serialize: Whether to serialize/deserialize as JSON

    Example:
        @cache_result("user:", ttl=3600)
        async def get_user(user_id: str) -> dict:
            # Expensive database query
            return await db.fetch_user(user_id)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = get_cache()

            # Generate cache key from function arguments
            key_parts = [key_prefix]
            if args:
                key_parts.extend(str(arg) for arg in args)
            if kwargs:
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            # Try to get from cache
            cached = await cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit for key: %s", cache_key)
                if serialize:
                    return json.loads(cached)
                return cached

            # Execute function and cache result
            logger.debug("Cache miss for key: %s", cache_key)
            result = await func(*args, **kwargs)

            value = json.dumps(result) if serialize else str(result)

            await cache.set(cache_key, value, ttl=ttl)

            return result

        return wrapper

    return decorator


def sync_cache_invalidate_pattern(pattern: str) -> Callable:
    """Decorator to invalidate cache entries matching a pattern after sync function execution.

    Args:
        pattern: Redis key pattern to invalidate

    Example:
        @sync_cache_invalidate_pattern("project:*")
        def update_project(project_id: str, data: dict) -> dict:
            # Update project in database
            return db.update_project(project_id, data)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            cache = get_sync_cache()
            cache.delete_pattern(pattern)
            logger.debug("Invalidated cache pattern: %s", pattern)
            return result

        return wrapper

    return decorator


def cache_invalidate_pattern(pattern: str) -> Callable:
    """Decorator to invalidate cache entries matching a pattern after function execution.

    Args:
        pattern: Redis key pattern to invalidate

    Example:
        @cache_invalidate_pattern("user:*")
        async def update_user(user_id: str, data: dict) -> dict:
            # Update user in database
            return await db.update_user(user_id, data)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await func(*args, **kwargs)
            cache = get_cache()
            await cache.delete_pattern(pattern)
            logger.debug("Invalidated cache pattern: %s", pattern)
            return result

        return wrapper

    return decorator
