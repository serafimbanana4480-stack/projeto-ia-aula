"""Tests for backend.tools.task_spawner — dynamic task spawning."""

from __future__ import annotations

import pytest

from backend.tools.task_spawner import spawn_task


class _StubLifecycle:
    """Minimal agent lifecycle: aceita o spawn e devolve um instance_id."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return "inst-stub-1"


@pytest.fixture
def stub_lifecycle(monkeypatch: pytest.MonkeyPatch) -> _StubLifecycle:
    from backend.orchestrator.main import app

    stub = _StubLifecycle()
    monkeypatch.setattr(app.state, "agent_lifecycle", stub, raising=False)
    return stub


class TestSpawnTask:
    """Test the spawn_task function."""

    @pytest.mark.asyncio
    async def test_spawn_task_returns_valid_dict(
        self, stub_lifecycle: _StubLifecycle
    ) -> None:
        """Test that spawn_task returns a valid dict structure."""
        result = await spawn_task(
            name="test_task",
            description="Test description",
            agent="CODER",
            priority="medium",
            definition_of_done="ficheiro criado e teste a passar",
            session_id="s-spawn-ok",
        )
        assert isinstance(result, dict)
        assert result["status"] == "spawned"
        assert result["task_name"] == "test_task"
        assert result["agent"] == "CODER"
        assert result["priority"] == "medium"
        assert result["description"] == "Test description"
        assert result["instance_id"] == "inst-stub-1"
        assert stub_lifecycle.calls, "lifecycle deve receber o spawn"

    @pytest.mark.asyncio
    async def test_spawn_task_with_minimal_params(
        self, stub_lifecycle: _StubLifecycle
    ) -> None:
        """Test that spawn_task works with only required params."""
        result = await spawn_task(
            name="minimal_task",
            description="Minimal description",
            definition_of_done="critério objetivo cumprido",
            session_id="s-spawn-min",
        )
        assert result["status"] == "spawned"
        assert result["task_name"] == "minimal_task"
        assert result["agent"] == "CODER"  # default
        assert result["priority"] == "medium"  # default
        assert result["depends_on"] == []  # default

    @pytest.mark.asyncio
    async def test_spawn_task_with_dependencies(self) -> None:
        """Test that spawn_task accepts and returns dependencies."""
        deps = ["task_1", "task_2"]
        result = await spawn_task(
            name="dependent_task",
            description="Task with dependencies",
            depends_on=deps,
        )
        assert result["depends_on"] == deps
        assert len(result["depends_on"]) == 2

    @pytest.mark.asyncio
    async def test_spawn_task_with_parent_id(self) -> None:
        """Test that spawn_task accepts and returns parent_id."""
        result = await spawn_task(
            name="child_task",
            description="Child task",
            parent_id="parent_phase_1",
        )
        assert result["parent_id"] == "parent_phase_1"

    @pytest.mark.asyncio
    async def test_spawn_task_with_context(self) -> None:
        """Test that spawn_task accepts and returns context."""
        context = "This task requires access to the database schema."
        result = await spawn_task(
            name="contextual_task",
            description="Task with context",
            context=context,
        )
        assert result["context"] == context

    # TODO: Add these tests when real implementation is done:
    # - test_spawn_task_validates_agent_in_registry
    # - test_spawn_task_emits_event_on_eventbus
    # - test_spawn_task_invalid_agent_raises_error
    # - test_spawn_task_invalid_priority_raises_error
