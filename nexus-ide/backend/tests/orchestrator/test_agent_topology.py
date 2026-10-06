
from backend.orchestrator.agent_topology import (
    AgentEdge,
    AgentNode,
    AgentTopology,
)


def test_add_and_get_node():
    topo = AgentTopology()
    node = AgentNode(agent_id="a1", agent_type="executive", role="CEO")
    topo.add_node(node)
    assert topo.get_node("a1") == node


def test_remove_node():
    topo = AgentTopology()
    topo.add_node(AgentNode("a1", "exec", "CEO"))
    topo.add_edge(AgentEdge("a1", "a2", "manages"))
    topo.add_node(AgentNode("a2", "exec", "CTO"))
    assert topo.remove_node("a1") is True
    assert topo.get_node("a1") is None
    assert len(topo._edges) == 0


def test_get_neighbors():
    topo = AgentTopology()
    topo.add_node(AgentNode("a1", "exec", "CEO"))
    topo.add_node(AgentNode("a2", "exec", "CTO"))
    topo.add_node(AgentNode("a3", "team", "Dev"))
    topo.add_edge(AgentEdge("a1", "a2", "manages", bidirectional=True))
    topo.add_edge(AgentEdge("a2", "a3", "supervises", bidirectional=True))
    neighbors = topo.get_neighbors("a2")
    assert len(neighbors) == 2
    ids = {n.agent_id for n in neighbors}
    assert ids == {"a1", "a3"}


def test_to_dict():
    topo = AgentTopology()
    topo.add_node(AgentNode("a1", "exec", "CEO"))
    topo.add_edge(AgentEdge("a1", "a2", "manages", weight=2.0))
    d = topo.to_dict()
    assert len(d["nodes"]) == 1
    assert d["nodes"][0]["id"] == "a1"
    assert len(d["edges"]) == 1
    assert d["edges"][0]["weight"] == 2.0


def test_get_hierarchy():
    topo = AgentTopology()
    topo.add_node(AgentNode("ceo", "exec", "CEO"))
    topo.add_node(AgentNode("cto", "exec", "CTO"))
    topo.add_node(AgentNode("dev", "team", "Dev"))
    topo.add_edge(AgentEdge("ceo", "cto", "manages"))
    topo.add_edge(AgentEdge("cto", "dev", "supervises"))
    tree = topo.get_hierarchy("ceo")
    assert tree["id"] == "ceo"
    assert len(tree["children"]) == 1
    assert tree["children"][0]["id"] == "cto"
    assert len(tree["children"][0]["children"]) == 1
    assert tree["children"][0]["children"][0]["id"] == "dev"


def test_stats():
    topo = AgentTopology()
    topo.add_node(AgentNode("a1", "exec", "CEO"))
    topo.add_node(AgentNode("a2", "team", "Dev", status="inactive"))
    topo.add_edge(AgentEdge("a1", "a2", "manages"))
    stats = topo.stats()
    assert stats["nodes"] == 2
    assert stats["edges"] == 1
    assert stats["active_nodes"] == 1
    assert "manages" in stats["relationship_types"]
