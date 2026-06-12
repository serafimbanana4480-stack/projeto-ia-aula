"""Tests for the Multi-Agent Orchestration Engine.

Covers:
- Dependency graph construction and validation
- Topological sorting and parallel layer computation
- Task execution with retry logic
- Event bus pub/sub
- Plan creation and parsing
- Cancellation
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskStatus,
)
from backend.orchestrator.engine import (
    ExecutionContext,
    OrchestrationEngine,
    OrchestrationState,
)
from backend.orchestrator.events import (
    EventBus,
    EventEmitter,
    EventType,
    OrchestratorEvent,
)

# ---------------------------------------------------------------------------
# Dependency Graph Tests
# ---------------------------------------------------------------------------


class TestDependencyGraph:
    def test_add_task(self) -> None:
        graph = DependencyGraph()
        task = TaskNode(name="Test", description="A test task", agent="CODER")
        graph.add_task(task)
        assert graph.get_task(task.task_id) is not None
        assert len(graph.get_all_tasks()) == 1

    def test_add_duplicate_task_raises(self) -> None:
        graph = DependencyGraph()
        task = TaskNode(name="Test")
        graph.add_task(task)
        with pytest.raises(ValueError, match="Duplicate"):
            graph.add_task(task)

    def test_add_dependency(self) -> None:
        graph = DependencyGraph()
        t1 = TaskNode(name="Task 1")
        t2 = TaskNode(name="Task 2")
        graph.add_task(t1)
        graph.add_task(t2)
        graph.add_dependency(t1.task_id, t2.task_id)
        assert t1.task_id in t2.depends_on
        assert t2.task_id in t1.required_by

    def test_validate_acyclic(self) -> None:
        graph = DependencyGraph()
        t1 = TaskNode(name="T1")
        t2 = TaskNode(name="T2")
        t3 = TaskNode(name="T3")
        graph.add_task(t1)
        graph.add_task(t2)
        graph.add_task(t3)
        graph.add_dependency(t1.task_id, t2.task_id)
        graph.add_dependency(t2.task_id, t3.task_id)
        valid, msg = graph.validate()
        assert valid, msg

    def test_validate_cycle_detected(self) -> None:
        graph = DependencyGraph()
        t1 = TaskNode(name="T1")
        t2 = TaskNode(name="T2")
        graph.add_task(t1)
        graph.add_task(t2)
        graph.add_dependency(t1.task_id, t2.task_id)
        graph.add_dependency(t2.task_id, t1.task_id)
        valid, msg = graph.validate()
        assert not valid
        assert "cycle" in msg.lower()

    def test_validate_empty_graph(self) -> None:
        graph = DependencyGraph()
        valid, msg = graph.validate()
        assert not valid
        assert "empty" in msg.lower()

    def test_topological_layers_linear(self) -> None:
        graph = DependencyGraph()
        t1 = TaskNode(name="T1")
        t2 = TaskNode(name="T2")
        t3 = TaskNode(name="T3")
        graph.add_task(t1)
        graph.add_task(t2)
        graph.add_task(t3)
        graph.add_dependency(t1.task_id, t2.task_id)
        graph.add_dependency(t2.task_id, t3.task_id)
        layers = graph.topological_layers()
        assert len(layers) == 3
        assert layers[0] == [t1.task_id]
        assert layers[1] == [t2.task_id]
        assert layers[2] == [t3.task_id]

    def test_topological_layers_parallel(self) -> None:
        graph = DependencyGraph()
        t1 = TaskNode(name="T1")
        t2 = TaskNode(name="T2")
        t3 = TaskNode(name="T3")
        graph.add_task(t1)
        graph.add_task(t2)
        graph.add_task(t3)
        # t3 depends on t1; t2 is independent
        graph.add_dependency(t1.task_id, t3.task_id)
        layers = graph.topological_layers()
        assert len(layers) == 2
        # t1 and t2 can run in parallel
        assert set(layers[0]) == {t1.task_id, t2.task_id}
        assert layers[1] == [t3.task_id]

    def test_get_ready_tasks(self) -> None:
        graph = DependencyGraph()
        t1 = TaskNode(name="T1")
        t2 = TaskNode(name="T2")
        graph.add_task(t1)
        graph.add_task(t2)
        graph.add_dependency(t1.task_id, t2.task_id)
        ready = graph.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == t1.task_id

    def test_is_complete(self) -> None:
        graph = DependencyGraph()
        t1 = TaskNode(name="T1")
        graph.add_task(t1)
        assert not graph.is_complete()
        graph.update_status(t1.task_id, TaskStatus.COMPLETED)
        assert graph.is_complete()

    def test_has_failures(self) -> None:
        graph = DependencyGraph()
        t1 = TaskNode(name="T1")
        graph.add_task(t1)
        graph.update_status(t1.task_id, TaskStatus.FAILED, "error")
        assert graph.has_failures()

    def test_to_dict(self) -> None:
        graph = DependencyGraph()
        t1 = TaskNode(name="T1", description="First task")
        graph.add_task(t1)
        d = graph.to_dict()
        assert d["total_tasks"] == 1
        assert len(d["tasks"]) == 1
        assert d["tasks"][0]["name"] == "T1"


# ---------------------------------------------------------------------------
# Execution Plan Tests
# ---------------------------------------------------------------------------


class TestExecutionPlan:
    def test_from_steps(self) -> None:
        t1 = TaskNode(name="Analyze", agent="ANALYZER")
        t2 = TaskNode(name="Implement", agent="CODER", depends_on=[t1.task_id])
        plan = ExecutionPlan.from_steps(
            title="Add feature X",
            description="Implement feature X",
            steps=[t1, t2],
            session_id="test-session",
        )
        assert plan.title == "Add feature X"
        assert plan.total_steps == 2
        assert plan.session_id == "test-session"

    def test_to_dict(self) -> None:
        t1 = TaskNode(name="Step 1")
        plan = ExecutionPlan.from_steps("Test", "Desc", [t1])
        d = plan.to_dict()
        assert d["title"] == "Test"
        assert d["total_steps"] == 1
        assert "graph" in d


# ---------------------------------------------------------------------------
# Event Bus Tests
# ---------------------------------------------------------------------------


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self) -> None:
        bus = EventBus()
        received: list[OrchestratorEvent] = []

        async def handler(event: OrchestratorEvent) -> None:
            received.append(event)

        await bus.subscribe("agent_started", handler)
        event = OrchestratorEvent(event_type=EventType.AGENT_STARTED, source="CODER")
        await bus.publish(event)

        # Allow async handlers to complete
        await asyncio.sleep(0.01)
        assert len(received) == 1
        assert received[0].source == "CODER"

    @pytest.mark.asyncio
    async def test_wildcard_subscription(self) -> None:
        bus = EventBus()
        received: list[OrchestratorEvent] = []

        async def handler(event: OrchestratorEvent) -> None:
            received.append(event)

        await bus.subscribe("*", handler)
        await bus.publish(OrchestratorEvent(event_type=EventType.TOKEN, source="A"))
        await bus.publish(OrchestratorEvent(event_type=EventType.ERROR, source="B"))
        await asyncio.sleep(0.01)
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[OrchestratorEvent] = []

        async def handler(event: OrchestratorEvent) -> None:
            received.append(event)

        await bus.subscribe("token", handler)
        await bus.publish(OrchestratorEvent(event_type=EventType.TOKEN))
        await asyncio.sleep(0.01)
        assert len(received) == 1

        await bus.unsubscribe("token", handler)
        await bus.publish(OrchestratorEvent(event_type=EventType.TOKEN))
        await asyncio.sleep(0.01)
        assert len(received) == 1  # no new events

    @pytest.mark.asyncio
    async def test_stream_events(self) -> None:
        bus = EventBus()
        events: list[OrchestratorEvent] = []

        async def collect() -> None:
            async for event in bus.stream_events(session_id="s1"):
                events.append(event)
                if len(events) >= 2:
                    break

        # Publish events in background
        async def publish() -> None:
            await asyncio.sleep(0.01)
            await bus.publish(
                OrchestratorEvent(event_type=EventType.TOKEN, session_id="s1", content="hello")
            )
            await bus.publish(
                OrchestratorEvent(event_type=EventType.TOKEN, session_id="s1", content="world")
            )

        await asyncio.gather(collect(), publish())
        assert len(events) == 2
        assert events[0].content == "hello"
        assert events[1].content == "world"

    @pytest.mark.asyncio
    async def test_get_recent_events(self) -> None:
        bus = EventBus()
        for i in range(5):
            await bus.publish(OrchestratorEvent(event_type=EventType.TOKEN, content=str(i)))
        recent = await bus.get_recent_events(limit=3)
        assert len(recent) == 3
        assert recent[-1].content == "4"


# ---------------------------------------------------------------------------
# Event Emitter Tests
# ---------------------------------------------------------------------------


class TestEventEmitter:
    @pytest.mark.asyncio
    async def test_emits_start_and_finish(self) -> None:
        bus = EventBus()
        events: list[OrchestratorEvent] = []

        async def handler(event: OrchestratorEvent) -> None:
            events.append(event)

        await bus.subscribe("*", handler)

        async with EventEmitter(bus, "CODER", "s1") as emit:
            await emit.emit(EventType.TOKEN, content="hello")

        await asyncio.sleep(0.01)
        types = [e.event_type for e in events]
        assert EventType.AGENT_STARTED in types
        assert EventType.TOKEN in types
        assert EventType.AGENT_FINISHED in types


# ---------------------------------------------------------------------------
# Orchestration Engine Tests
# ---------------------------------------------------------------------------


class TestOrchestrationEngine:
    @pytest.fixture
    def mock_ollama(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def mock_registry(self) -> dict:
        agent = MagicMock()
        agent.name = "CODER"
        agent.run = AsyncMock(return_value=iter(["mock", " ", "output"]))
        return {"CODER": agent, "ARCHITECT": agent, "ANALYZER": agent}

    @pytest.fixture
    def event_bus(self) -> EventBus:
        return EventBus()

    @pytest.fixture
    def engine(
        self, mock_ollama: MagicMock, mock_registry: dict, event_bus: EventBus
    ) -> OrchestrationEngine:
        return OrchestrationEngine(
            llm_client=mock_ollama,
            registry=mock_registry,
            event_bus=event_bus,
            max_parallel=2,
        )

    def test_initial_state(self, engine: OrchestrationEngine) -> None:
        assert engine.get_state("any") == OrchestrationState.IDLE

    @pytest.mark.asyncio
    async def test_cancel(self, engine: OrchestrationEngine) -> None:
        await engine.cancel("s1")
        assert engine.get_state("s1") == OrchestrationState.CANCELLED

    @pytest.mark.asyncio
    async def test_execute_simple_plan(self, engine: OrchestrationEngine) -> None:
        t1 = TaskNode(name="Simple task", description="Do something", agent="CODER")
        plan = ExecutionPlan.from_steps("Test", "Test plan", [t1], session_id="s1")
        plan.approved = True

        result = await engine.execute_plan(plan, "s1", auto_approve=True)
        assert result.state == OrchestrationState.COMPLETED
        assert result.completed_tasks == 1
        assert result.failed_tasks == 0

    @pytest.mark.asyncio
    async def test_execute_plan_requires_approval(self, engine: OrchestrationEngine) -> None:
        t1 = TaskNode(name="Task", agent="CODER")
        plan = ExecutionPlan.from_steps("Test", "Desc", [t1])
        plan.requires_approval = True
        plan.approved = False

        with pytest.raises(ValueError, match="approval"):
            await engine.execute_plan(plan, "s1")

    @pytest.mark.asyncio
    async def test_execute_parallel_tasks(self, engine: OrchestrationEngine) -> None:
        t1 = TaskNode(name="Task 1", agent="CODER")
        t2 = TaskNode(name="Task 2", agent="CODER")
        plan = ExecutionPlan.from_steps(
            "Parallel", "Two independent tasks", [t1, t2], session_id="s1"
        )
        plan.approved = True

        result = await engine.execute_plan(plan, "s1", auto_approve=True)
        assert result.completed_tasks == 2

    @pytest.mark.asyncio
    async def test_execute_with_dependencies(self, engine: OrchestrationEngine) -> None:
        t1 = TaskNode(name="First", agent="CODER")
        t2 = TaskNode(name="Second", agent="CODER", depends_on=[t1.task_id])
        plan = ExecutionPlan.from_steps("Sequential", "Dependent tasks", [t1, t2], session_id="s1")
        plan.approved = True

        result = await engine.execute_plan(plan, "s1", auto_approve=True)
        assert result.completed_tasks == 2

    @pytest.mark.asyncio
    async def test_task_failure_handling(self, engine: OrchestrationEngine) -> None:
        # Create a failing agent
        failing_agent = MagicMock()
        failing_agent.name = "CODER"
        failing_agent.run = AsyncMock(side_effect=RuntimeError("Test failure"))
        engine._registry["CODER"] = failing_agent

        t1 = TaskNode(name="Will fail", agent="CODER", max_retries=1)
        plan = ExecutionPlan.from_steps("Fail", "This will fail", [t1], session_id="s1")
        plan.approved = True

        result = await engine.execute_plan(plan, "s1", auto_approve=True)
        assert result.state == OrchestrationState.FAILED
        assert result.failed_tasks == 1
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# Execution Context Tests
# ---------------------------------------------------------------------------


class TestExecutionContext:
    def test_initialization(self) -> None:
        ctx = ExecutionContext(session_id="s1", project_path="/tmp/test")
        assert ctx.session_id == "s1"
        assert ctx.project_path == "/tmp/test"
        assert ctx.shared_memory == {}
        assert ctx.artifacts == {}

    def test_artifact_storage(self) -> None:
        ctx = ExecutionContext(session_id="s1")
        ctx.artifacts["task-1"] = {"name": "Test", "output": "result"}
        assert "task-1" in ctx.artifacts
        assert ctx.artifacts["task-1"]["output"] == "result"
