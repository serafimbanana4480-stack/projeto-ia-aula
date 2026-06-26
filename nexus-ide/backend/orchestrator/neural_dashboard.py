"""NeuralDashboard — aggregated system health and metrics for the command center."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SystemMetric:
    """A system-wide metric snapshot."""

    name: str
    value: float
    unit: str = ""
    timestamp: float = field(default_factory=time.time)
    healthy: bool = True


@dataclass
class AgentHealth:
    """Health status for a single agent."""

    agent_id: str
    status: str = "healthy"  # healthy, warning, critical, offline
    last_seen: float = field(default_factory=time.time)
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    active_tasks: int = 0
    error_rate: float = 0.0


class NeuralDashboard:
    """Aggregated system dashboard for the Neural Command Center.

    Collects and summarizes:
    - System-wide metrics (CPU, memory, throughput)
    - Per-agent health status
    - Active debates, tasks, and communications
    - Alerts and anomalies
    """

    def __init__(self) -> None:
        self._metrics: dict[str, list[SystemMetric]] = {}
        self._agent_health: dict[str, AgentHealth] = {}
        self._alerts: list[dict[str, Any]] = []

    def record_metric(self, metric: SystemMetric) -> None:
        if metric.name not in self._metrics:
            self._metrics[metric.name] = []
        self._metrics[metric.name].append(metric)
        if len(self._metrics[metric.name]) > 1000:
            self._metrics[metric.name] = self._metrics[metric.name][-1000:]

    def update_agent_health(self, health: AgentHealth) -> None:
        self._agent_health[health.agent_id] = health

    def add_alert(self, level: str, message: str, source: str = "") -> None:
        self._alerts.append({
            "timestamp": time.time(),
            "level": level,
            "message": message,
            "source": source,
        })
        if len(self._alerts) > 1000:
            self._alerts = self._alerts[-1000:]

    def get_system_overview(self) -> dict[str, Any]:
        """Get high-level system overview."""
        total_agents = len(self._agent_health)
        healthy = sum(1 for h in self._agent_health.values() if h.status == "healthy")
        warning = sum(1 for h in self._agent_health.values() if h.status == "warning")
        critical = sum(1 for h in self._agent_health.values() if h.status == "critical")
        offline = sum(1 for h in self._agent_health.values() if h.status == "offline")

        latest_metrics = {}
        for name, values in self._metrics.items():
            if values:
                latest_metrics[name] = {
                    "value": values[-1].value,
                    "unit": values[-1].unit,
                    "healthy": values[-1].healthy,
                }

        return {
            "agents": {
                "total": total_agents,
                "healthy": healthy,
                "warning": warning,
                "critical": critical,
                "offline": offline,
            },
            "metrics": latest_metrics,
            "alerts": len(self._alerts),
            "timestamp": time.time(),
        }

    def get_agent_details(self, agent_id: str) -> Optional[dict[str, Any]]:
        health = self._agent_health.get(agent_id)
        if not health:
            return None
        return {
            "agent_id": health.agent_id,
            "status": health.status,
            "last_seen": health.last_seen,
            "cpu_percent": health.cpu_percent,
            "memory_mb": health.memory_mb,
            "active_tasks": health.active_tasks,
            "error_rate": health.error_rate,
        }

    def get_all_agents(self) -> list[dict[str, Any]]:
        agents = [self.get_agent_details(aid) for aid in self._agent_health]
        return [a for a in agents if a is not None]

    def get_alerts(self, level: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        alerts = self._alerts
        if level:
            alerts = [a for a in alerts if a["level"] == level]
        return alerts[-limit:]

    def get_metric_history(self, name: str, limit: int = 100) -> list[dict[str, Any]]:
        values = self._metrics.get(name, [])
        return [
            {"value": v.value, "unit": v.unit, "timestamp": v.timestamp, "healthy": v.healthy}
            for v in values[-limit:]
        ]
