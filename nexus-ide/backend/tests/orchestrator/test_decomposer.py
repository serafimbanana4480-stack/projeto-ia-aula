"""Tests for GoalDecomposer."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.orchestrator.decomposer import (
    GoalDecomposer,
    StoryPriority,
    UserStory,
)


class TestGoalDecomposer:
    @pytest.fixture
    def mock_client(self) -> MagicMock:
        client = MagicMock()
        response = MagicMock()
        response.content = """{"stories": [
            {"title": "Design schema", "description": "Create DB schema", "acceptance_criteria": ["Schema is documented"], "priority": "critical", "estimated_effort": "2h", "assigned_agent": "architect"},
            {"title": "Implement API", "description": "Create REST endpoints", "acceptance_criteria": ["Endpoints return 200"], "priority": "high", "estimated_effort": "4h", "assigned_agent": "coder"}
        ]}"""
        client.chat = AsyncMock(return_value=response)
        return client

    @pytest.mark.asyncio
    async def test_decompose_creates_stories(self, mock_client: MagicMock) -> None:
        decomposer = GoalDecomposer(ollama_client=mock_client)
        stories = await decomposer.decompose("Create a user API")

        assert len(stories) == 2
        assert stories[0].title == "Design schema"
        assert stories[0].priority == StoryPriority.CRITICAL
        assert stories[1].assigned_agent == "coder"

    def test_parse_stories_json(self) -> None:
        decomposer = GoalDecomposer()
        content = '{"stories": [{"title": "Test", "priority": "high", "acceptance_criteria": ["A"], "assigned_agent": "tester"}]}'
        stories = decomposer._parse_stories(content)

        assert len(stories) == 1
        assert stories[0].title == "Test"
        assert stories[0].priority == StoryPriority.HIGH

    def test_build_dependency_graph(self) -> None:
        decomposer = GoalDecomposer()
        stories = [
            UserStory(story_id="s1", title="A", dependencies=[]),
            UserStory(story_id="s2", title="B", dependencies=["s1"]),
            UserStory(story_id="s3", title="C", dependencies=["s1", "s2"]),
        ]
        graph = decomposer.build_dependency_graph(stories)

        assert graph["s1"] == []
        assert graph["s2"] == ["s1"]
        assert graph["s3"] == ["s1", "s2"]

    def test_story_to_dict(self) -> None:
        story = UserStory(
            title="Test",
            description="Desc",
            priority=StoryPriority.HIGH,
            acceptance_criteria=["A"],
        )
        d = story.to_dict()
        assert d["title"] == "Test"
        assert d["priority"] == "high"
