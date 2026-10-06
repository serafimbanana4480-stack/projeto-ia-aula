"""Integration tests for agent communication via the bus."""
from __future__ import annotations

from backend.agents.ai_team.team_lead import AITeamLead
from backend.agents.executive.ceo_agent import CEOAgent
from backend.agents.executive.cto_agent import CTOAgent
from backend.agents.frontend.team_lead import FrontendTeamLead
from backend.orchestrator.agent_communication_bus import AgentCommunicationBus, AgentMessage


class TestAgentCommunicationBus:
    def test_direct_message_delivery(self):
        bus = AgentCommunicationBus()
        received = []

        def handler(msg):
            received.append(msg)

        bus.subscribe("agent-b", handler)
        msg = AgentMessage(
            message_id="m1", sender="agent-a", recipient="agent-b",
            message_type="query", payload={"q": "hello"},
        )
        assert bus.send(msg) is True
        assert len(received) == 1
        assert received[0].payload["q"] == "hello"

    def test_broadcast_reaches_multiple(self):
        bus = AgentCommunicationBus()
        received_a, received_b = [], []

        bus.subscribe_broadcast(lambda m: received_a.append(m))
        bus.subscribe_broadcast(lambda m: received_b.append(m))

        bus.send(AgentMessage(
            message_id="m2", sender="x", recipient="*",
            message_type="alert", payload={"level": "critical"},
        ))
        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_team_lead_routes_to_specialist(self):
        lead = FrontendTeamLead()
        status = lead.get_team_status()
        assert status["team"] == "frontend"
        assert "UIUX" in status["members"]
        assert "COMPONENT" in status["members"]
        assert "STATE_MANAGER" in status["members"]

    def test_ai_team_lead_coordination(self):
        lead = AITeamLead()
        status = lead.get_team_status()
        assert status["team"] == "ai"
        assert "ML_ENGINEER" in status["members"]
        assert "DATA_SCIENTIST" in status["members"]
        assert "PROMPT_ENGINEER" in status["members"]

    def test_ceo_cto_exist_and_have_names(self):
        ceo = CEOAgent()
        cto = CTOAgent()
        assert ceo.name == "CEO"
        assert cto.name == "CTO"

    def test_message_history_query(self):
        bus = AgentCommunicationBus()
        bus.subscribe("recv", lambda m: None)
        for i in range(5):
            bus.send(AgentMessage(
                message_id=f"m{i}", sender="a", recipient="recv",
                message_type="data", payload={"i": i},
            ))
        history = bus.get_history(sender="a", limit=3)
        assert len(history) == 3
        assert history[-1].payload["i"] == 4

    def test_concurrent_send_is_safe(self):
        bus = AgentCommunicationBus(max_history=100)
        bus.subscribe("recv", lambda m: None)
        import threading
        errors = []

        def sender(start):
            try:
                for i in range(50):
                    bus.send(AgentMessage(
                        message_id=f"t{start}-{i}", sender="a", recipient="recv",
                        message_type="test", payload={"i": i},
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=sender, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert bus.stats()["total_messages"] == 200
