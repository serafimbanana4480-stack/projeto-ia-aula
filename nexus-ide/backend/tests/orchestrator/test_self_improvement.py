import pytest
from backend.orchestrator.self_improvement_loop import (
    SelfImprovementLoop,
    PerformanceMetric,
    ImprovementAction,
)


def test_record_metric():
    loop = SelfImprovementLoop()
    metric = PerformanceMetric(name="response_time", value=120.0, threshold=100.0, unit="ms")
    loop.record_metric(metric)
    assert "response_time" in loop._metrics
    assert len(loop._metrics["response_time"]) == 1


def test_register_action():
    loop = SelfImprovementLoop()
    action = ImprovementAction(
        action_id="cache-1",
        name="Enable caching",
        description="Add result caching",
        handler=lambda: "done",
        expected_impact=50.0,
        target_metric="response_time",
    )
    loop.register_action(action)
    assert len(loop._actions) == 1


def test_analyze_finds_opportunity():
    loop = SelfImprovementLoop()
    # Add metrics below threshold
    for i in range(5):
        loop.record_metric(
            PerformanceMetric(name="response_time", value=80.0, threshold=100.0)
        )
    for i in range(5):
        loop.record_metric(
            PerformanceMetric(name="response_time", value=60.0, threshold=100.0)
        )
    for i in range(5):
        loop.record_metric(
            PerformanceMetric(name="accuracy", value=0.95, threshold=0.90)
        )

    opportunities = loop.analyze()
    assert len(opportunities) == 1
    assert opportunities[0]["metric"] == "response_time"
    assert opportunities[0]["severity"] == "critical"


def test_analyze_critical_severity():
    loop = SelfImprovementLoop()
    loop.record_metric(
        PerformanceMetric(name="response_time", value=50.0, threshold=100.0)
    )
    opportunities = loop.analyze()
    assert opportunities[0]["severity"] == "critical"


def test_apply_improvements():
    loop = SelfImprovementLoop()
    improvements = []

    def handler():
        improvements.append("cached")
        return "cached"

    action = ImprovementAction(
        action_id="cache-1",
        name="Enable caching",
        description="Cache results",
        handler=handler,
        expected_impact=40.0,
        target_metric="response_time",
    )
    loop.register_action(action)

    # Record degraded metric (below threshold = not meeting target)
    for i in range(20):
        loop.record_metric(
            PerformanceMetric(name="response_time", value=60.0, threshold=100.0)
        )

    results = loop.apply_improvements()
    assert len(results) == 1
    assert results[0]["status"] == "applied"
    assert len(improvements) == 1


def test_stats():
    loop = SelfImprovementLoop()
    loop.record_metric(PerformanceMetric(name="m1", value=1.0, threshold=0.5))
    loop.record_metric(PerformanceMetric(name="m1", value=2.0, threshold=0.5))
    stats = loop.stats()
    assert stats["metrics_tracked"] == 1
    assert stats["total_metric_readings"] == 2
