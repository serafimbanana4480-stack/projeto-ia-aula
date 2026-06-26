"""Tests for reputation-aware AgentAllocator."""
from __future__ import annotations

import pytest

from backend.agents.base import AgentBase
from backend.orchestrator.allocator import AgentAllocator, AgentScore
from backend.pipeline.rl_optimizer import AgentReputationSystem, AgentReputationTier


class FakeAgent(AgentBase):
    """Minimal agent stub for testing."""

    def __init__(self, name: str, supported_stacks: list[str] | None = None):
        super().__init__()
        self._name = name
        self.supported_stacks = supported_stacks or []

    @property
    def name(self) -> str:
        return self._name

    async def run(self, request: object) -> object:
        return iter([])

    async def execute(self, task: dict) -> dict:
        return {"status": "ok"}


class TestReputationAwareAllocator:
    """Tests for AgentAllocator with reputation integration."""

    @pytest.fixture
    def registry(self):
        return {
            "ARCHITECT": FakeAgent("ARCHITECT", ["python", "typescript"]),
            "CODER": FakeAgent("CODER", ["python", "go"]),
            "DEBUGGER": FakeAgent("DEBUGGER"),
            "ANALYZER": FakeAgent("ANALYZER"),
            "RESEARCHER": FakeAgent("RESEARCHER"),
            "DOCUMENTER": FakeAgent("DOCUMENTER"),
            "OPTIMIZER": FakeAgent("OPTIMIZER"),
            "MICRO": FakeAgent("MICRO"),
        }

    @pytest.fixture
    def reputation(self):
        rep = AgentReputationSystem()
        rep.register("CODER", "backend")
        rep.register("ARCHITECT", "backend")
        rep.register("DEBUGGER", "qa")
        return rep

    def test_allocator_without_reputation(self, registry):
        allocator = AgentAllocator(registry)
        scores = allocator.score_agents("code_generation")
        assert len(scores) > 0
        assert all(isinstance(s, AgentScore) for s in scores)

    def test_allocator_with_reputation(self, registry, reputation):
        # Make CODER an expert
        coder = reputation.get("CODER")
        for _ in range(20):
            coder.record_success()
        assert coder.reputation_tier == AgentReputationTier.EXPERT

        allocator = AgentAllocator(registry, reputation_system=reputation)
        scores = allocator.score_agents("code_generation")
        assert len(scores) > 0

        # CODER should be top with expert multiplier
        coder_score = next(s for s in scores if s.agent_name == "CODER")
        assert coder_score.score >= 0.8  # boosted

    def test_reputation_multipliers(self, registry, reputation):
        # Set up agents at different tiers
        coder = reputation.get("CODER")
        for _ in range(20):
            coder.record_success()  # EXPERT (>=95%)

        architect = reputation.get("ARCHITECT")
        for _ in range(10):
            architect.record_success()
        for _ in range(2):
            architect.record_failure()  # RELIABLE (>=80%, <95%)

        allocator = AgentAllocator(registry, reputation_system=reputation)
        scores = allocator.score_agents("design")

        architect_score = next(s for s in scores if s.agent_name == "ARCHITECT")
        assert architect_score.score > 0.5

    def test_deprecated_agent_penalized(self, registry, reputation):
        coder = reputation.get("CODER")
        for _ in range(10):
            coder.record_failure()  # DEPRECATED (<50%)

        allocator = AgentAllocator(registry, reputation_system=reputation)
        scores = allocator.score_agents("code_generation")
        coder_score = next(s for s in scores if s.agent_name == "CODER")
        assert coder_score.score < 0.5  # penalized

    def test_fallback_when_no_candidates(self, registry):
        allocator = AgentAllocator(registry)
        chain = allocator.get_fallback_chain("nonexistent_task")
        # Should fall back to CODER
        assert len(chain) > 0
        assert "CODER" in chain

    def test_score_agents_stack_preference(self, registry):
        allocator = AgentAllocator(registry)
        scores_python = allocator.score_agents("design", stack="python")
        scores_go = allocator.score_agents("design", stack="go")

        architect_python = next(s for s in scores_python if s.agent_name == "ARCHITECT")
        architect_go = next(s for s in scores_go if s.agent_name == "ARCHITECT")

        # ARCHITECT supports both python and typescript, but not go
        # So python should have stack bonus
        assert "stack match" in architect_python.reason

    def test_get_fallback_chain(self, registry):
        allocator = AgentAllocator(registry)
        chain = allocator.get_fallback_chain("code_generation")
        assert isinstance(chain, list)
        assert len(chain) > 0