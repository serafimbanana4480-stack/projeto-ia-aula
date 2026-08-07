"""Adaptive Strategy Selector — replaces hardcoded strategy selection with learned policy."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StrategyDecision:
    strategy: str
    confidence: float
    reasoning: str


class AdaptiveStrategySelector:
    """Replaces hardcoded strategy selection with learned policy."""

    def __init__(self) -> None:
        self._knowledge_base: Any | None = None
        try:
            from backend.core.knowledge_base import KnowledgeBase
            self._knowledge_base = KnowledgeBase.get_instance()
        except Exception:
            logger.debug("KnowledgeBase not available for AdaptiveStrategySelector")

    async def select_strategy(self, objective: str, context: dict[str, Any]) -> StrategyDecision:
        best_strategy = "divide"
        best_confidence = 0.5
        reasoning = "default"

        if self._knowledge_base:
            try:
                match = self._knowledge_base.find_matching_pattern("*", {"objective": objective, **context})
                if match:
                    steps = match.solution_steps
                    if steps and steps[0] in {"divide", "ensemble", "pipeline", "debate", "adaptive"}:
                        best_strategy = steps[0]
                        best_confidence = match.confidence
                        reasoning = f"matched pattern {match.pattern_id}"
            except Exception:
                logger.debug("Strategy lookup failed", exc_info=True)

        return StrategyDecision(strategy=best_strategy, confidence=best_confidence, reasoning=reasoning)
