"""
Tool Result Cache — TTL-based cache for tool execution results.

Prevents redundant execution of idempotent tools (search, list, read) within
the same session. Shell commands, writes, and code execution are never cached.

Usage:
    from backend.cache import tool_cache
    
    # Before executing tool
    cached = tool_cache.get(tool_name, arguments)
    if cached:
        return cached
    
    # After executing tool
    tool_cache.store(tool_name, arguments, result)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# TTL per tool type (seconds). 0 = never cache.
TOOL_TTL_CONFIG: dict[str, int] = {
    "search_codebase": 300,       # 5 min — codebase changes rarely
    "search_in_files": 300,
    "list_files": 60,             # 1 min — filesystem can change
    "list_dir": 60,
    "read_file": 120,             # 2 min — file may be edited
    "read_multiple_files": 120,
    "web_search": 600,            # 10 min — web is stable short-term
    "search_web_v2": 600,
    "fetch_url": 300,
    "fetch_and_summarize": 600,
    "git_log": 300,
    "get_commit_history": 300,
    "get_commit_statistics": 300,
    "git_status": 60,
    "get_file_info": 60,
    "index_stats": 120,
    # Tools that should NEVER be cached
    "shell": 0,
    "execute_shell": 0,
    "execute_code": 0,
    "execute_python": 0,
    "execute_script": 0,
    "write_file": 0,
    "write_file_absolute": 0,
    "append_file": 0,
    "delete_file": 0,
    "delete_directory": 0,
    "move_file": 0,
    "copy_file": 0,
    "create_directory": 0,
    "publish_bus_message": 0,
    "schedule_task": 0,
    "cancel_task": 0,
}


class ToolResultCache:
    """In-memory TTL cache for tool results with automatic eviction."""

    def __init__(self, max_entries: int = 500):
        self._cache: dict[str, tuple[Any, float]] = {}  # key -> (result, expiry)
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0

    def _make_key(self, tool_name: str, arguments: dict) -> str:
        """Generate deterministic cache key from tool name + arguments."""
        args_normalized = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        content = f"{tool_name}:{args_normalized}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def get(self, tool_name: str, arguments: dict) -> Optional[Any]:
        """Return cached result or None if miss/expired."""
        ttl = TOOL_TTL_CONFIG.get(tool_name, 0)
        if ttl == 0:
            self._misses += 1
            return None

        key = self._make_key(tool_name, arguments)
        entry = self._cache.get(key)
        if entry is not None:
            result, expiry = entry
            if time.time() < expiry:
                self._hits += 1
                return result
            # Expired — remove
            del self._cache[key]

        self._misses += 1
        return None

    def store(self, tool_name: str, arguments: dict, result: Any) -> None:
        """Store result in cache with TTL."""
        ttl = TOOL_TTL_CONFIG.get(tool_name, 0)
        if ttl == 0:
            return

        key = self._make_key(tool_name, arguments)
        self._cache[key] = (result, time.time() + ttl)

        # Eviction: remove expired entries if over max
        if len(self._cache) > self._max_entries:
            now = time.time()
            expired = [k for k, (_, exp) in self._cache.items() if now > exp]
            for k in expired:
                del self._cache[k]
            # If still over max, remove oldest entries
            if len(self._cache) > self._max_entries:
                sorted_keys = sorted(
                    self._cache.keys(),
                    key=lambda k: self._cache[k][1],  # sort by expiry time
                )
                excess = len(self._cache) - self._max_entries
                for k in sorted_keys[:excess]:
                    del self._cache[k]

    def clear(self) -> None:
        """Clear all cached results."""
        self._cache.clear()

    def get_metrics(self) -> dict:
        total = self._hits + self._misses
        return {
            "tool_cache_hits": self._hits,
            "tool_cache_misses": self._misses,
            "tool_cache_size": len(self._cache),
            "tool_cache_hit_rate": self._hits / max(1, total),
        }


# Global singleton per process
_tool_cache: ToolResultCache | None = None


def get_tool_cache() -> ToolResultCache:
    global _tool_cache
    if _tool_cache is None:
        _tool_cache = ToolResultCache()
    return _tool_cache
