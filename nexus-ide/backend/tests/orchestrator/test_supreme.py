"""Tests for SupremeOrchestrator."""
from unittest.mock import AsyncMock, MagicMock
import asyncio

import pytest

from backend.orchestrator.supreme import SupremeOrchestrator
from backend.orchestrator.decomposer import UserStory, StoryPriority
from backend.agents.base import AgentRequest


class TestSupremeOrchestrator:
    @pytest.mark.asyncio
    async def test_orchestrate_mock(self) -> None:
        registry = {
            "CODER": MagicMock(),
            "ARCHITECT": MagicMock(),
        }

        decomposer = MagicMock()
        decomposer.decompose = AsyncMock(return_value=[
            UserStory(title="API", description="Build API", assigned_agent="coder", priority=StoryPriority.HIGH),
            UserStory(title="Tests", description="Write tests", assigned_agent="tester", priority=StoryPriority.MEDIUM),
        ])

        allocator = MagicMock()
        allocator.allocate = AsyncMock(return_value=MagicMock())

        supreme = SupremeOrchestrator(
            registry=registry,
            decomposer=decomposer,
            allocator=allocator,
        )

        result = await supreme.orchestrate("Build a todo app")

        assert result["status"] in ("completed", "failed")
        assert "workflow_id" in result
        assert result["stories_executed"] == 2

        await supreme.stop()

    @pytest.mark.asyncio
    async def test_no_stories(self) -> None:
        registry = {"CODER": MagicMock()}
        decomposer = MagicMock()
        decomposer.decompose = AsyncMock(return_value=[])

        supreme = SupremeOrchestrator(
            registry=registry,
            decomposer=decomposer,
        )

        result = await supreme.orchestrate("Do nothing")
        assert result["status"] == "completed"
        assert result["stories_executed"] == 0

        await supreme.stop()

    @pytest.mark.asyncio
    async def test_agent_timeout(self) -> None:
        """Test that agent execution times out after configured timeout."""
        # Create a mock agent that never completes
        async def slow_run(request: AgentRequest):
            while True:
                await asyncio.sleep(0.1)
                yield "working..."
        
        agent = MagicMock()
        agent.name = "SLOW_AGENT"
        agent.run = slow_run

        registry = {"SLOW_AGENT": agent}
        
        decomposer = MagicMock()
        decomposer.decompose = AsyncMock(return_value=[
            UserStory(title="Slow Task", description="This will timeout", 
                     assigned_agent="slow_agent", priority=StoryPriority.HIGH),
        ])

        allocator = MagicMock()
        allocator.get_fallback_chain = MagicMock(return_value=[])

        pool = MagicMock()
        pool.acquire = AsyncMock()
        pool.release = AsyncMock()

        supreme = SupremeOrchestrator(
            registry=registry,
            decomposer=decomposer,
            allocator=allocator,
            agent_pool=pool,
            agent_timeout=1.0,  # 1 second timeout
        )

        result = await supreme.orchestrate("Test timeout")
        
        assert result["status"] == "failed"
        assert "timed out" in result["results"][0].get("error", "").lower()
        assert result["stories_executed"] == 1

        await supreme.stop()

    @pytest.mark.asyncio
    async def test_agent_execution_success(self) -> None:
        """Test that agent execution succeeds when agent completes within timeout."""
        # Create a mock agent that completes quickly
        async def fast_run(request: AgentRequest):
            yield "Task completed successfully"
        
        agent = MagicMock()
        agent.name = "FAST_AGENT"
        agent.run = fast_run

        registry = {"FAST_AGENT": agent}
        
        decomposer = MagicMock()
        decomposer.decompose = AsyncMock(return_value=[
            UserStory(title="Fast Task", description="This will complete", 
                     assigned_agent="fast_agent", priority=StoryPriority.HIGH),
        ])

        allocator = MagicMock()
        allocator.get_fallback_chain = MagicMock(return_value=[])

        pool = MagicMock()
        pool.acquire = AsyncMock()
        pool.release = AsyncMock()

        supreme = SupremeOrchestrator(
            registry=registry,
            decomposer=decomposer,
            allocator=allocator,
            agent_pool=pool,
            agent_timeout=10.0,  # 10 second timeout
        )

        result = await supreme.orchestrate("Test success")
        
        assert result["status"] == "completed"
        assert result["results"][0]["status"] == "completed"
        assert result["stories_executed"] == 1

        await supreme.stop()

    @pytest.mark.asyncio
    async def test_agent_execution_error_handling(self) -> None:
        """Test that agent execution errors are caught and logged appropriately."""
        # Create a mock agent that raises an exception
        async def failing_run(request: AgentRequest):
            raise ValueError("Agent execution failed")
            yield "This should never be reached"
        
        agent = MagicMock()
        agent.name = "FAILING_AGENT"
        agent.run = failing_run

        registry = {"FAILING_AGENT": agent}
        
        decomposer = MagicMock()
        decomposer.decompose = AsyncMock(return_value=[
            UserStory(title="Failing Task", description="This will fail", 
                     assigned_agent="failing_agent", priority=StoryPriority.HIGH),
        ])

        allocator = MagicMock()
        allocator.get_fallback_chain = MagicMock(return_value=[])

        pool = MagicMock()
        pool.acquire = AsyncMock()
        pool.release = AsyncMock()

        supreme = SupremeOrchestrator(
            registry=registry,
            decomposer=decomposer,
            allocator=allocator,
            agent_pool=pool,
        )

        result = await supreme.orchestrate("Test error handling")
        
        assert result["status"] == "failed"
        assert result["results"][0]["status"] == "failed"
        assert "Agent execution failed" in result["results"][0]["error"]
        assert result["stories_executed"] == 1

        await supreme.stop()
