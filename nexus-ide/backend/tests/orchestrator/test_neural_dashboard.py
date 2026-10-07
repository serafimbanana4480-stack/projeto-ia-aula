
from backend.orchestrator.neural_dashboard import (
    AgentHealth,
    NeuralDashboard,
    SystemMetric,
)


def test_record_metric():
    dash = NeuralDashboard()
    dash.record_metric(SystemMetric(name="cpu", value=45.0, unit="%"))
    assert "cpu" in dash._metrics
    assert len(dash._metrics["cpu"]) == 1


def test_update_agent_health():
    dash = NeuralDashboard()
    dash.update_agent_health(AgentHealth(agent_id="a1", status="healthy", cpu_percent=10.0))
    assert "a1" in dash._agent_health
    assert dash._agent_health["a1"].status == "healthy"


def test_add_alert():
    dash = NeuralDashboard()
    dash.add_alert("warning", "High CPU", "monitor")
    assert len(dash._alerts) == 1
    assert dash._alerts[0]["level"] == "warning"


def test_get_system_overview():
    dash = NeuralDashboard()
    dash.update_agent_health(AgentHealth("a1", "healthy"))
    dash.update_agent_health(AgentHealth("a2", "warning"))
    dash.update_agent_health(AgentHealth("a3", "critical"))
    dash.record_metric(SystemMetric("cpu", 50.0, "%"))
    overview = dash.get_system_overview()
    assert overview["agents"]["total"] == 3
    assert overview["agents"]["healthy"] == 1
    assert overview["agents"]["warning"] == 1
    assert overview["agents"]["critical"] == 1
    assert "cpu" in overview["metrics"]
    assert overview["metrics"]["cpu"]["value"] == 50.0


def test_get_agent_details():
    dash = NeuralDashboard()
    dash.update_agent_health(AgentHealth("a1", "healthy", cpu_percent=15.0, memory_mb=256.0))
    details = dash.get_agent_details("a1")
    assert details["status"] == "healthy"
    assert details["cpu_percent"] == 15.0
    assert details["memory_mb"] == 256.0


def test_get_all_agents():
    dash = NeuralDashboard()
    dash.update_agent_health(AgentHealth("a1"))
    dash.update_agent_health(AgentHealth("a2"))
    agents = dash.get_all_agents()
    assert len(agents) == 2


def test_get_alerts_filtered():
    dash = NeuralDashboard()
    dash.add_alert("warning", "W1")
    dash.add_alert("critical", "C1")
    dash.add_alert("warning", "W2")
    warnings = dash.get_alerts(level="warning")
    assert len(warnings) == 2


def test_get_metric_history():
    dash = NeuralDashboard()
    for i in range(5):
        dash.record_metric(SystemMetric("cpu", float(i), "%"))
    history = dash.get_metric_history("cpu", limit=3)
    assert len(history) == 3
    assert history[-1]["value"] == 4.0
