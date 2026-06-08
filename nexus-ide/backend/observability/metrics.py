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
