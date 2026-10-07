"""Mock Redis backend for testing."""
from __future__ import annotations

from typing import Any


class MockRedisClient:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self._data = {}
        self._prefix = "nexus"
        self.is_connected = True
    
    def get(self, key: str) -> bytes | None:
        """Mock get operation."""
        full_key = f"{self._prefix}:{key}"
        return self._data.get(full_key)
    
    def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        """Mock set operation."""
        full_key = f"{self._prefix}:{key}"
        self._data[full_key] = value
        return True
    
    def delete(self, key: str) -> int:
        """Mock delete operation."""
        full_key = f"{self._prefix}:{key}"
        if full_key in self._data:
            del self._data[full_key]
            return 1
        return 0
    
    def exists(self, key: str) -> int:
        """Mock exists operation."""
        full_key = f"{self._prefix}:{key}"
        return 1 if full_key in self._data else 0
    
    def scan_iter(self, match: str = "*", count: int = 10) -> list[Any]:
        """Mock scan_iter operation."""
        pattern = match.replace("*", ".*")
        import re
        regex = re.compile(pattern)
        return [k for k in self._data if regex.match(k)]
    
    def memory_usage(self, key: str) -> int | None:
        """Mock memory_usage operation."""
        full_key = f"{self._prefix}:{key}"
        if full_key in self._data:
            return len(str(self._data[full_key]))
        return None
    
    def ping(self) -> bool:
        """Mock ping operation."""
        return True
    
    def close(self) -> None:
        """Mock close operation."""
        self.is_connected = False


class MockRedisBackend:
    """Mock Redis backend for testing."""
    
    def __init__(self):
        self._client = MockRedisClient()
        self._prefix = "nexus"
        self.is_connected = True
    
    def get(self, key: str) -> Any | None:
        """Get value from Redis."""
        return self._client.get(key)
    
    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in Redis."""
        return self._client.set(key, value, ttl)
    
    def delete(self, key: str) -> int:
        """Delete key from Redis."""
        return self._client.delete(key)
    
    def exists(self, key: str) -> bool:
        """Check if key exists in Redis."""
        return self._client.exists(key) > 0
    
    def clear(self) -> None:
        """Clear all data."""
        self._client._data.clear()
