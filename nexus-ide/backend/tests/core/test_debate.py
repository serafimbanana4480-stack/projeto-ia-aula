"""Tests for the Debate system."""

from __future__ import annotations

import pytest

from backend.core.debate import (
    AgentOpinion,
    DebateResult,
    DebateSession,
    get_debate_result,
    run_debate,
)


class TestDebate:
    @pytest.mark.asyncio
    async def test_consensus_debate(self):
        opinions = [
            AgentOpinion(agent_name="A", position="Use FastAPI", arguments=["async"]),
            AgentOpinion(agent_name="B", position="Use FastAPI", arguments=["fast"]),
        ]
        result = await run_debate("Framework?", opinions, max_rounds=3)
        assert result.consensus_reached is True
        assert result.winning_position == "Use FastAPI"
        assert result.meta_decision == ""
        assert len(result.rounds) == 3

    @pytest.mark.asyncio
    async def test_split_debate_meta_decision(self):
        opinions = [
            AgentOpinion(agent_name="A", position="SQLAlchemy", arguments=["orm"]),
            AgentOpinion(agent_name="B", position="Raw SQL", arguments=["speed"]),
            AgentOpinion(agent_name="C", position="SQLAlchemy", arguments=["maintainable"]),
        ]
        result = await run_debate("ORM?", opinions, max_rounds=3)
        assert result.consensus_reached is False
        assert result.winning_position == "SQLAlchemy"
        assert "META_ANALYZER decides" in result.meta_decision
        assert len(result.dissenting_positions) == 1
        assert result.dissenting_positions[0].agent_name == "B"

    @pytest.mark.asyncio
    async def test_debate_registry(self):
        opinions = [
            AgentOpinion(agent_name="A", position="X", arguments=[]),
        ]
        result = await run_debate("Topic", opinions)
        fetched = get_debate_result(result.debate_id)
        assert fetched is not None
        assert fetched.debate_id == result.debate_id

    @pytest.mark.asyncio
    async def test_debate_session_run(self):
        session = DebateSession(
            topic="Architecture",
            opinions=[
                AgentOpinion(agent_name="ARCH", position="Monolith", arguments=["simple"]),
                AgentOpinion(agent_name="DEV", position="Microservices", arguments=["scale"]),
            ],
            max_rounds=3,
        )
        result = await session.run()
        assert isinstance(result, DebateResult)
        assert result.topic == "Architecture"
        assert len(result.rounds) == 3
        # Round 2 should have response arguments
        assert any("Response to" in arg for arg in result.rounds[1].opinions[0].arguments)
        # Round 3 should have compromise arguments
        assert any("Compromise" in arg for arg in result.rounds[2].opinions[0].arguments)

    def test_get_debate_result_missing(self):
        assert get_debate_result("nonexistent") is None
