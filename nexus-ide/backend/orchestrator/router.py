"""Intelligent routing layer (shim).

Three-level routing described in ARCHITECTURE.md §4.2:

1. Fast rules - deterministic, zero-cost (:func:`fast_route`).
2. ROUTER model (NANO) - JSON classification (:func:`route_with_model`).
3. Automatic fallback - see :mod:`backend.orchestrator.fallback`.

This module is a thin back-compat shim. The real implementation lives in:

* :mod:`backend.orchestrator.routing_strategies` — the Strategy pattern
  implementations (keyword, LLM, recording).
* :mod:`backend.orchestrator.router_engine` — the :class:`Router` engine
  that composes strategies and a cache.
* :mod:`backend.cache_backends` — the cache backend abstractions.

The public ``RoutingDecision`` type lives in :mod:`backend.models.api` and is
re-exported here for backwards compatibility with existing imports.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any

from backend.cache_backends import NullCacheBackend, TTLCacheBackend
from backend.config.settings import get_model_config, load_prompt
from backend.llm.factory import create_llm_client
from backend.models.api import AgentName, RoutingDecision
from backend.orchestrator.router_engine import (
    DEFAULT_CACHE_TTL,
    Router,
    _query_hash,
)
from backend.orchestrator.routing_strategies import (
    FALLBACK_DECISION,
    KeywordRoutingStrategy,
    LLMRoutingStrategy,
    RoutingStrategy,
    parse_routing_decision,
)
from backend.tools.ollama_client import ChatMessage
from backend.tools.sanitizer import detect_injection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Back-compat private aliases
# ---------------------------------------------------------------------------
# The historical module exposed a number of "private" symbols that the
# existing test suite (and possibly other callers) import by name. Re-export
# them here so the refactor stays non-breaking.

#: Cached routing cache TTL (seconds). Kept for back-compat with code that
#: imported the previous module-level constant.
_ROUTING_CACHE_TTL: float = DEFAULT_CACHE_TTL

#: Maximum cache size. Kept for back-compat.
_ROUTING_CACHE_MAX: int = 1000

#: Back-compat alias for the fallback decision used by the LLM-based path.
_FALLBACK_DECISION: RoutingDecision = FALLBACK_DECISION

#: Back-compat alias for the JSON → RoutingDecision parser.
_parse_routing_decision = parse_routing_decision


# ---------------------------------------------------------------------------
# Default router — lazily instantiated so importing this module stays cheap.
# ---------------------------------------------------------------------------

_default_router: Router | None = None


def _get_default_router() -> Router:
    """Return the process-wide default :class:`Router` instance.

    The router is created on first access and re-used for the lifetime of
    the process. Tests that need isolation should instantiate their own
    :class:`Router` and pass it explicitly.
    """
    global _default_router
    if _default_router is None:
        _default_router = Router(
            strategies=[
                KeywordRoutingStrategy(),
                LLMRoutingStrategy(llm_client=create_llm_client()),
            ],
            cache=TTLCacheBackend(),
        )
    return _default_router


# ---------------------------------------------------------------------------
# Common queries used to warm the routing cache at startup.
# ---------------------------------------------------------------------------

_COMMON_QUERIES: dict[str, RoutingDecision] = {
    "what is python": RoutingDecision(
        primary_agent="MICRO",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="fast",
        estimated_complexity=1,
        task_type="question",
        context_needed="low",
        routing_confidence=0.95,
        routing_reason="common-trivial-question",
    ),
    "write a function": RoutingDecision(
        primary_agent="CODER",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="fast",
        estimated_complexity=4,
        task_type="code_generation",
        context_needed="low",
        routing_confidence=0.9,
        routing_reason="common-code-request",
    ),
    "fix the bug": RoutingDecision(
        primary_agent="DEBUGGER",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="iterative",
        estimated_complexity=5,
        task_type="debugging",
        context_needed="high",
        routing_confidence=0.9,
        routing_reason="common-debug-request",
    ),
    "optimize performance": RoutingDecision(
        primary_agent="OPTIMIZER",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="deep",
        estimated_complexity=6,
        task_type="optimization",
        context_needed="high",
        routing_confidence=0.9,
        routing_reason="common-optimization-request",
    ),
    "design the architecture": RoutingDecision(
        primary_agent="ARCHITECT",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="deep",
        estimated_complexity=8,
        task_type="design",
        context_needed="high",
        routing_confidence=0.9,
        routing_reason="common-architecture-request",
    ),
}


def warm_routing_cache() -> None:
    """Pre-populate the routing cache with common queries at startup."""
    router = _get_default_router()
    try:
        asyncio.run(router.warm_cache(_COMMON_QUERIES))
    except RuntimeError:
        # Called from within a running loop — schedule the warm-up as a task
        # so callers in async contexts can still trigger cache priming.
        loop = asyncio.get_event_loop()
        loop.create_task(router.warm_cache(_COMMON_QUERIES))
    logger.info("Routing cache warmed with %d common queries", len(_COMMON_QUERIES))


# ---------------------------------------------------------------------------
# Level 1 - fast deterministic rules (shim)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1000)
def _keyword_classify_cached(normalized_query: str) -> AgentName | None:
    """Cached inner keyword classifier. Delegates to the strategy helper."""
    from backend.orchestrator.routing_strategies import _keyword_classify

    return _keyword_classify(normalized_query)


def fast_route(query: str) -> AgentName | None:
    """Level 1 - deterministic pre-routing.

    Returns an agent name when the query is trivially classifiable, otherwise
    ``None`` so the caller falls through to :func:`route_with_model`.

    Priority order matters: more specific markers are checked first to avoid
    false positives. For example, "fix the error" should route to DEBUGGER,
    not CODER, even though "fix" could imply coding.

    This is a thin shim that delegates to
    :class:`backend.orchestrator.routing_strategies.KeywordRoutingStrategy`'s
    internal keyword classifier. The LRU cache is preserved for performance
    parity with the previous implementation.
    """
    if not query or not query.strip():
        return None
    return _keyword_classify_cached(query.lower().strip())


# ---------------------------------------------------------------------------
# Level 2 - model-based classification (shim)
# ---------------------------------------------------------------------------


async def route_with_model(query: str, client: Any) -> RoutingDecision:
    """Level 2 - ask the NANO model to classify the request.

    Returns a best-effort :class:`RoutingDecision`. If the model output is
    missing/malformed or the call fails, returns a low-confidence default
    decision pointing to CODER so the system always makes forward progress.
    The caller should use the ``routing_confidence`` field to decide whether
    to escalate.

    This shim delegates the LLM call to
    :class:`backend.orchestrator.routing_strategies.LLMRoutingStrategy` while
    sharing the cache of the default :class:`Router` instance so caching
    behaviour is preserved end-to-end.
    """
    if not query or not query.strip():
        return _FALLBACK_DECISION

    router = _get_default_router()
    cache_key = _query_hash(query)
    cached = await router.cache.get(cache_key)
    if isinstance(cached, RoutingDecision):
        logger.debug("Routing decision cache hit for query hash: %s", cache_key[:8])
        return cached

    if detect_injection(query).detected:
        decision = _FALLBACK_DECISION.model_copy(
            update={"routing_reason": "prompt-injection-detected", "primary_agent": "MICRO"}
        )
        await router.cache.set(cache_key, decision, _ROUTING_CACHE_TTL)
        return decision

    try:
        model_id = get_model_config("nano")["id"]
        system = load_prompt("router")
    except (KeyError, FileNotFoundError) as exc:
        logger.error("Router misconfigured: %s", exc)
        return _FALLBACK_DECISION

    try:
        raw = await client.chat_complete(
            model=model_id,
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=query),
            ],
            options={"temperature": 0.1, "num_predict": 512},
        )
    except Exception as exc:
        logger.warning("Router model call failed: %s", exc)
        return _FALLBACK_DECISION

    decision = parse_routing_decision(raw)
    await router.cache.set(cache_key, decision, _ROUTING_CACHE_TTL)
    return decision


__all__ = [
    "RoutingDecision",
    "AgentName",
    "fast_route",
    "route_with_model",
    "warm_routing_cache",
    # New public API re-exported for back-compat with the strategy refactor.
    "Router",
    "RoutingStrategy",
    "KeywordRoutingStrategy",
    "LLMRoutingStrategy",
    "TTLCacheBackend",
    "NullCacheBackend",
    # Private back-compat aliases. Re-exported so tests that import them
    # by their historical names keep working.
    "_FALLBACK_DECISION",
    "_parse_routing_decision",
    "_ROUTING_CACHE_TTL",
    "_ROUTING_CACHE_MAX",
    "_query_hash",
]
