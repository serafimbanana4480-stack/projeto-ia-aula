"""Integration tests for Debate Visualizer and Agent Topology."""
from __future__ import annotations

import pytest

from backend.orchestrator.debate_visualizer import DebateVisualizer, Stance
from backend.orchestrator.agent_topology import AgentTopology, AgentNode, AgentEdge


class TestDebateIntegration:
    def test_full_debate_session(self):
        viz = DebateVisualizer()
        viz.create_session("debate-1", "AI Safety", ["agent-a", "agent-b", "agent-c"])

        viz.add_argument("debate-1", "agent-a", Stance.FOR, "AI is safe", 0.8)
        viz.add_argument("debate-1", "agent-b", Stance.AGAINST, "AI is dangerous", 0.7)
        viz.complete_round("debate-1")

        viz.add_argument("debate-1", "agent-c", Stance.NEUTRAL, "Need more data", 0.5)
        viz.complete_round("debate-1")

        viz.complete_session("debate-1")

        summary = viz.get_session("debate-1").get_summary()
        assert summary["total_arguments"] == 3
        assert summary["rounds"] == 2
        assert summary["status"] == "completed"
        assert summary["stance_distribution"]["for"] == 1
        assert summary["stance_distribution"]["against"] == 1

    def test_live_state_updates(self):
        viz = DebateVisualizer()
        viz.create_session("live", "Topic", ["a", "b"])
        viz.add_argument("live", "a", Stance.FOR, "For")

        state = viz.get_live_state("live")
        assert state["current_round"] == 1
        assert state["arguments_in_current_round"] == 1
        assert state["status"] == "active"


class TestTopologyIntegration:
    def test_ceo_cto_dev_hierarchy(self):
        topo = AgentTopology()
        topo.add_node(AgentNode("ceo", "executive", "CEO"))
        topo.add_node(AgentNode("cto", "executive", "CTO"))
        topo.add_node(AgentNode("dev", "team", "Developer"))

        topo.add_edge(AgentEdge("ceo", "cto", "manages"))
        topo.add_edge(AgentEdge("cto", "dev", "supervises"))

        tree = topo.get_hierarchy("ceo")
        assert tree["id"] == "ceo"
        assert len(tree["children"]) == 1
        assert tree["children"][0]["id"] == "cto"
        assert len(tree["children"][0]["children"]) == 1
        assert tree["children"][0]["children"][0]["id"] == "dev"

    def test_bidirectional_neighbors(self):
        topo = AgentTopology()
        topo.add_node(AgentNode("a1", "exec", "CEO"))
        topo.add_node(AgentNode("a2", "exec", "CTO"))
        topo.add_node(AgentNode("a3", "team", "Dev"))
        topo.add_edge(AgentEdge("a1", "a2", "manages", bidirectional=True))
        topo.add_edge(AgentEdge("a2", "a3", "supervises", bidirectional=True))

        neighbors = topo.get_neighbors("a2")
        ids = {n.agent_id for n in neighbors}
        assert ids == {"a1", "a3"}

    def test_graph_export(self):
        topo = AgentTopology()
        topo.add_node(AgentNode("x", "type", "role"))
        topo.add_edge(AgentEdge("x", "y", "rel", weight=2.5))
        d = topo.to_dict()
        assert len(d["nodes"]) == 1
        assert len(d["edges"]) == 1
        assert d["edges"][0]["weight"] == 2.5

    def test_cycle_detection(self):
        topo = AgentTopology()
        topo.add_node(AgentNode("a", "exec", "CEO"))
        topo.add_node(AgentNode("b", "exec", "CTO"))
        topo.add_edge(AgentEdge("a", "b", "manages"))
        topo.add_edge(AgentEdge("b", "a", "reports_to"))  # cycle

        tree = topo.get_hierarchy("a")
        assert tree["id"] == "a"
        # Should detect cycle in children traversal
