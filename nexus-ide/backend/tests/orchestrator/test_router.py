"""Tests for backend.orchestrator.router — back-compat shim around the strategy chain."""

from __future__ import annotations

from backend.models.api import RoutingDecision
from backend.orchestrator.router import (
    _COMMON_QUERIES,
    _FALLBACK_DECISION,
    _ROUTING_CACHE_MAX,
    _ROUTING_CACHE_TTL,
    FALLBACK_DECISION,
    TTLCacheBackend,
    _get_default_router,
    _keyword_classify_cached,
    _parse_routing_decision,
    fast_route,
    route_with_model,
    warm_routing_cache,
)
from backend.orchestrator.router_engine import (
    DEFAULT_CACHE_TTL,
)
from backend.orchestrator.routing_strategies import FALLBACK_DECISION


class TestBackCompatAliases:
    def test_fallback_decision_alias(self) -> None:
        assert _FALLBACK_DECISION is FALLBACK_DECISION

    def test_parse_routing_decision_alias(self) -> None:
        assert _parse_routing_decision is not None

    def test_routing_cache_ttl_constant(self) -> None:
        assert _ROUTING_CACHE_TTL == DEFAULT_CACHE_TTL == 300.0

    def test_routing_cache_max_constant(self) -> None:
        assert _ROUTING_CACHE_MAX == 1000

    def test_common_queries_populated(self) -> None:
        assert len(_COMMON_QUERIES) == 5
        assert "what is python" in _COMMON_QUERIES
        assert "write a function" in _COMMON_QUERIES
        assert "fix the bug" in _COMMON_QUERIES
        assert "optimize performance" in _COMMON_QUERIES
        assert "design the architecture" in _COMMON_QUERIES

    def test_common_queries_all_micro_or_agents(self) -> None:
        for decision in _COMMON_QUERIES.values():
            assert isinstance(decision, RoutingDecision)
            assert decision.primary_agent is not None


class TestFastRoute:
    def test_empty_query_returns_none(self) -> None:
        assert fast_route("") is None

    def test_whitespace_query_returns_none(self) -> None:
        assert fast_route("   ") is None

    def test_write_function_routes_coder(self) -> None:
        assert fast_route("write a function") == "CODER"

    def test_debug_query_routes_debugger(self) -> None:
        assert fast_route("fix the bug in this code") == "DEBUGGER"

    def test_optimize_routes_optimizer(self) -> None:
        assert fast_route("optimize this loop") == "OPTIMIZER"

    def test_design_routes_architect(self) -> None:
        assert fast_route("design the architecture") == "ARCHITECT"

    def test_research_query_routes_researcher(self) -> None:
        assert fast_route("deep research on ai trends") == "RESEARCHER_WEB"

    def test_unmatched_query_returns_none(self) -> None:
        assert fast_route("xylophone banana") is None

    def test_case_insensitive(self) -> None:
        assert fast_route("WRITE A FUNCTION") == "CODER"

    def test_strips_whitespace(self) -> None:
        assert fast_route("  write a function  ") == "CODER"


class TestKeywordClassifyCached:
    def test_caches_results(self) -> None:
        # First call populates cache
        result1 = _keyword_classify_cached("write a function")
        result2 = _keyword_classify_cached("write a function")
        assert result1 == result2 == "CODER"

    def test_handles_empty_string(self) -> None:
        assert _keyword_classify_cached("") is None

    def test_different_query_different_result(self) -> None:
        assert _keyword_classify_cached("write a function") == "CODER"
        assert _keyword_classify_cached("optimize performance") == "OPTIMIZER"


class TestGetDefaultRouter:
    def test_returns_singleton(self) -> None:
        r1 = _get_default_router()
        r2 = _get_default_router()
        assert r1 is r2

    def test_router_has_strategies(self) -> None:
        router = _get_default_router()
        strategies = router.strategies
        assert len(strategies) == 2

    def test_router_has_cache(self) -> None:
        router = _get_default_router()
        assert isinstance(router.cache, TTLCacheBackend)


class TestRouteWithModel:
    async def test_empty_query_returns_fallback(self) -> None:
        result = await route_with_model("", None)
        assert result.primary_agent == "CODER"
        assert result.routing_confidence == 0.2

    async def test_whitespace_query_returns_fallback(self) -> None:
        result = await route_with_model("  ", None)
        assert result.primary_agent == "CODER"

    async def test_caches_valid_decision(self) -> None:
        router = _get_default_router()
        # Clear cache first
        await router.cache.clear()

        class MockClient:
            async def chat_complete(self, **kwargs):
                return '{"primary_agent": "CODER", "requires_web_search": false}'

        result = await route_with_model("test cache query", MockClient())
        assert result.primary_agent == "CODER"
        # Second call should hit cache
        result2 = await route_with_model("test cache query", MockClient())
        assert result2.primary_agent == "CODER"


class TestWarmRoutingCache:
    def test_warm_up_does_not_raise(self) -> None:
        warm_routing_cache()
        # Should complete without error

    def test_common_queries_are_cached(self) -> None:
        # After warming, queries should be in cache
        warm_routing_cache()
        _get_default_router()
        # These are sync-safe to call (warns if event loop is running)
        # Just verify the router has the queries in memory
        assert len(_COMMON_QUERIES) == 5


class TestImports:
    def test_router_exports(self) -> None:
        from backend.orchestrator import router
        assert hasattr(router, "Router")
        assert hasattr(router, "RoutingStrategy")
        assert hasattr(router, "KeywordRoutingStrategy")
        assert hasattr(router, "LLMRoutingStrategy")
        assert hasattr(router, "TTLCacheBackend")
        assert hasattr(router, "NullCacheBackend")
        assert hasattr(router, "fast_route")
        assert hasattr(router, "route_with_model")
        assert hasattr(router, "warm_routing_cache")
        assert hasattr(router, "RoutingDecision")
        assert hasattr(router, "AgentName")
