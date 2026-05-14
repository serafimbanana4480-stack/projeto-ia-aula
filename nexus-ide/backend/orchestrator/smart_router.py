"""Smart Router - automatic tier selection based on heuristics and LLM fallback.

Prioritizes:
1. Trivial queries → MICRO (qwen2.5:0.5b) for <50ms
2. Code tasks → CODER (qwen2.5-coder:7b)
3. Reasoning → REASONING (deepseek-r1:14b)
4. Deep analysis → DEEP (qwen2.5:32b)
5. Fallback: LLM classifier if heuristics uncertain
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import yaml

from backend.config.settings import get_settings
from backend.persistence.db import log_routing_decision
from backend.tools.ollama_client import ChatMessage, OllamaClient

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    tier: str
    model_id: str
    reason: str
    confidence: float
    decision_ms: int


class SmartRouter:
    def __init__(self):
        self.settings = get_settings()
        self.ollama = OllamaClient()
        self.config = self._load_config()
        self._cache: dict[str, RoutingDecision] = {}
        self._cache_max = 1000

    def _load_config(self) -> dict:
        try:
            with open("config/models.yaml") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
            return {}

    def _word_count(self, text: str) -> int:
        return len(text.split())

    def _contains_code(self, text: str) -> bool:
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
        ]
        return any(ind in text.lower() for ind in code_indicators)

    def _is_trivial(self, text: str) -> bool:
        trivial_keywords = self.config.get("smart_router", {}).get("trivial_keywords", [])
        word_count = self._word_count(text)
        threshold = self.config.get("routing", {}).get("trivial_threshold_words", 6)

        if word_count <= threshold:
            return True

        has_math = any(op in text for op in ["+", "-", "*", "/", "=", "^"])
        has_keyword = any(kw in text.lower() for kw in trivial_keywords)

        return (has_math and word_count <= 10) or (has_keyword and word_count <= threshold)

    def _classify_by_heuristics(self, user_input: str) -> RoutingDecision | None:
        word_count = self._word_count(user_input)
        start = time.time()

        # Trivial → MICRO
        if self._is_trivial(user_input):
            return RoutingDecision(
                tier="micro",
                model_id=self.config["models"]["micro"]["id"],
                reason=f"Trivial query (word_count={word_count})",
                confidence=0.95,
                decision_ms=int((time.time() - start) * 1000),
            )

        # Code → CODER
        if self._contains_code(user_input):
            code_keywords = self.config.get("smart_router", {}).get("code_keywords", [])
            if any(kw in user_input.lower() for kw in code_keywords):
                return RoutingDecision(
                    tier="coder",
                    model_id=self.config["models"]["coder"]["id"],
                    reason="Code-related query",
                    confidence=0.85,
                    decision_ms=int((time.time() - start) * 1000),
                )

        # Reasoning → REASONING
        reasoning_keywords = self.config.get("smart_router", {}).get("reasoning_keywords", [])
        if any(kw in user_input.lower() for kw in reasoning_keywords):
            return RoutingDecision(
                tier="reasoning",
                model_id=self.config["models"]["reasoning"]["id"],
                reason="Reasoning task detected",
                confidence=0.8,
                decision_ms=int((time.time() - start) * 1000),
            )

        # Deep → DEEP
        deep_keywords = self.config.get("smart_router", {}).get("deep_keywords", [])
        if any(kw in user_input.lower() for kw in deep_keywords) or word_count > 100:
            return RoutingDecision(
                tier="deep",
                model_id=self.config["models"]["deep"]["id"],
                reason=f"Deep analysis (word_count={word_count})",
                confidence=0.75,
                decision_ms=int((time.time() - start) * 1000),
            )

        # Short queries → FAST
        if word_count <= 20:
            return RoutingDecision(
                tier="fast",
                model_id=self.config["models"]["fast"]["id"],
                reason=f"Short query (word_count={word_count})",
                confidence=0.7,
                decision_ms=int((time.time() - start) * 1000),
            )

        return None

    async def _classify_by_llm(self, user_input: str) -> RoutingDecision:
        """Fallback LLM-based classification for uncertain cases."""
        start = time.time()

        prompt = f"""Classify this query into one tier: micro, fast, coder, reasoning, deep.
Query: "{user_input[:200]}"
Respond with ONLY the tier name."""

        try:
            micro_id = self.config["models"]["micro"]["id"]
            response = await self.ollama.chat_complete(
                model=micro_id,
                messages=[ChatMessage(role="user", content=prompt)],
                options={"temperature": 0.1, "num_predict": 10},
            )

            tier = response.strip().lower()
            if tier not in ["micro", "fast", "coder", "reasoning", "deep"]:
                tier = "fast"  # default fallback

            model_id = self.config["models"].get(tier, {}).get("id", micro_id)

            return RoutingDecision(
                tier=tier,
                model_id=model_id,
                reason="LLM fallback classification",
                confidence=0.6,
                decision_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            return RoutingDecision(
                tier="fast",
                model_id=self.config["models"]["fast"]["id"],
                reason="LLM fallback failed, defaulting to FAST",
                confidence=0.5,
                decision_ms=int((time.time() - start) * 1000),
            )

    async def route(self, user_input: str, session_id: str | None = None) -> RoutingDecision:
        """Route user input to appropriate model tier."""
        # Cache check
        cache_key = user_input[:100]
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Heuristics
        decision = self._classify_by_heuristics(user_input)

        # LLM fallback
        if decision is None or decision.confidence < 0.7:
            decision = await self._classify_by_llm(user_input)

        # Cache
        if len(self._cache) >= self._cache_max:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = decision

        # Log decision
        log_routing_decision(
            session_id=session_id,
            user_input=user_input,
            tier_chosen=decision.tier,
            reason=decision.reason,
            confidence=decision.confidence,
            word_count=self._word_count(user_input),
            decision_ms=decision.decision_ms,
        )

        return decision


_router_instance: SmartRouter | None = None


def get_smart_router() -> SmartRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = SmartRouter()
    return _router_instance
