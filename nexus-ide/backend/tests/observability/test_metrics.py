"""Tests for backend.observability.metrics — Prometheus metrics existence."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from backend.observability import metrics


class TestMetricsExist:
    def test_counters(self) -> None:
        assert isinstance(metrics.requests_total, Counter)
        assert isinstance(metrics.tokens_generated_total, Counter)
        assert isinstance(metrics.tokens_input_total, Counter)
        assert isinstance(metrics.web_searches_total, Counter)
        assert isinstance(metrics.fallbacks_total, Counter)
        assert isinstance(metrics.agent_runs_total, Counter)
        assert isinstance(metrics.bus_messages_total, Counter)

    def test_histograms(self) -> None:
        assert isinstance(metrics.response_latency_seconds, Histogram)
        assert isinstance(metrics.ttft_seconds, Histogram)
        assert isinstance(metrics.react_iterations, Histogram)
        assert isinstance(metrics.agent_tokens_used, Histogram)
        assert isinstance(metrics.agent_duration_seconds, Histogram)
        assert isinstance(metrics.mission_duration_seconds, Histogram)

    def test_gauges(self) -> None:
        assert isinstance(metrics.model_loaded, Gauge)
        assert isinstance(metrics.model_ram_bytes, Gauge)
        assert isinstance(metrics.queue_depth, Gauge)
        assert isinstance(metrics.active_sessions, Gauge)
        assert isinstance(metrics.mission_success_rate, Gauge)
        assert isinstance(metrics.review_approval_rate, Gauge)

    def test_requests_total_labels(self) -> None:
        labels = metrics.requests_total._labelnames
        assert "agent" in labels
        assert "model" in labels
        assert "task_type" in labels
        assert "status" in labels
