"""Tests for AgentAllocator."""
from unittest.mock import MagicMock

import pytest

from backend.orchestrator.allocator import AgentAllocator


@pytest.fixture
def mock_registry() -> dict[str, MagicMock]:
    agents = {
        "ARCHITECT": MagicMock(name="ARCHITECT"),
        "CODER": MagicMock(name="CODER"),
        "DEBUGGER": MagicMock(name="DEBUGGER"),
        "ANALYZER": MagicMock(name="ANALYZER"),
        "OPTIMIZER": MagicMock(name="OPTIMIZER"),
    }
    return agents


class TestAgentAllocator:
    def test_score_code_generation(self, mock_registry: dict) -> None:
        allocator = AgentAllocator(mock_registry)
        scores = allocator.score_agents("code_generation")
        assert len(scores) >= 1
        assert scores[0].agent_name == "CODER"

    def test_score_design(self, mock_registry: dict) -> None:
        allocator = AgentAllocator(mock_registry)
        scores = allocator.score_agents("design")
        assert scores[0].agent_name == "ARCHITECT"

    def test_score_unknown_fallback(self, mock_registry: dict) -> None:
        allocator = AgentAllocator(mock_registry)
        scores = allocator.score_agents("unknown_task")
        assert len(scores) == 1
        assert scores[0].agent_name == "CODER"

    def test_fallback_chain(self, mock_registry: dict) -> None:
        allocator = AgentAllocator(mock_registry)
        chain = allocator.get_fallback_chain("debugging")
        assert "DEBUGGER" in chain

    def test_allocate_missing_agent(self, mock_registry: dict) -> None:
        # Remove CODER to force failure
        registry = {k: v for k, v in mock_registry.items() if k != "CODER"}
        allocator = AgentAllocator(registry)
        scores = allocator.score_agents("unknown_task")
        assert len(scores) == 0  # No fallback available
