
from backend.orchestrator.nexus_core import NexusCore


def test_nexus_core_initialization():
    core = NexusCore()
    assert core.pool is not None
    assert core.allocator is not None
    assert core.router is not None
    assert core.execution_engine is not None
    assert core.communication_bus is not None
    assert core.debate_visualizer is not None
    assert core.topology is not None
    assert core.dashboard is not None
    assert core.self_improvement is not None


def test_register_agent():
    core = NexusCore()
    core.register_agent("a1", "executive", "CEO", capabilities=["strategy"])
    node = core.topology.get_node("a1")
    assert node is not None
    assert node.agent_type == "executive"
    assert node.role == "CEO"
    assert "strategy" in node.capabilities

    health = core.dashboard.get_agent_details("a1")
    assert health is not None
    assert health["status"] == "healthy"


def test_connect_agents():
    core = NexusCore()
    core.register_agent("a1", "exec", "CEO")
    core.register_agent("a2", "exec", "CTO")
    core.connect_agents("a1", "a2", "manages")
    edges = core.topology.get_edges_for_node("a1")
    assert len(edges) == 1
    assert edges[0].target_id == "a2"


def test_get_system_status():
    core = NexusCore()
    core.register_agent("a1", "exec", "CEO")
    status = core.get_system_status()
    assert "execution" in status
    assert "communication" in status
    assert "topology" in status
    assert "dashboard" in status
    assert status["topology"]["nodes"] == 1
