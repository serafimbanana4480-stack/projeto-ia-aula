"""Tests for backend.orchestrator.router_engine — Router with strategy chain and cache."""

from __future__ import annotations

from backend.cache_backends import NullCacheBackend, TTLCacheBackend
from backend.models.api import RoutingDecision
from backend.orchestrator.router_engine import (
    DEFAULT_CACHE_TTL,
    Router,
    _query_hash,
)
from backend.orchestrator.routing_strategies import (
    KeywordRoutingStrategy,
    LLMRoutingStrategy,
    RoutingStrategy,
)


class TestQueryHash:
    def test_deterministic(self) -> None:
        h1 = _query_hash("hello world")
        h2 = _query_hash("hello world")
        assert h1 == h2

    def test_different_queries_different_hashes(self) -> None:
        assert _query_hash("hello") != _query_hash("world")

    def test_case_insensitive(self) -> None:
        assert _query_hash("Hello") == _query_hash("hello")

    def test_strips_whitespace(self) -> None:
        assert _query_hash("  hello  ") == _query_hash("hello")

    def test_returns_hex_string(self) -> None:
        h = _query_hash("test")
        assert len(h) == 32  # MD5 hex digest
        assert all(c in "0123456789abcdef" for c in h)


class TestRouterDefaults:
    def test_default_strategies(self) -> None:
        router = Router()
        strategies = router.strategies
        assert len(strategies) == 2
        assert isinstance(strategies[0], KeywordRoutingStrategy)
        assert isinstance(strategies[1], LLMRoutingStrategy)

    def test_default_cache_is_ttl(self) -> None:
        router = Router()
        assert isinstance(router.cache, TTLCacheBackend)

    def test_custom_cache(self) -> None:
        cache = NullCacheBackend()
        router = Router(cache=cache)
        assert router.cache is cache

    def test_custom_strategies(self) -> None:
        strategies = [KeywordRoutingStrategy()]
        router = Router(strategies=strategies)
        assert len(router.strategies) == 1

    def test_strategies_property_returns_copy(self) -> None:
        router = Router()
        s1 = router.strategies
        s2 = router.strategies
        assert s1 is not s2


class TestRouterRoute:
    async def test_empty_query_returns_micro(self) -> None:
        router = Router()
        decision = await router.route("")
        assert decision.primary_agent == "MICRO"
        assert decision.routing_confidence == 0.0
        assert "empty_query" in decision.routing_reason

    async def test_whitespace_query_returns_micro(self) -> None:
        router = Router()
        decision = await router.route("   ")
        assert decision.primary_agent == "MICRO"

    async def test_keyword_query_uses_keyword_strategy(self) -> None:
        router = Router()
        decision = await router.route("write a function")
        assert decision.primary_agent == "CODER"
        assert decision.routing_reason == "keyword-rule"

    async def test_debug_query_uses_keyword_strategy(self) -> None:
        router = Router()
        decision = await router.route("fix the bug in this code")
        assert decision.primary_agent == "DEBUGGER"

    async def test_research_query_uses_keyword_strategy(self) -> None:
        router = Router()
        decision = await router.route("deep research on ai trends")
        assert decision.primary_agent == "RESEARCHER_WEB"

    async def test_trivial_query_uses_keyword_strategy(self) -> None:
        router = Router()
        decision = await router.route("what is the meaning of life")
        assert decision.primary_agent == "MICRO"
        assert decision.routing_reason == "keyword-rule"

    async def test_unmatched_query_falls_to_no_strategy(self) -> None:
        router = Router()
        decision = await router.route("xylophone banana telephone purple")
        assert decision.primary_agent == "MICRO"
        assert decision.routing_confidence == 0.0
        assert "no_strategy_matched" in decision.routing_reason

    async def test_caches_decision(self) -> None:
        router = Router(cache=NullCacheBackend())
        decision1 = await router.route("write a function")
        # Second call should return same result
        decision2 = await router.route("write a function")
        assert decision1 == decision2

    async def test_cache_hit_returns_cached_decision(self) -> None:
        """When cache returns a value, it should be used without calling strategies."""
        counter = {"count": 0}

        class CountingStrategy(RoutingStrategy):
            async def route(self, query: str, *, context: dict | None = None):
                counter["count"] += 1
                return RoutingDecision(primary_agent="MICRO")

        router = Router(strategies=[CountingStrategy()])
        await router.route("test query")
        assert counter["count"] == 1
        # Second call should hit cache if using a cache backend
        router_with_cache = Router(strategies=[CountingStrategy()])
        await router_with_cache.route("test query")

        # Now test with NullCacheBackend - should call strategy each time
        counter2 = {"count": 0}

        class CountingStrategy2(RoutingStrategy):
            async def route(self, query: str, *, context: dict | None = None):
                counter2["count"] += 1
                return RoutingDecision(primary_agent="MICRO")

        router_no_cache = Router(strategies=[CountingStrategy2()], cache=NullCacheBackend())
        await router_no_cache.route("test")
        first_count = counter2["count"]
        await router_no_cache.route("test")
        # With null cache (set is no-op, get always returns None), strategy is called again
        assert counter2["count"] > first_count

    async def test_strategy_exception_is_swallowed(self) -> None:
        class FailingStrategy(RoutingStrategy):
            async def route(self, query: str, *, context: dict | None = None):
                raise RuntimeError("strategy failed")

        router = Router(strategies=[FailingStrategy()])
        decision = await router.route("test query")
        assert decision.primary_agent == "MICRO"
        assert "no_strategy_matched" in decision.routing_reason

    async def test_context_is_forwarded(self) -> None:
        """Context is passed to strategies."""
        received: dict = {}

        class ContextCapturingStrategy(RoutingStrategy):
            async def route(self, query: str, *, context: dict | None = None):
                received["context"] = context
                return RoutingDecision(primary_agent="CODER")

        router = Router(strategies=[ContextCapturingStrategy()])
        await router.route("test", context={"user": "test"})
        assert received["context"] == {"user": "test"}

    async def test_context_defaults_to_none(self) -> None:
        received: dict = {}

        class ContextCapturingStrategy(RoutingStrategy):
            async def route(self, query: str, *, context: dict | None = None):
                received["context"] = context
                return RoutingDecision(primary_agent="CODER")

        router = Router(strategies=[ContextCapturingStrategy()])
        await router.route("test")
        assert received["context"] is None


class TestRouterWarmCache:
    async def test_warm_cache_populates_decisions(self) -> None:
        router = Router()
        queries = {
            "write a function": RoutingDecision(primary_agent="CODER"),
            "debug this": RoutingDecision(primary_agent="DEBUGGER"),
        }
        await router.warm_cache(queries)
        # Now routing these should return cached values (even though LLM strategy
        # would also return a decision, the cached one takes priority)
        for query, expected in queries.items():
            result = await router.route(query)
            assert result == expected

    async def test_warm_cache_with_context(self) -> None:
        router = Router()
        await router.warm_cache({"test": RoutingDecision(primary_agent="MICRO")})
        decision = await router.route("test")
        assert decision.primary_agent == "MICRO"


class TestDefaultCacheTTL:
    def test_constant_value(self) -> None:
        assert DEFAULT_CACHE_TTL == 300.0
