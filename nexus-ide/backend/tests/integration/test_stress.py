"""Stress tests for NEXUS v3.0 subsystems."""
from __future__ import annotations

import asyncio

import pytest

from backend.orchestrator.agent_communication_bus import AgentCommunicationBus, AgentMessage
from backend.orchestrator.agent_topology import AgentEdge, AgentNode, AgentTopology
from backend.orchestrator.autonomous_execution_engine import AutonomousExecutionEngine
from backend.orchestrator.debate_visualizer import DebateVisualizer, Stance
from backend.orchestrator.neural_dashboard import AgentHealth, NeuralDashboard, SystemMetric


class TestStressCommunicationBus:
    def test_1000_messages(self):
        bus = AgentCommunicationBus(max_history=500)
        bus.subscribe("recv", lambda m: None)
        for i in range(1000):
            bus.send(AgentMessage(
                message_id=f"m-{i}", sender="a", recipient="recv",
                message_type="stress", payload={"seq": i},
            ))
        stats = bus.stats()
        assert stats["total_messages"] == 1000
        assert stats["history_size"] == 500

    def test_100_agents_broadcast(self):
        bus = AgentCommunicationBus()
        received_count = [0]

        def handler(m):
            received_count[0] += 1

        for _i in range(100):
            bus.subscribe_broadcast(handler)

        bus.send(AgentMessage(
            message_id="broadcast", sender="root", recipient="*",
            message_type="ping", payload={},
        ))
        assert received_count[0] == 100


class TestStressExecutionEngine:
    @pytest.mark.asyncio
    async def test_100_tasks_concurrent(self):
        engine = AutonomousExecutionEngine(max_concurrent=10)

        async def handler(x: int):
            await asyncio.sleep(0.01)
            return x * 2

        for i in range(100):
            engine.submit_task(f"task-{i}", handler, i)

        results = await engine.execute_all()
        assert len(results) == 100
        assert sum(1 for r in results if r.status.value == "completed") == 100


class TestStressTopology:
    def test_100_nodes_200_edges(self):
        topo = AgentTopology()
        for i in range(100):
            topo.add_node(AgentNode(f"a{i}", "team", f"Role-{i}"))

        for i in range(200):
            src = f"a{i % 100}"
            tgt = f"a{(i + 1) % 100}"
            topo.add_edge(AgentEdge(src, tgt, "connects"))

        assert topo.stats()["nodes"] == 100
        assert topo.stats()["edges"] == 200

        d = topo.to_dict()
        assert len(d["nodes"]) == 100
        assert len(d["edges"]) == 200


class TestStressDashboard:
    def test_1000_metric_readings(self):
        dash = NeuralDashboard()
        for i in range(1000):
            dash.record_metric(SystemMetric("cpu", float(i % 100), "%"))

        history = dash.get_metric_history("cpu", limit=100)
        assert len(history) == 100

    def test_100_agents_health(self):
        dash = NeuralDashboard()
        for i in range(100):
            status = ["healthy", "warning", "critical", "offline"][i % 4]
            dash.update_agent_health(AgentHealth(f"agent-{i}", status))

        overview = dash.get_system_overview()
        assert overview["agents"]["total"] == 100
        assert overview["agents"]["healthy"] == 25


class TestStressDebate:
    def test_100_arguments_10_rounds(self):
        viz = DebateVisualizer()
        viz.create_session("stress-debate", "Stress Test", ["a", "b"])

        for round_num in range(10):
            for arg_num in range(10):
                stance = [Stance.FOR, Stance.AGAINST][arg_num % 2]
                viz.add_argument("stress-debate", "a", stance, f"Arg {round_num}-{arg_num}")
            viz.complete_round("stress-debate")

        summary = viz.get_session("stress-debate").get_summary()
        assert summary["total_arguments"] == 100
        assert summary["rounds"] == 10
