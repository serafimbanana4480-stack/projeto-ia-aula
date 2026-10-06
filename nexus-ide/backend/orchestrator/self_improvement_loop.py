"""SelfImprovementLoop — autonomous system optimization based on metrics and feedback."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetric:
    """A performance metric snapshot."""

    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    threshold: float = 0.0
    unit: str = ""
    higher_is_better: bool = True  # False for metrics like error_rate, latency


@dataclass
class ImprovementAction:
    """An improvement action to take."""

    action_id: str
    name: str
    description: str
    handler: Callable[..., Any] = field(repr=False)
    expected_impact: float = 0.0  # Expected improvement in target metric
    target_metric: str = ""


class SelfImprovementLoop:
    """Autonomous self-improvement loop for the NEXUS system.

    Monitors performance metrics, identifies bottlenecks, and applies
    improvement actions automatically.
    """

    def __init__(self, target_metrics: list[str] | None = None) -> None:
        self._metrics: dict[str, list[PerformanceMetric]] = {}
        self._actions: list[ImprovementAction] = []
        self._target_metrics = target_metrics or ["response_time", "accuracy", "throughput"]
        self._improvement_log: list[dict[str, Any]] = []

    def record_metric(self, metric: PerformanceMetric) -> None:
        """Record a new performance metric."""
        if metric.name not in self._metrics:
            self._metrics[metric.name] = []
        self._metrics[metric.name].append(metric)
        # Keep last 1000 entries
        if len(self._metrics[metric.name]) > 1000:
            self._metrics[metric.name] = self._metrics[metric.name][-1000:]
        logger.debug("Recorded metric %s = %.2f %s", metric.name, metric.value, metric.unit)

    def register_action(self, action: ImprovementAction) -> None:
        """Register an improvement action."""
        self._actions.append(action)
        logger.debug("Registered improvement action: %s", action.name)

    def analyze(self) -> list[dict[str, Any]]:
        """Analyze metrics and identify improvement opportunities."""
        opportunities: list[dict[str, Any]] = []

        for metric_name, values in self._metrics.items():
            if not values:
                continue

            latest = values[-1]
            # Calculate trend
            if len(values) >= 10:
                recent = [v.value for v in values[-10:]]
                older = [v.value for v in values[-20:-10]] if len(values) >= 20 else recent[:5]
                if older:
                    recent_avg = sum(recent) / len(recent)
                    older_avg = sum(older) / len(older)
                    improved = recent_avg > older_avg
                    trend = "improving" if (improved if latest.higher_is_better else not improved) else "degrading"
                else:
                    trend = "stable"
            else:
                trend = "insufficient_data"

            # Check threshold (direction-aware)
            if latest.threshold > 0:
                is_below = latest.value < latest.threshold
                is_problem = is_below if latest.higher_is_better else not is_below
                if is_problem:
                    severity_ratio = latest.value / latest.threshold if latest.threshold != 0 else 0
                    opportunities.append({
                        "metric": metric_name,
                        "current_value": latest.value,
                        "threshold": latest.threshold,
                        "trend": trend,
                        "severity": "critical" if (severity_ratio < 0.7 if latest.higher_is_better else severity_ratio > 1.3) else "warning",
                    })

        return opportunities

    def apply_improvements(self) -> list[dict[str, Any]]:
        """Apply registered improvement actions for identified opportunities."""
        opportunities = self.analyze()
        results: list[dict[str, Any]] = []

        for opp in opportunities:
            metric_name = opp["metric"]
            # Find matching actions
            matching = [a for a in self._actions if a.target_metric == metric_name]
            if not matching:
                continue

            # Sort by expected impact
            matching.sort(key=lambda a: a.expected_impact, reverse=True)

            for action in matching[:3]:  # Apply top 3 actions
                try:
                    result = action.handler()
                    self._improvement_log.append({
                        "timestamp": time.time(),
                        "action": action.name,
                        "metric": metric_name,
                        "result": result,
                    })
                    results.append({
                        "action": action.name,
                        "metric": metric_name,
                        "status": "applied",
                        "result": result,
                    })
                    logger.info("Applied improvement: %s for %s", action.name, metric_name)
                except Exception as e:
                    results.append({
                        "action": action.name,
                        "metric": metric_name,
                        "status": "failed",
                        "error": str(e),
                    })
                    logger.error("Improvement action failed: %s — %s", action.name, e)

        return results

    def get_improvement_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._improvement_log[-limit:]

    def stats(self) -> dict[str, Any]:
        return {
            "metrics_tracked": len(self._metrics),
            "total_metric_readings": sum(len(v) for v in self._metrics.values()),
            "actions_registered": len(self._actions),
            "improvements_applied": len(self._improvement_log),
            "opportunities": len(self.analyze()),
        }
