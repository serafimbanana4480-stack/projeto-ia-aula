"""Usage store — tracks LLM token consumption by model and agent.

Provides aggregate metrics for the cost/usage dashboard widget.
Data is accumulated in-memory; for production, replace with a
time-series database (e.g., InfluxDB, QuestDB).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Approximate USD pricing per 1K tokens (input / output) for common models.
# Ordered from least to most expensive.  These are rough averages; real
# pricing depends on the provider and plan.
MODEL_PRICING_USD: dict[str, tuple[float, float]] = {
    # (input_price_per_1k, output_price_per_1k)
    "gemma2:2b": (0.0001, 0.0002),
    "phi3:mini": (0.0001, 0.0002),
    "llama3.2:1b": (0.0001, 0.0002),
    "llama3.2:3b": (0.00015, 0.00025),
    "llama3.1:8b": (0.0002, 0.0004),
    "mistral:7b": (0.0002, 0.0004),
    "qwen2.5:7b": (0.0002, 0.0004),
    "deepseek-r1:8b": (0.0003, 0.0005),
    "codellama:7b": (0.0002, 0.0004),
    "llama3.1:70b": (0.0008, 0.0015),
    "deepseek-r1:32b": (0.001, 0.002),
    "mixtral:8x7b": (0.0006, 0.001),
    "deepseek-chat": (0.0005, 0.0015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4-turbo": (0.01, 0.03),
    "claude-3-haiku": (0.00025, 0.00125),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-opus": (0.015, 0.075),
    "gemini-pro": (0.0005, 0.0015),
    "gemini-1.5-pro": (0.00125, 0.005),
    "openrouter/auto": (0.001, 0.003),
}

# Default price for unrecognised models
DEFAULT_INPUT_PRICE = 0.0005
DEFAULT_OUTPUT_PRICE = 0.0015


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Return estimated USD cost for a single request."""
    prices = MODEL_PRICING_USD.get(model, MODEL_PRICING_USD.get(model.lower()))
    if prices is None:
        prices = (DEFAULT_INPUT_PRICE, DEFAULT_OUTPUT_PRICE)
    cost_in = (tokens_in / 1000) * prices[0]
    cost_out = (tokens_out / 1000) * prices[1]
    return round(cost_in + cost_out, 6)


class UsageStore:
    """In-memory accumulator for token usage data.

    Data is kept in a rolling window (default 30 days) keyed by model and
    agent.  Old entries are pruned on write.
    """

    def __init__(self, retention_seconds: int = 30 * 86400):
        self._retention = retention_seconds
        # model -> list of (timestamp, tokens_in, tokens_out)
        self._by_model: dict[str, list[tuple[float, int, int]]] = defaultdict(list)
        # agent -> list of (timestamp, tokens_in, tokens_out)
        self._by_agent: dict[str, list[tuple[float, int, int]]] = defaultdict(list)
        self._lock = __import__("asyncio").Lock()

    async def record(
        self,
        model: str,
        agent: str,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        """Record a usage event."""
        now = time.time()
        async with self._lock:
            self._by_model[model].append((now, tokens_in, tokens_out))
            self._by_agent[agent].append((now, tokens_in, tokens_out))
            self._prune_locked()

    def _prune_locked(self) -> None:
        cutoff = time.time() - self._retention
        for store in (self._by_model, self._by_agent):
            for key in list(store.keys()):
                store[key] = [(t, i, o) for t, i, o in store[key] if t >= cutoff]
                if not store[key]:
                    del store[key]

    async def get_usage(
        self,
        range_seconds: int = 86400,
    ) -> dict[str, Any]:
        """Return aggregated usage within the given time window."""
        cutoff = time.time() - range_seconds
        async with self._lock:
            model_breakdown: dict[str, dict[str, Any]] = {}
            agent_breakdown: dict[str, dict[str, Any]] = {}

            total_in = 0
            total_out = 0
            total_cost = 0.0

            for model, records in self._by_model.items():
                in_range = [(t, i, o) for t, i, o in records if t >= cutoff]
                if not in_range:
                    continue
                sum_in = sum(i for _, i, _ in in_range)
                sum_out = sum(o for _, _, o in in_range)
                cost = estimate_cost(model, sum_in, sum_out)
                model_breakdown[model] = {
                    "tokens_in": sum_in,
                    "tokens_out": sum_out,
                    "total_tokens": sum_in + sum_out,
                    "cost": round(cost, 6),
                    "requests": len(in_range),
                }
                total_in += sum_in
                total_out += sum_out
                total_cost += cost

            for agent, records in self._by_agent.items():
                in_range = [(t, i, o) for t, i, o in records if t >= cutoff]
                if not in_range:
                    continue
                sum_in = sum(i for _, i, _ in in_range)
                sum_out = sum(o for _, _, o in in_range)
                agent_breakdown[agent] = {
                    "tokens_in": sum_in,
                    "tokens_out": sum_out,
                    "total_tokens": sum_in + sum_out,
                    "requests": len(in_range),
                }

            # Sort agents by total tokens descending, take top 5
            top_agents = sorted(
                agent_breakdown.items(),
                key=lambda x: x[1]["total_tokens"],
                reverse=True,
            )[:5]

            return {
                "total_tokens": total_in + total_out,
                "total_tokens_in": total_in,
                "total_tokens_out": total_out,
                "total_cost": round(total_cost, 6),
                "by_model": model_breakdown,
                "by_agent": {k: v for k, v in top_agents},
                "range_seconds": range_seconds,
                "generated_at": time.time(),
                "currency": "USD",
            }


# Global singleton
_store: UsageStore | None = None


def get_usage_store() -> UsageStore:
    """Get or create the global usage store singleton."""
    global _store
    if _store is None:
        _store = UsageStore()
    return _store
