"""Smart Router - automatic model tier selection based on heuristics and LLM fallback.

Complements the agent-level router (router.py) by selecting the optimal model
tier (micro, fast, coder, reasoning, deep) for a given query. The tier is then
mapped to the appropriate agent via the _MODEL_TIER_TO_AGENT mapping.

Pipeline integration:
    When the user does NOT explicitly select a model, the chat pipeline calls
    smart_route_tier() which returns a tier key. That tier is then mapped to
    the agent that uses the corresponding model.

Prioritizes (all cloud models via OpenCode Go):
1. Trivial queries  -> micro (mimo-v2.5)              ~200ms
2. Simple answers   -> fast (deepseek-v4-flash)       ~600ms
3. Code tasks       -> coder (kimi-k2.7-code)         ~1200ms
4. Reasoning        -> reasoning (glm-5.2)            ~2000ms
5. Deep analysis    -> deep (deepseek-v4-pro)         ~4000ms
6. Fallback: LLM classifier if heuristics uncertain

All models are cloud-based via OpenCode Go (no local ollama dependency).
The actual model for each tier is configured in ``config/models.yaml``.
"""

from __future__ import annotations

import functools
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from backend.config.settings import load_models_config
from backend.models.api import RoutingDecision
from backend.orchestrator.router import fast_route, route_with_model
from backend.orchestrator.routing_config import MODEL_TIER_TO_AGENT as _MODEL_TIER_TO_AGENT

logger = logging.getLogger(__name__)


@dataclass
class TierDecision:
    """Result of smart routing — selects a model tier."""

    tier: str
    model_id: str
    reason: str
    confidence: float
    decision_ms: int


# In-memory LRU cache for tier decisions (keyed by query prefix).
_tier_cache: OrderedDict[str, TierDecision] = OrderedDict()
_TIER_CACHE_MAX = 1000


def _word_count(text: str) -> int:
    return len(text.split())


def _contains_code(text: str) -> bool:
    code_indicators = [
        "function",
        "class",
        "def ",
        "import ",
        "const ",
        "let ",
        "var ",
        "=>",
        "return",
        "implement",
        "create a",
        "write a",
        "build a",
        "refactor",
        "api",
        "endpoint",
        "function that",
        "class that",
        "login",
        "authentication",
        "scraper",
        "cli",
        "script",
    ]
    return any(ind in text.lower() for ind in code_indicators)


# Action verbs that indicate a non-trivial task regardless of word count.
_ACTION_VERBS = frozenset(
    {
        "create",
        "build",
        "implement",
        "write",
        "develop",
        "design",
        "refactor",
        "optimize",
        "fix",
        "debug",
        "analyze",
        "review",
        "add",
        "remove",
        "update",
        "modify",
        "generate",
        "scaffold",
        "configure",
        "set up",
        "install",
        "deploy",
        "test",
        "criar",
        "construir",
        "implementar",
        "escrever",
        "desenvolver",
        "projetar",
        "otimizar",
        "corrigir",
        "depurar",
        "analisar",
    }
)


def _is_trivial(text: str, config: dict) -> bool:
    """Determine if a query is trivial (simple factoid lookup).

    Backwards-compatible wrapper around the cached implementation.
    """
    trivial_keywords = config.get("smart_router", {}).get("trivial_keywords", [])
    return _is_trivial_cached(text, tuple(trivial_keywords))


@functools.lru_cache(maxsize=1000)
def _is_trivial_cached(text: str, trivial_keywords: tuple[str, ...] = ()) -> bool:
    """Determine if a query is trivial (simple factoid lookup).

    A query is trivial ONLY if:
    - It is very short (<=3 words) AND contains no action verbs
    - It is a simple math expression
    - It is a trivial keyword match AND very short

    IMPORTANT: Queries with action verbs are NEVER trivial, even if short.
    """
    word_count = _word_count(text)
    lowered = text.lower()

    # If the query contains action verbs, it is NOT trivial
    if any(verb in lowered for verb in _ACTION_VERBS):
        return False

    # If the query contains code indicators, it is NOT trivial
    if _contains_code(text):
        return False

    # Very short queries with no action verbs (<=3 words) are trivial
    if word_count <= 3:
        return True

    # Simple math expressions
    has_math = any(op in text for op in ["+", "-", "*", "/", "=", "^"])
    if has_math and word_count <= 5:
        return True

    # Trivial keyword matches (e.g. "what is X", "quanto é X") with short length
    has_keyword = any(kw in lowered for kw in trivial_keywords)
    return bool(has_keyword and word_count <= 4)


def _classify_by_heuristics(user_input: str, config: dict) -> TierDecision | None:
    """Classify query into a model tier using deterministic heuristics.

    Returns None when heuristics are uncertain (falls through to LLM).

    Priority order: code > reasoning > deep > trivial > fast
    This ensures code queries are never misclassified as trivial.
    """
    word_count = _word_count(user_input)
    start = time.time()
    models = config.get("models", {})

    # Code → coder (check FIRST, before trivial, to avoid misrouting)
    if _contains_code(user_input):
        return TierDecision(
            tier="coder",
            model_id=models.get("coder", {}).get("id", "qwen2.5-coder:7b"),
            reason="Code-related query detected",
            confidence=0.85,
            decision_ms=int((time.time() - start) * 1000),
        )

    # Reasoning → reasoning
    reasoning_keywords = config.get("smart_router", {}).get("reasoning_keywords", [])
    # Also add common reasoning patterns not in config
    extra_reasoning = [
        "plan",
        "step by step",
        "explain why",
        "compare",
        "analyze",
        "think through",
        "reason about",
        "evaluate",
        "decide",
    ]
    all_reasoning = list(reasoning_keywords) + extra_reasoning
    if any(kw in user_input.lower() for kw in all_reasoning):
        return TierDecision(
            tier="reasoning",
            model_id=models.get("reasoning", {}).get("id", "deepseek-r1:8b"),
            reason="Reasoning task detected",
            confidence=0.8,
            decision_ms=int((time.time() - start) * 1000),
        )

    # Deep → deep
    deep_keywords = config.get("smart_router", {}).get("deep_keywords", [])
    # Also add common deep analysis patterns
    extra_deep = [
        "architecture",
        "design system",
        "scalable",
        "trade-off",
        "comprehensive",
        "in-depth",
        "thorough analysis",
    ]
    all_deep = list(deep_keywords) + extra_deep
    if any(kw in user_input.lower() for kw in all_deep) or word_count > 100:
        return TierDecision(
            tier="deep",
            model_id=models.get("deep", {}).get("id", "qwen2.5:32b"),
            reason=f"Deep analysis (word_count={word_count})",
            confidence=0.75,
            decision_ms=int((time.time() - start) * 1000),
        )

    # Trivial → micro (check AFTER code/reasoning/deep to avoid misrouting)
    if _is_trivial(user_input, config):
        return TierDecision(
            tier="micro",
            model_id=models.get("micro", {}).get("id", "mimo-v2.5"),
            reason=f"Trivial query (word_count={word_count})",
            confidence=0.95,
            decision_ms=int((time.time() - start) * 1000),
        )

    # Default for moderate queries → coder (better to over-power than under-power)
    if word_count <= 50:
        return TierDecision(
            tier="coder",
            model_id=models.get("coder", {}).get("id", "qwen2.5-coder:7b"),
            reason=f"Moderate query defaulting to coder (word_count={word_count})",
            confidence=0.6,
            decision_ms=int((time.time() - start) * 1000),
        )

    return None


async def _classify_by_llm(user_input: str, client: Any, config: dict) -> TierDecision:
    """Fallback LLM-based classification for uncertain cases."""
    start = time.time()
    models = config.get("models", {})

    prompt = (
        "Classify this query into one tier: micro, fast, coder, reasoning, deep.\n"
        f'Query: "{user_input[:200]}"\n'
        "Respond with ONLY the tier name."
    )

    try:
        micro_id = models.get("micro", {}).get("id", "mimo-v2.5")
        response = await client.chat_complete(
            model=micro_id,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": 10},
        )

        tier = response.strip().lower()
        if tier not in ("micro", "fast", "coder", "reasoning", "deep"):
            tier = "coder"  # default fallback for uncertain classification

        model_id = models.get(tier, {}).get("id", micro_id)

        return TierDecision(
            tier=tier,
            model_id=model_id,
            reason="LLM fallback classification",
            confidence=0.6,
            decision_ms=int((time.time() - start) * 1000),
        )
    except Exception as exc:
        logger.error("LLM classification failed: %s", exc)
        return TierDecision(
            tier="coder",
            model_id=models.get("coder", {}).get("id", "qwen2.5-coder:7b"),
            reason="LLM fallback failed, defaulting to CODER",
            confidence=0.5,
            decision_ms=int((time.time() - start) * 1000),
        )


@functools.lru_cache(maxsize=1000)
def _cached_heuristic_tier(query: str) -> str | None:
    """Fast sync path: return tier from deterministic heuristics if confident."""
    config = load_models_config()
    decision = _classify_by_heuristics(query, config)
    if decision is not None and decision.confidence >= 0.7:
        return decision.tier
    return None


async def smart_route_tier(query: str, client: Any) -> str:
    """Select the optimal model tier for a query.

    Returns the tier key (e.g. "coder", "reasoning", "deep") that should be
    used for this query. The caller maps the tier to the appropriate agent
    via the _MODEL_TIER_TO_AGENT mapping.

    This is the main entry point called from the chat pipeline.
    Uses a two-level cache:
      1. LRU cache on deterministic heuristics (sync, zero-cost).
      2. OrderedDict LRU for LLM fallback results.
    """
    normalized = query[:120].lower().strip()

    # Level 1: deterministic heuristic cache (sync, zero-cost)
    cached_tier = _cached_heuristic_tier(normalized)
    if cached_tier is not None:
        logger.debug("SmartRouter heuristic cache hit for tier: %s", cached_tier)
        return cached_tier

    # Level 2: LLM result cache
    if normalized in _tier_cache:
        cached = _tier_cache[normalized]
        logger.debug("SmartRouter LLM cache hit for tier: %s", cached.tier)
        # Move to end (most recently used)
        _tier_cache.move_to_end(normalized)
        return cached.tier

    config = load_models_config()

    # Heuristics first (zero-cost)
    decision = _classify_by_heuristics(query, config)

    # LLM fallback when heuristics are uncertain
    if decision is None or decision.confidence < 0.7:
        decision = await _classify_by_llm(query, client, config)

    # Cache the result with LRU eviction
    if len(_tier_cache) >= _TIER_CACHE_MAX:
        # Evict oldest 100 entries
        for _ in range(100):
            if _tier_cache:
                _tier_cache.popitem(last=False)
    _tier_cache[normalized] = decision

    logger.info(
        "SmartRouter: tier=%s confidence=%.2f reason=%s (%dms)",
        decision.tier,
        decision.confidence,
        decision.reason,
        decision.decision_ms,
    )

    return decision.tier


class SmartRouter:
    """Automatic query router implementing the 4-step pipeline described in docs.

    1. **Fast path** — deterministic keyword matching via :func:`fast_route`.
    2. **Cache check** — LRU cache of previous :class:`RoutingDecision` objects.
    3. **Model routing** — tier heuristic (``smart_route_tier``) maps to an agent.
    4. **Fallback chain** — LLM-based agent classification via
       :func:`route_with_model` if the tier heuristic is uncertain or fails.

    The class is fully backwards-compatible: ``smart_route_tier`` and all existing
    free functions remain untouched.
    """

    def __init__(self, llm_client: Any = None) -> None:
        self.llm_client = llm_client
        self._decision_cache: OrderedDict[str, RoutingDecision] = OrderedDict()
        self._cache_max = 1000

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _get_cached(self, key: str) -> RoutingDecision | None:
        if key in self._decision_cache:
            self._decision_cache.move_to_end(key)
            return self._decision_cache[key]
        return None

    def _store_cache(self, key: str, decision: RoutingDecision) -> None:
        if len(self._decision_cache) >= self._cache_max:
            for _ in range(100):
                if self._decision_cache:
                    self._decision_cache.popitem(last=False)
        self._decision_cache[key] = decision

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route(
        self,
        query: str,
        session_id: str = "",
        **kwargs: Any,
    ) -> RoutingDecision:
        """Route *query* through the 4-step pipeline and return a decision.

        Parameters
        ----------
        query:
            The user message to classify.
        session_id:
            Optional session identifier (reserved for future session-scoped
            caching).
        **kwargs:
            Reserved for future extensibility (e.g. project context).
        """
        if not query or not query.strip():
            return RoutingDecision(
                primary_agent="MICRO",
                routing_confidence=0.95,
                routing_reason="empty-query",
            )

        normalized = query[:120].lower().strip()

        # Step 1 — Fast path: deterministic keyword matching (zero-cost)
        fast = fast_route(query)
        if fast is not None:
            return RoutingDecision(
                primary_agent=fast,
                routing_confidence=0.9,
                routing_reason=f"fast-rule:{fast.lower()}",
            )

        # Step 2 — Cache check: LRU cache of previous RoutingDecision objects
        cached = self._get_cached(normalized)
        if cached is not None:
            return cached

        # Step 3 — Model routing: tier heuristic + optional LLM fallback
        decision: RoutingDecision | None = None
        try:
            tier = await smart_route_tier(query, self.llm_client)
            agent_name = _MODEL_TIER_TO_AGENT.get(tier, "CODER")
            decision = RoutingDecision(
                primary_agent=agent_name,  # type: ignore[arg-type]
                routing_confidence=0.8,
                routing_reason=f"smart-tier:{tier}",
            )
        except Exception as exc:
            logger.warning("SmartRouter tier routing failed: %s", exc)

        # Step 4 — Fallback chain: LLM-based agent classification
        if decision is None:
            try:
                decision = await route_with_model(query, self.llm_client)
            except Exception as exc:
                logger.warning("SmartRouter model routing failed: %s", exc)
                decision = RoutingDecision(
                    primary_agent="CODER",
                    routing_confidence=0.5,
                    routing_reason="fallback-chain-failure",
                )

        self._store_cache(normalized, decision)
        return decision
