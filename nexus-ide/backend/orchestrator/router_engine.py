"""Routing engine — composes strategies and a cache backend.

The :class:`Router` is the runtime entry point for the new routing layer. It
holds a list of :class:`RoutingStrategy` instances and a
:class:`CacheBackend`. For each incoming query it:

1. Computes a stable cache key from the query.
2. Returns the cached decision when present.
3. Iterates through strategies in order and returns the first non-``None``
   decision, caching it before returning.
4. Falls back to a hard-coded "no_strategy_matched" decision when no
   strategy can classify the query.

The default constructor wires up :class:`KeywordRoutingStrategy` plus a
no-op :class:`LLMRoutingStrategy` (``llm_client=None``), which short-circuits
and simply returns ``None`` when reached. This keeps the engine usable in
environments without an LLM client while preserving the chain-of-strategies
architecture.
"""

from __future__ import annotations

import hashlib
import logging

from backend.cache_backends import CacheBackend, TTLCacheBackend
from backend.models.api import RoutingDecision
from backend.orchestrator.routing_strategies import (
    KeywordRoutingStrategy,
    LLMRoutingStrategy,
    RoutingStrategy,
)

logger = logging.getLogger(__name__)

# Default TTL for cached routing decisions, in seconds.
DEFAULT_CACHE_TTL: float = 300.0


def _query_hash(query: str) -> str:
    """Generate a hash for caching routing decisions based on query content."""
    return hashlib.md5(query.lower().strip().encode()).hexdigest()


class Router:
    """Strategy-chain router with pluggable caching.

    The router is the single integration point for callers that want a
    fully-routed decision. It is safe to share a single instance across
    coroutines because the underlying :class:`CacheBackend` is itself
    concurrency-safe.

    Parameters
    ----------
    strategies:
        Ordered list of strategies to consult. The first strategy that
        returns a non-``None`` decision wins. When ``None``, the router
        uses ``[KeywordRoutingStrategy(), LLMRoutingStrategy(llm_client=None)]``
        which means the keyword rules run first and the LLM strategy is a
        no-op pass-through.
    cache:
        Cache backend used to memoize decisions. When ``None``, a
        :class:`TTLCacheBackend` with sensible production defaults
        (``max_size=1000``, ``default_ttl=300s``) is created.
    """

    def __init__(
        self,
        *,
        strategies: list[RoutingStrategy] | None = None,
        cache: CacheBackend | None = None,
    ) -> None:
        if strategies is None:
            strategies = [
                KeywordRoutingStrategy(),
                LLMRoutingStrategy(llm_client=None),
            ]
        self._strategies: list[RoutingStrategy] = list(strategies)
        self._cache: CacheBackend = cache or TTLCacheBackend()

    @property
    def cache(self) -> CacheBackend:
        """Expose the cache backend so callers (and shims) can inspect/use it."""
        return self._cache

    @property
    def strategies(self) -> list[RoutingStrategy]:
        """Expose the strategy chain (read-only view)."""
        return list(self._strategies)

    async def route(self, query: str, *, context: dict | None = None) -> RoutingDecision:
        """Return a :class:`RoutingDecision` for ``query``.

        Consults the cache first, then iterates the strategy chain, and
        finally falls back to a low-confidence ``MICRO`` decision when no
        strategy matches.
        """
        if not query or not query.strip():
            return RoutingDecision(
                primary_agent="MICRO",
                secondary_agents=[],
                requires_web_search=False,
                routing_confidence=0.0,
                routing_reason="empty_query",
            )

        cache_key = _query_hash(query)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        for strategy in self._strategies:
            try:
                decision = await strategy.route(query, context=context)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Strategy %s raised: %s", type(strategy).__name__, exc)
                continue
            if decision is not None:
                await self._cache.set(cache_key, decision, DEFAULT_CACHE_TTL)
                return decision

        # No strategy could decide — return the documented hard fallback.
        fallback = RoutingDecision(
            primary_agent="MICRO",
            secondary_agents=[],
            requires_web_search=False,
            routing_confidence=0.0,
            routing_reason="no_strategy_matched",
        )
        return fallback

    async def warm_cache(self, queries: dict[str, RoutingDecision]) -> None:
        """Pre-populate the cache with a set of known query → decision pairs.

        Useful for warming the cache at startup with common queries so the
        first user request is served from cache.
        """
        for query, decision in queries.items():
            await self._cache.set(_query_hash(query), decision, DEFAULT_CACHE_TTL)
        logger.info("Routing cache warmed with %d queries", len(queries))


__all__ = ["Router", "DEFAULT_CACHE_TTL", "_query_hash"]
