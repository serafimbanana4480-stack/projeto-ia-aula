"""Security and robustness integration tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.orchestrator.agent_communication_bus import AgentCommunicationBus, AgentMessage
from backend.orchestrator.self_improvement_loop import SelfImprovementLoop, PerformanceMetric
from backend.orchestrator.agent_topology import AgentTopology, AgentNode, AgentEdge


class TestSecurityRobustness:
    def test_bus_message_id_unique(self):
        bus = AgentCommunicationBus()
        ids = set()
        for i in range(100):
            msg = AgentMessage(
                message_id=f"msg-{i}-{hash(str(i))}",
                sender="a", recipient="b", message_type="test", payload={},
            )
            bus.send(msg)
            ids.add(msg.message_id)
        assert len(ids) == 100

    def test_improvement_metric_direction(self):
        loop = SelfImprovementLoop()
        # Higher is better metric (accuracy) — below threshold = problem
        loop.record_metric(PerformanceMetric("accuracy", 0.6, threshold=0.9, higher_is_better=True))
        opps = loop.analyze()
        assert len(opps) == 1
        assert opps[0]["metric"] == "accuracy"

        # Lower is better metric (error_rate) — BELOW threshold = good, no problem
        loop2 = SelfImprovementLoop()
        loop2.record_metric(PerformanceMetric("error_rate", 0.05, threshold=0.1, higher_is_better=False))
        opps2 = loop2.analyze()
        assert len(opps2) == 0  # 0.05 < 0.1 is GOOD for error_rate

        # Lower is better metric ABOVE threshold = problem
        loop3 = SelfImprovementLoop()
        loop3.record_metric(PerformanceMetric("error_rate", 0.15, threshold=0.1, higher_is_better=False))
        opps3 = loop3.analyze()
        assert len(opps3) == 1
        assert opps3[0]["metric"] == "error_rate"

    def test_topology_cycle_not_infinite(self):
        topo = AgentTopology()
        topo.add_node(AgentNode("a", "exec", "CEO"))
        topo.add_node(AgentNode("b", "exec", "CTO"))
        topo.add_edge(AgentEdge("a", "b", "manages"))
        topo.add_edge(AgentEdge("b", "a", "reports_to"))

        tree = topo.get_hierarchy("a")
        assert tree["id"] == "a"
        # Should not infinite loop

    def test_bus_concurrent_access_no_corruption(self):
        bus = AgentCommunicationBus(max_history=50)
        bus.subscribe("recv", lambda m: None)

        import threading
        errors = []

        def flood():
            try:
                for i in range(100):
                    bus.send(AgentMessage(
                        message_id=f"x-{i}", sender="a", recipient="recv",
                        message_type="flood", payload={"i": i},
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=flood) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        stats = bus.stats()
        assert stats["total_messages"] == 1000
        assert stats["history_size"] == 50  # max_history enforced

    def test_empty_debate_session(self):
        from backend.orchestrator.debate_visualizer import DebateVisualizer
        viz = DebateVisualizer()
        viz.create_session("empty", "Topic", ["a"])
        summary = viz.get_session("empty").get_summary()
        assert summary["total_arguments"] == 0
        assert summary["rounds"] == 0

    @pytest.mark.asyncio
    async def test_execution_engine_empty(self):
        from backend.orchestrator.autonomous_execution_engine import AutonomousExecutionEngine
        engine = AutonomousExecutionEngine()
        result = await engine.execute_all()
        assert result == []
        assert engine.stats()["total"] == 0
