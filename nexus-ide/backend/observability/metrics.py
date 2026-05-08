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
web_searches_total = Counter(
    "nexus_web_searches_total", "Web searches performed", ["agent"]
)
fallbacks_total = Counter(
    "nexus_fallbacks_total", "Fallback invocations", ["from_agent", "to_agent", "reason"]
)

# Histograms
response_latency_seconds = Histogram(
    "nexus_response_latency_seconds",
    "End-to-end response latency",
    ["agent", "model", "task_type"],
)
ttft_seconds = Histogram(
    "nexus_ttft_seconds", "Time to first token", ["agent", "model"]
)
react_iterations = Histogram(
    "nexus_react_iterations", "ReAct iterations per request", ["agent"]
)

# Gauges
model_loaded = Gauge("nexus_model_loaded", "1 if model is loaded", ["model", "port"])
model_ram_bytes = Gauge("nexus_model_ram_bytes", "RAM used by model", ["model"])
queue_depth = Gauge("nexus_queue_depth", "Pending tasks per agent", ["agent"])
active_sessions = Gauge("nexus_active_sessions", "Concurrent sessions")
