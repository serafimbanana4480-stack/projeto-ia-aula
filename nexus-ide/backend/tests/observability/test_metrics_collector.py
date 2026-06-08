"""Tests for backend.observability.metrics_collector — Mission Control metrics."""

from __future__ import annotations

import pytest

from backend.observability.metrics_collector import MetricsCollector, get_metrics_collector
from backend.observability import metrics


class TestMetricsCollector:
    @pytest.fixture
    def collector(self) -> MetricsCollector:
        return MetricsCollector()

    @pytest.mark.asyncio
    async def test_record_agent_run(self, collector: MetricsCollector) -> None:
        """Recording an agent run should update counters and histograms."""
        before_runs = metrics.agent_runs_total.labels(agent="CODER", status="success")._value.get()
        before_tokens = metrics.agent_tokens_used.labels(agent="CODER")._sum.get()
        before_duration = metrics.agent_duration_seconds.labels(agent="CODER")._sum.get()

        await collector.record_agent_run("CODER", "success", tokens=512, duration_seconds=2.5)

        assert metrics.agent_runs_total.labels(agent="CODER", status="success")._value.get() == before_runs + 1
        assert metrics.agent_tokens_used.labels(agent="CODER")._sum.get() == before_tokens + 512
        assert metrics.agent_duration_seconds.labels(agent="CODER")._sum.get() == before_duration + 2.5

    @pytest.mark.asyncio
    async def test_record_agent_run_failure(self, collector: MetricsCollector) -> None:
        """Failed agent runs should be recorded with a different status label."""
        before = metrics.agent_runs_total.labels(agent="DEBUGGER", status="failed")._value.get()
        await collector.record_agent_run("DEBUGGER", "failed", tokens=0, duration_seconds=0.5)
        assert metrics.agent_runs_total.labels(agent="DEBUGGER", status="failed")._value.get() == before + 1

    @pytest.mark.asyncio
    async def test_record_mission(self, collector: MetricsCollector) -> None:
        """Recording a mission should update the mission duration histogram."""
        before = metrics.mission_duration_seconds.labels(status="completed")._sum.get()
        await collector.record_mission("completed", duration_seconds=120.0)
        assert metrics.mission_duration_seconds.labels(status="completed")._sum.get() == before + 120.0

    @pytest.mark.asyncio
    async def test_record_bus_message(self, collector: MetricsCollector) -> None:
        """Recording a bus message should increment the topic counter."""
        before = metrics.bus_messages_total.labels(topic="code.changes")._value.get()
        await collector.record_bus_message("code.changes")
        assert metrics.bus_messages_total.labels(topic="code.changes")._value.get() == before + 1

    @pytest.mark.asyncio
    async def test_get_snapshot(self, collector: MetricsCollector) -> None:
        """get_snapshot should return a MetricsSnapshot with sane defaults."""
        snapshot = await collector.get_snapshot(active_sessions=3, queue_depth=1)
        assert snapshot.active_sessions == 3
        assert snapshot.queue_depth == 1
        assert snapshot.tokens_per_second >= 0.0
        assert snapshot.uptime_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_singleton_collector(self) -> None:
        """get_metrics_collector should always return the same instance."""
        c1 = get_metrics_collector()
        c2 = get_metrics_collector()
        assert c1 is c2
