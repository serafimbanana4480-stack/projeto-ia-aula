"""Tests for backend.agents.dashboard_agent."""

from __future__ import annotations

from backend.agents.base import AgentAction
from backend.agents.dashboard_agent import DashboardAgent


class TestDashboardAgent:
    def test_health_score_unmeasured_is_none(self) -> None:
        agent = DashboardAgent()

        assert agent.get_health_score() is None

    def test_metadata(self) -> None:
        agent = DashboardAgent()
        assert agent.name == "DASHBOARD"
        assert agent.model_key == "dashboard"
        assert agent.prompt_file == "dashboard"
        assert agent.supported_actions == {
            AgentAction.CONSULT_AGENT,
            AgentAction.RECALL_CONTEXT,
            AgentAction.STORE_MEMORY,
            AgentAction.ANALYZE_DATA,
        }

    def test_health_score_nominal(self) -> None:
        agent = DashboardAgent()
        agent._history.append(
            {
                "cpu_percent": 30.0,
                "ram_percent": 40.0,
                "disk_percent": 50.0,
                "avg_latency_ms": 200.0,
                "db_stats": {"tool_error_rate": 0.0},
            }
        )
        score = agent.get_health_score()
        assert 0.9 <= score <= 1.0

    def test_health_score_critical(self) -> None:
        agent = DashboardAgent()
        agent._history.append(
            {
                "cpu_percent": 95.0,
                "ram_percent": 95.0,
                "disk_percent": 95.0,
                "avg_latency_ms": 8000.0,
                "db_stats": {"tool_error_rate": 0.5},
            }
        )
        score = agent.get_health_score()
        assert 0.0 <= score <= 0.5

    def test_anomaly_detection_cpu(self) -> None:
        agent = DashboardAgent()
        snapshot = {
            "timestamp": "2024-01-01T00:00:00Z",
            "cpu_percent": 95.0,
            "ram_percent": 50.0,
            "disk_percent": 50.0,
            "avg_latency_ms": 100.0,
            "db_stats": {"tool_error_rate": 0.0},
        }
        alerts = agent._detect_anomalies(snapshot, [])
        assert any(a.metric == "cpu_percent" and a.severity == "critical" for a in alerts)

    def test_alert_storage_and_filtering(self) -> None:
        agent = DashboardAgent()
        alert = agent._make_alert(
            "warning", "ram_percent", 85.0, 80.0, "RAM high", "2024-01-01T00:00:00Z"
        )
        agent._alerts.append(alert)
        assert len(agent.get_alerts()) == 1
        assert len(agent.get_alerts(severity="warning")) == 1
        assert len(agent.get_alerts(severity="critical")) == 0
