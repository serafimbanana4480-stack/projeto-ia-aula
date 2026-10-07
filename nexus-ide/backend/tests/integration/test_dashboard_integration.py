"""Integration tests for Neural Dashboard."""
from __future__ import annotations

from backend.orchestrator.neural_dashboard import AgentHealth, NeuralDashboard, SystemMetric
from backend.orchestrator.nexus_core import NexusCore


class TestDashboardIntegration:
    def test_system_overview_with_mixed_health(self):
        dash = NeuralDashboard()
        dash.update_agent_health(AgentHealth("a1", "healthy"))
        dash.update_agent_health(AgentHealth("a2", "warning", cpu_percent=85.0))
        dash.update_agent_health(AgentHealth("a3", "critical", error_rate=0.5))
        dash.update_agent_health(AgentHealth("a4", "offline"))

        dash.record_metric(SystemMetric("cpu", 45.0, "%"))
        dash.record_metric(SystemMetric("memory", 80.0, "%"))

        overview = dash.get_system_overview()
        assert overview["agents"]["total"] == 4
        assert overview["agents"]["healthy"] == 1
        assert overview["agents"]["warning"] == 1
        assert overview["agents"]["critical"] == 1
        assert overview["agents"]["offline"] == 1
        assert "cpu" in overview["metrics"]
        assert "memory" in overview["metrics"]

    def test_metric_history_time_series(self):
        dash = NeuralDashboard()
        for i in range(10):
            dash.record_metric(SystemMetric("latency", float(i * 10), "ms"))
        history = dash.get_metric_history("latency", limit=5)
        assert len(history) == 5
        assert history[0]["value"] == 50.0
        assert history[-1]["value"] == 90.0

    def test_alerts_filtering(self):
        dash = NeuralDashboard()
        dash.add_alert("warning", "High CPU", "monitor")
        dash.add_alert("critical", "Disk full", "disk")
        dash.add_alert("warning", "Memory pressure", "memory")

        warnings = dash.get_alerts(level="warning")
        assert len(warnings) == 2
        criticals = dash.get_alerts(level="critical")
        assert len(criticals) == 1

    def test_nexus_core_system_status(self):
        core = NexusCore()
        core.register_agent("exec-1", "executive", "CEO")
        core.register_agent("exec-2", "executive", "CTO")
        core.connect_agents("exec-1", "exec-2", "manages")

        status = core.get_system_status()
        assert "execution" in status
        assert "communication" in status
        assert "topology" in status
        assert "dashboard" in status
        assert "self_improvement" in status
        assert status["topology"]["nodes"] == 2
        assert status["topology"]["edges"] == 1

    def test_agent_details_returns_none_for_missing(self):
        dash = NeuralDashboard()
        assert dash.get_agent_details("missing") is None

    def test_get_all_agents_no_double_call(self):
        dash = NeuralDashboard()
        dash.update_agent_health(AgentHealth("z1"))
        dash.update_agent_health(AgentHealth("z2"))
        agents = dash.get_all_agents()
        assert len(agents) == 2
