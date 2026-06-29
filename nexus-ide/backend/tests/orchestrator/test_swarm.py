"""Tests for SwarmOrchestrator."""

from __future__ import annotations

import pytest

from backend.orchestrator.swarm import SwarmOrchestrator, SwarmResult


class FakeAgent:
    def __init__(self, name: str):
        self.name = name

    async def run(self, request):
        for token in [f"[{self.name}]", " result"]:
            yield token


class FakeLLM:
    """Fake LLM client that returns a simple synthesis."""

    async def chat_complete(self, model, messages, options=None):
        return "Synthesised answer from swarm."

    async def chat_stream(self, model, messages, options=None):
        yield "stream token"


@pytest.fixture
def fake_registry():
    return {
        "CODER": FakeAgent("CODER"),
        "ANALYZER": FakeAgent("ANALYZER"),
        "DEBUGGER": FakeAgent("DEBUGGER"),
    }


@pytest.mark.asyncio
async def test_swarm_divide(fake_registry):
    swarm = SwarmOrchestrator(FakeLLM(), fake_registry, None, max_agents=3)
    result = await swarm.execute_swarm(
        objective="Write a function",
        session_id="test-1",
        agents=["CODER", "ANALYZER"],
        strategy="divide",
    )
    assert isinstance(result, SwarmResult)
    assert result.strategy_used == "divide"
    assert len(result.agent_results) > 0
    assert result.confidence > 0
    # With fake agents the subtask planner returns raw tokens, so the final
    # answer may be the single agent output. Just ensure a non-empty answer.
    assert result.final_answer.strip()


@pytest.mark.asyncio
async def test_swarm_ensemble(fake_registry):
    swarm = SwarmOrchestrator(FakeLLM(), fake_registry, None, max_agents=3)
    result = await swarm.execute_swarm(
        objective="Review code",
        session_id="test-2",
        agents=["CODER", "ANALYZER"],
        strategy="ensemble",
    )
    assert isinstance(result, SwarmResult)
    assert result.strategy_used == "ensemble"
    assert len(result.agent_results) == 2


@pytest.mark.asyncio
async def test_swarm_pipeline(fake_registry):
    swarm = SwarmOrchestrator(FakeLLM(), fake_registry, None, max_agents=3)
    result = await swarm.execute_swarm(
        objective="Build feature",
        session_id="test-3",
        agents=["CODER", "DEBUGGER"],
        strategy="pipeline",
    )
    assert isinstance(result, SwarmResult)
    assert result.strategy_used == "pipeline"
    assert len(result.agent_results) <= 2


@pytest.mark.asyncio
async def test_swarm_debate(fake_registry):
    swarm = SwarmOrchestrator(FakeLLM(), fake_registry, None, max_agents=3)
    result = await swarm.execute_swarm(
        objective="Best approach",
        session_id="test-4",
        agents=["CODER", "ANALYZER"],
        strategy="debate",
    )
    assert isinstance(result, SwarmResult)
    assert result.strategy_used == "debate"


@pytest.mark.asyncio
async def test_swarm_no_valid_agents():
    swarm = SwarmOrchestrator(FakeLLM(), {}, None, max_agents=3)
    result = await swarm.execute_swarm(
        objective="Any task",
        session_id="test-5",
        agents=["MISSING"],
        strategy="divide",
    )
    assert isinstance(result, SwarmResult)
    assert result.confidence == 0.0
    assert "No valid agents" in result.final_answer


@pytest.mark.asyncio
async def test_swarm_adaptive_selects_strategy(fake_registry):
    swarm = SwarmOrchestrator(FakeLLM(), fake_registry, None, max_agents=3)
    result = await swarm.execute_swarm(
        objective="Compare REST vs GraphQL for our API",
        session_id="test-adaptive",
        agents=["CODER", "ANALYZER"],
        strategy="adaptive",
    )
    assert isinstance(result, SwarmResult)
    assert result.strategy_used == "debate"


def test_pick_agent_for_task():
    swarm = SwarmOrchestrator(FakeLLM(), {}, None, max_agents=3)
    assert swarm._pick_agent_for_task("Implement the auth module", ["CODER", "ANALYZER"]) == "CODER"
    assert (
        swarm._pick_agent_for_task("Security audit and code review", ["CODER", "ANALYZER"])
        == "ANALYZER"
    )
    assert swarm._pick_agent_for_task("Debug the failing test", ["CODER", "DEBUGGER"]) == "DEBUGGER"
