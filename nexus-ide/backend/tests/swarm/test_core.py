"""Unit tests for the SWARM core types and message bus."""

from __future__ import annotations

import asyncio

import pytest

from backend.swarm.communication.message_bus import MessageBus
from backend.swarm.core.types import (
    AgentMessage,
    OperationalMode,
    Proposal,
    QualityScores,
    SwarmResult,
    SwarmStrategy,
    WorkflowState,
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


def test_quality_scores_default_gate_fails() -> None:
    s = QualityScores()
    assert not s.gate()


def test_quality_scores_gate_passes_when_balanced() -> None:
    s = QualityScores(quality=0.8, confidence=0.7, risk=0.2, complexity=0.3)
    assert s.gate()
    assert s.to_dict() == {
        "quality": 0.8,
        "confidence": 0.7,
        "risk": 0.2,
        "complexity": 0.3,
    }


def test_proposal_to_dict_includes_state_and_scores() -> None:
    p = Proposal(
        title="Fix login",
        description="The login endpoint returns 500 on empty body",
        rationale="Missing input validation",
        files_to_change=[{"path": "auth/login.py", "change": "add validation"}],
        evidence_refs=["auth/login.py:42-58"],
    )
    d = p.to_dict()
    assert d["title"] == "Fix login"
    assert d["state"] == WorkflowState.PROPOSED.value
    assert d["evidence_refs"] == ["auth/login.py:42-58"]
    assert d["scores"]["quality"] >= 0.0


def test_swarm_result_to_dict_drops_full_messages() -> None:
    """`SwarmResult.to_dict()` only summarises messages (full list in memory)."""
    r = SwarmResult(
        run_id="abc",
        mode=OperationalMode.ARCHITECTURE,
        strategy=SwarmStrategy.ENSEMBLE,
        objective="design an API",
    )
    r.messages = [AgentMessage(sender="COORDINATOR", content="hi")] * 3
    d = r.to_dict()
    assert d["message_count"] == 3
    assert "messages" not in d  # not serialised to keep the payload small


# ---------------------------------------------------------------------------
# Message bus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_bus_persists_history() -> None:
    bus = MessageBus()
    msg = AgentMessage(sender="COORDINATOR", recipient="*", content="hello")
    await bus.publish(msg)
    assert len(bus.all_history()) == 1
    assert bus.history()[0].content == "hello"


@pytest.mark.asyncio
async def test_message_bus_topic_filter() -> None:
    bus = MessageBus()
    await bus.publish(AgentMessage(sender="COORDINATOR", recipient="ARCHITECT", content="A"))
    await bus.publish(AgentMessage(sender="COORDINATOR", recipient="CODER", content="C"))
    by_recipient = bus.history(recipient="ARCHITECT")
    assert len(by_recipient) == 1
    assert by_recipient[0].content == "A"


@pytest.mark.asyncio
async def test_message_bus_request_response() -> None:
    bus = MessageBus()

    async def responder() -> None:
        # wait for a request, then reply
        async for msg in bus.subscribe("type:request"):
            await bus.respond(sender="ARCHITECT", in_reply_to=msg, content="ok")
            break

    task = asyncio.create_task(responder())
    await asyncio.sleep(0.05)
    reply = await bus.request_response(
        sender="COORDINATOR",
        recipient="ARCHITECT",
        content="please",
        timeout=2.0,
    )
    await task
    assert reply.content == "ok"
    assert reply.sender == "ARCHITECT"
