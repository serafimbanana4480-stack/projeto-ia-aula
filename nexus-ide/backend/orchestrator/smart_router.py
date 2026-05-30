"""Smart Router - automatic model tier selection based on heuristics and LLM fallback.

Complements the agent-level router (router.py) by selecting the optimal model
tier (micro, fast, coder, reasoning, deep) for a given query. The tier is then
mapped to the appropriate agent via the _MODEL_TIER_TO_AGENT mapping.

Pipeline integration:
    When the user does NOT explicitly select a model, the chat pipeline calls
    smart_route_tier() which returns a tier key. That tier is then mapped to
    the agent that uses the corresponding model.

Prioritizes:
1. Trivial queries → micro (qwen2.5:0.5b) for <50ms
2. Code tasks → coder (qwen2.5-coder:7b)
3. Reasoning → reasoning (deepseek-r1:8b)
4. Deep analysis → deep (qwen2.5:32b)
5. Fallback: LLM classifier if heuristics uncertain
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from backend.config.settings import get_model_config, load_models_config
from backend.tools.ollama_client import ChatMessage
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TierDecision:
    """Result of smart routing — selects a model tier."""

    tier: str
    model_id: str
    reason: str
    confidence: float
    decision_ms: int


# In-memory cache for tier decisions (keyed by query prefix).
_tier_cache: dict[str, TierDecision] = {}
_TIER_CACHE_MAX = 500


def _word_count(text: str) -> int:
    return len(text.split())


def _contains_code(text: str) -> bool:
    code_indicators = [
        "function", "class", "def ", "import ", "const ",
        "let ", "var ", "=>", "return", "implement", "create a",
        "write a", "build a", "refactor", "api", "endpoint",
        "function that", "class that", "login", "authentication",
        "scraper", "cli", "script",
    ]
    return any(ind in text.lower() for ind in code_indicators)


# Action verbs that indicate a non-trivial task regardless of word count.
_ACTION_VERBS = frozenset({
    "create", "build", "implement", "write", "develop", "design",
    "refactor", "optimize", "fix", "debug", "analyze", "review",
    "add", "remove", "update", "modify", "generate", "scaffold",
    "configure", "set up", "install", "deploy", "test",
    "criar", "construir", "implementar", "escrever", "desenvolver",
    "projetar", "otimizar", "corrigir", "depurar", "analisar",
})


def _is_trivial(text: str, config: dict) -> bool:
    """Determine if a query is trivial (simple factoid lookup).

    A query is trivial ONLY if:
    - It is very short (<=3 words) AND contains no action verbs
    - It is a simple math expression
    - It is a trivial keyword match AND very short

    IMPORTANT: Queries with action verbs are NEVER trivial, even if short.
    """
    trivial_keywords = config.get("smart_router", {}).get("trivial_keywords", [])
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
    if has_keyword and word_count <= 4:
        return True

    return False


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
    extra_reasoning = ["plan", "step by step", "explain why", "compare", "analyze",
                       "think through", "reason about", "evaluate", "decide"]
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
    extra_deep = ["architecture", "design system", "scalable", "trade-off",
                  "comprehensive", "in-depth", "thorough analysis"]
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
            model_id=models.get("micro", {}).get("id", "qwen2.5:0.5b"),
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
        micro_id = models.get("micro", {}).get("id", "qwen2.5:0.5b")
        response = await client.chat_complete(
            model=micro_id,
            messages=[ChatMessage(role="user", content=prompt)],
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


async def smart_route_tier(query: str, client: Any) -> str:
    """Select the optimal model tier for a query.

    Returns the tier key (e.g. "coder", "reasoning", "deep") that should be
    used for this query. The caller maps the tier to the appropriate agent
    via the _MODEL_TIER_TO_AGENT mapping.

    This is the main entry point called from the chat pipeline.
    """
    # Cache check
    cache_key = query[:100].lower().strip()
    if cache_key in _tier_cache:
        cached = _tier_cache[cache_key]
        logger.debug("SmartRouter cache hit for tier: %s", cached.tier)
        return cached.tier

    config = load_models_config()

    # Heuristics first (zero-cost)
    decision = _classify_by_heuristics(query, config)

    # LLM fallback when heuristics are uncertain
    if decision is None or decision.confidence < 0.7:
        decision = await _classify_by_llm(query, client, config)

    # Cache the result
    if len(_tier_cache) >= _TIER_CACHE_MAX:
        # Evict oldest entries
        keys_to_remove = list(_tier_cache.keys())[:100]
        for k in keys_to_remove:
            del _tier_cache[k]
    _tier_cache[cache_key] = decision

    logger.info(
        "SmartRouter: tier=%s confidence=%.2f reason=%s (%dms)",
        decision.tier, decision.confidence, decision.reason, decision.decision_ms,
    )

    return decision.tier
