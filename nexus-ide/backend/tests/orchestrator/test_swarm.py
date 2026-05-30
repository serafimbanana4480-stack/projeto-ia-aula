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


@pytest.fixture
def fake_registry():
    return {
        "CODER": FakeAgent("CODER"),
        "ANALYZER": FakeAgent("ANALYZER"),
        "DEBUGGER": FakeAgent("DEBUGGER"),
    }


class FakeLLM:
    pass


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
