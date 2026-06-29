"""Prometheus custom metrics. See ARCHITECTURE.md §10.2."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# Counters
requests_total = Counter(
    "nexus_requests_total",
    "Total agent requests",
    ["agent", "model", "task_type", "status"],
)
tokens_generated_total = Counter(
    "nexus_tokens_generated_total", "Output tokens generated", ["agent", "model"]
)
tokens_input_total = Counter(
    "nexus_tokens_input_total", "Input tokens consumed", ["agent", "model"]
)
web_searches_total = Counter("nexus_web_searches_total", "Web searches performed", ["agent"])
fallbacks_total = Counter(
    "nexus_fallbacks_total", "Fallback invocations", ["from_agent", "to_agent", "reason"]
)

# Histograms
response_latency_seconds = Histogram(
    "nexus_response_latency_seconds",
    "End-to-end response latency",
    ["agent", "model", "task_type"],
)
ttft_seconds = Histogram("nexus_ttft_seconds", "Time to first token", ["agent", "model"])
react_iterations = Histogram("nexus_react_iterations", "ReAct iterations per request", ["agent"])

# Gauges
model_loaded = Gauge("nexus_model_loaded", "1 if model is loaded", ["model", "port"])
model_ram_bytes = Gauge("nexus_model_ram_bytes", "RAM used by model", ["model"])
queue_depth = Gauge("nexus_queue_depth", "Pending tasks per agent", ["agent"])
active_sessions = Gauge("nexus_active_sessions", "Concurrent sessions")

# ═════════════════════════════════════════════════════════════════════════════
# Mission Control observability metrics
# ═════════════════════════════════════════════════════════════════════════════

agent_runs_total = Counter(
    "nexus_agent_runs_total",
    "Total agent runs by agent and final status",
    ["agent", "status"],
)
agent_tokens_used = Histogram(
    "nexus_agent_tokens_used",
    "Token usage per agent run",
    ["agent"],
    buckets=[50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000],
)
agent_duration_seconds = Histogram(
    "nexus_agent_duration_seconds",
    "Duration of agent runs in seconds",
    ["agent"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)
mission_duration_seconds = Histogram(
    "nexus_mission_duration_seconds",
    "Duration of missions in seconds",
    ["status"],
    buckets=[5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0],
)
mission_success_rate = Gauge(
    "nexus_mission_success_rate",
    "Ratio of successful missions (0.0–1.0)",
)
bus_messages_total = Counter(
    "nexus_bus_messages_total",
    "Total bus messages by topic",
    ["topic"],
)
review_approval_rate = Gauge(
    "nexus_review_approval_rate",
    "Ratio of approved reviews (0.0–1.0)",
)

# =========================================================================
# Cost Tracking
# =========================================================================

# Pricing per model (USD per 1M tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Cloud providers
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.5, "output": 1.5},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-haiku": {"input": 0.5, "output": 1.5},
    "deepseek-chat": {"input": 0.5, "output": 1.5},
    "deepseek-coder": {"input": 0.5, "output": 1.5},
    "gemini-1.5-pro": {"input": 3.5, "output": 10.5},
    # OpenRouter free tier
    "openrouter/free": {"input": 0.0, "output": 0.0},
    # Local models (Ollama) — infrastructure cost estimate
    "qwen2.5:0.5b": {"input": 0.01, "output": 0.01},
    "qwen2.5-coder:1.5b": {"input": 0.02, "output": 0.02},
    "qwen2.5-coder:7b": {"input": 0.05, "output": 0.05},
    "llama3.1:8b": {"input": 0.05, "output": 0.05},
    "deepseek-r1:8b": {"input": 0.05, "output": 0.05},
    "codestral": {"input": 0.05, "output": 0.05},
    "nomic-embed-text": {"input": 0.005, "output": 0.005},
    # Default fallback
    "default": {"input": 0.1, "output": 0.1},
}

# Prometheus metrics for cost tracking
llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Total LLM cost in USD",
    ["model", "agent"],
)
llm_cost_per_session = Counter(
    "llm_cost_per_session",
    "LLM cost per session in USD",
    ["session_id"],
)
llm_session_token_count = Counter(
    "llm_session_token_count",
    "Total tokens per session",
    ["session_id", "direction"],  # direction = "input" or "output"
)

# Cache metrics (FASE 2)
cache_hits_total = Counter(
    "cache_hits_total",
    "Total cache hits",
    ["cache_type"],  # semantic, tool, embedding, routing
)
cache_misses_total = Counter(
    "cache_misses_total",
    "Total cache misses",
    ["cache_type"],
)
cache_size_current = Gauge(
    "cache_size_current",
    "Current cache size",
    ["cache_type"],
)
cache_hit_rate = Gauge(
    "cache_hit_rate",
    "Cache hit rate (0-1)",
    ["cache_type"],
)


class CostTracker:
    """Track LLM usage costs per session, agent, and model.

    Usage:
        tracker = CostTracker()
        cost = tracker.record(
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            session_id="abc123",
            agent="CODER",
        )
        report = tracker.get_report()
    """

    def __init__(self):
        self._session_costs: dict[str, float] = {}
        self._agent_costs: dict[str, float] = {}
        self._total_cost: float = 0.0

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        session_id: str,
        agent: str,
    ) -> float:
        """Record an LLM call and its cost.

        Args:
            model: Model name (e.g., 'gpt-4o', 'qwen2.5-coder:1.5b').
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            session_id: Session identifier.
            agent: Agent name (e.g., 'CODER', 'ARCHITECT').

        Returns:
            Cost in USD for this call.
        """
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        self._session_costs[session_id] = self._session_costs.get(session_id, 0.0) + cost
        self._agent_costs[agent] = self._agent_costs.get(agent, 0.0) + cost
        self._total_cost += cost

        # Push to Prometheus
        llm_cost_usd_total.labels(model=model, agent=agent).inc(cost)
        llm_cost_per_session.labels(session_id=session_id).inc(cost)
        llm_session_token_count.labels(session_id=session_id, direction="input").inc(input_tokens)
        llm_session_token_count.labels(session_id=session_id, direction="output").inc(output_tokens)

        return cost

    def get_session_cost(self, session_id: str) -> float:
        """Get total cost for a session."""
        return self._session_costs.get(session_id, 0.0)

    def get_agent_cost(self, agent: str) -> float:
        """Get total cost for an agent."""
        return self._agent_costs.get(agent, 0.0)

    def get_report(self) -> dict:
        """Get comprehensive cost report."""
        return {
            "total_cost_usd": round(self._total_cost, 6),
            "by_agent": {
                k: round(v, 6)
                for k, v in sorted(self._agent_costs.items(), key=lambda x: x[1], reverse=True)
            },
            "by_session_count": len(self._session_costs),
            "top_5_sessions": [
                {"session_id": sid, "cost_usd": round(cost, 6)}
                for sid, cost in sorted(
                    self._session_costs.items(), key=lambda x: x[1], reverse=True
                )[:5]
            ],
        }

    def reset(self) -> None:
        """Reset all cost tracking."""
        self._session_costs.clear()
        self._agent_costs.clear()
        self._total_cost = 0.0


# Global singleton
_cost_tracker: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker


def update_cache_metrics(cache_type: str, hits: int, misses: int, size: int):
    """Update Prometheus cache metrics.

    Args:
        cache_type: 'semantic', 'tool', 'embedding', or 'routing'.
        hits: Number of cache hits.
        misses: Number of cache misses.
        size: Current cache size.
    """
    total = hits + misses
    cache_hits_total.labels(cache_type=cache_type).inc(hits)
    cache_misses_total.labels(cache_type=cache_type).inc(misses)
    cache_size_current.labels(cache_type=cache_type).set(size)
    cache_hit_rate.labels(cache_type=cache_type).set(hits / max(1, total))
