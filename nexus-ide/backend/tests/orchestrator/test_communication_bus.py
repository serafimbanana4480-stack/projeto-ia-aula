
from backend.orchestrator.agent_communication_bus import (
    AgentCommunicationBus,
    AgentMessage,
)


def test_send_direct_message():
    bus = AgentCommunicationBus()
    received = []

    def handler(msg):
        received.append(msg)

    bus.subscribe("agent-b", handler)
    msg = AgentMessage(
        message_id="msg-1",
        sender="agent-a",
        recipient="agent-b",
        message_type="query",
        payload={"q": "hello"},
    )
    delivered = bus.send(msg)
    assert delivered is True
    assert len(received) == 1
    assert received[0].sender == "agent-a"
    assert received[0].payload["q"] == "hello"


def test_send_broadcast():
    bus = AgentCommunicationBus()
    received = []

    def handler(msg):
        received.append(msg)

    bus.subscribe_broadcast(handler)
    msg = AgentMessage(
        message_id="msg-2",
        sender="agent-a",
        recipient="*",
        message_type="announcement",
        payload={"text": "hello all"},
    )
    delivered = bus.send(msg)
    assert delivered is True
    assert len(received) == 1
    assert received[0].payload["text"] == "hello all"


def test_send_to_unknown_recipient():
    bus = AgentCommunicationBus()
    msg = AgentMessage(
        message_id="msg-3",
        sender="agent-a",
        recipient="unknown",
        message_type="query",
        payload={},
    )
    delivered = bus.send(msg)
    assert delivered is False


def test_message_history():
    bus = AgentCommunicationBus()
    bus.subscribe("recv", lambda m: None)

    for i in range(5):
        bus.send(
            AgentMessage(
                message_id=f"msg-{i}",
                sender="a",
                recipient="recv",
                message_type="data",
                payload={"i": i},
            )
        )

    history = bus.get_history(sender="a", limit=3)
    assert len(history) == 3
    assert history[-1].payload["i"] == 4

    typed = bus.get_history(message_type="data")
    assert len(typed) == 5


def test_stats():
    bus = AgentCommunicationBus()
    bus.subscribe("x", lambda m: None)
    bus.send(
        AgentMessage(
            message_id="m1",
            sender="a",
            recipient="x",
            message_type="t",
            payload={},
        )
    )
    stats = bus.stats()
    assert stats["total_messages"] == 1
    assert stats["subscribers"] == 1
