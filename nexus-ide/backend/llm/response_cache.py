"""LLM response cache — exact-match TTL+LRU cache for chat completions.

Identical prompts repeated inside a short window (agent retries, UI refreshes,
multi-agent fan-out over the same context) paid full price on every call.
This module caches the *exact* request: same provider + model + normalized
messages + serializable params → same cached answer. Streaming is never
cached (partial output cannot be replayed safely).

Ordering vs. the cost governor (deliberate):
    A cache hit performs no dispatch and therefore costs $0 — the lookup runs
    BEFORE ``CostGovernor.check()`` in ``MultiLLMManager.chat_complete``.
    Refusing a free cached answer because a budget is exhausted would force a
    paid re-dispatch or a user-facing error for content the system already
    owns. Hits are recorded as zero cost: they never reach
    ``CostGovernor.record()`` (which ignores $0 entries); hit accounting lives
    in :meth:`ResponseCache.get_stats`.

Configuration:
    * ``NEXUS_LLM_CACHE_TTL``  — seconds; default 0 = disabled.
    * ``NEXUS_LLM_CACHE_SIZE`` — max entries (LRU eviction); default 256.

Usage:
    from backend.llm.response_cache import get_response_cache

    cache = get_response_cache()
    key = cache.cache_key(provider, model, messages, options)
    hit = cache.get(key)
    ...
    cache.store(key, result)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

TTL_ENV = "NEXUS_LLM_CACHE_TTL"
SIZE_ENV = "NEXUS_LLM_CACHE_SIZE"
_DEFAULT_TTL_SECONDS = 0.0
_DEFAULT_MAX_ENTRIES = 256


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid %s=%r — ignoring", name, raw)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r — ignoring", name, raw)
        return default
    if value < 1:
        logger.warning("Invalid %s=%r — ignoring", name, raw)
        return default
    return value


def _jsonable(value: Any) -> bool:
    """True when *value* survives a JSON round-trip (callbacks do not)."""
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def _normalize_message(message: Any) -> dict[str, str]:
    """Canonical ``{"role", "content"}`` view of dicts or ChatMessage-like objects."""
    if isinstance(message, dict):
        return {
            "role": str(message.get("role", "")),
            "content": str(message.get("content", "")),
        }
    return {
        "role": str(getattr(message, "role", "")),
        "content": str(getattr(message, "content", "")),
    }


def _normalize_params(options: dict[str, Any] | None, kwargs: dict[str, Any]) -> str:
    """Deterministic JSON of call parameters that can change the answer.

    Only JSON-serializable values participate; callbacks and private transport
    hints (``_nexus_dispatch_timeout``, ``on_final_chunk``, …) are excluded so
    they cannot alter the cache identity.
    """
    payload: dict[str, Any] = {}
    if isinstance(options, dict):
        payload.update({k: v for k, v in options.items() if _jsonable(v)})
    payload.update(
        {k: v for k, v in kwargs.items() if not k.startswith("_") and _jsonable(v)}
    )
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


class ResponseCache:
    """Thread-safe exact-match LRU+TTL cache keyed by a request hash."""

    def __init__(
        self,
        *,
        ttl_seconds: float | None = None,
        max_entries: int | None = None,
    ) -> None:
        # Overrides win over env so tests and embedders can pin behaviour;
        # without an override the env is re-read on every get/store, allowing
        # operators to toggle caching without a process restart.
        self._ttl_override = ttl_seconds
        self._size_override = max_entries
        # key -> (expires_at, response), LRU order = insertion/access order
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @property
    def ttl_seconds(self) -> float:
        if self._ttl_override is not None:
            return self._ttl_override
        return _env_float(TTL_ENV, _DEFAULT_TTL_SECONDS)

    @property
    def max_entries(self) -> int:
        if self._size_override is not None:
            return self._size_override
        return _env_int(SIZE_ENV, _DEFAULT_MAX_ENTRIES)

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    @staticmethod
    def cache_key(
        provider: str,
        model: str,
        messages: list[Any],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Stable hash of provider+model+normalized messages+params."""
        normalized = [_normalize_message(message) for message in (messages or [])]
        content = "\x1f".join(
            (
                str(provider or ""),
                str(model or ""),
                json.dumps(normalized, sort_keys=True, ensure_ascii=False),
                _normalize_params(options, kwargs),
            )
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        """Return the cached response or None on miss/expiry/disabled."""
        ttl = self.ttl_seconds
        now = time.time()
        with self._lock:
            if ttl <= 0:
                self._misses += 1
                return None
            entry = self._entries.get(key)
            if entry is not None and now < entry[0]:
                self._entries.move_to_end(key)
                self._hits += 1
                return entry[1]
            if entry is not None:
                del self._entries[key]
            self._misses += 1
        return None

    def store(self, key: str, response: str) -> None:
        """Store a successful response; no-op while disabled."""
        ttl = self.ttl_seconds
        if ttl <= 0:
            return
        with self._lock:
            self._entries[key] = (time.time() + ttl, response)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        """Drop every cached response."""
        with self._lock:
            self._entries.clear()

    def get_stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "llm_cache_hits": self._hits,
            "llm_cache_misses": self._misses,
            "llm_cache_size": len(self._entries),
            "llm_cache_hit_rate": self._hits / max(1, total),
            "enabled": self.enabled,
            "ttl_seconds": self.ttl_seconds,
            "max_entries": self.max_entries,
        }


# Global singleton per process (same convention as backend/cache/tool_result_cache.py)
_response_cache: ResponseCache | None = None
_response_cache_lock = threading.Lock()


def get_response_cache() -> ResponseCache:
    global _response_cache
    if _response_cache is None:
        with _response_cache_lock:
            if _response_cache is None:
                _response_cache = ResponseCache()
    return _response_cache


def reset_response_cache() -> None:
    """Test helper: drop the singleton."""
    global _response_cache
    with _response_cache_lock:
        _response_cache = None
