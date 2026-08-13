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

import backend.orchestrator.engine as engine_module
from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskStatus,
)
from backend.orchestrator.engine import (
    ExecutionContext,
    OrchestrationEngine,
    OrchestrationResult,
    OrchestrationState,
)
from backend.orchestrator.engine import (
    extract_tool_errors as _extract_tool_errors,
)
from backend.orchestrator.events import (
    EventBus,
    EventEmitter,
    EventType,
    OrchestratorEvent,
)
from backend.orchestrator.plan_executor import extract_spawn_requests
from backend.orchestrator.plan_validation import PlanningResult
from backend.orchestrator.types import OrchestrationState as SharedOrchestrationState

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
    async def test_slow_stream_drops_oldest_events_without_blocking_publish(self) -> None:
        """A full client queue must not stall the producer/orchestrator."""
        bus = EventBus(max_queue_size=2)
        stream = bus.stream_events(session_id="s1")

        # Start the generator and consume one event.  It remains subscribed,
        # but intentionally stops reading afterwards to simulate a slow SSE
        # client.
        first_event = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        await bus.publish(
            OrchestratorEvent(event_type=EventType.TOKEN, session_id="s1", content="one")
        )
        assert (await first_event).content == "one"

        await bus.publish(
            OrchestratorEvent(event_type=EventType.TOKEN, session_id="s1", content="two")
        )
        await bus.publish(
            OrchestratorEvent(event_type=EventType.TOKEN, session_id="s1", content="three")
        )

        # The third unread event used to block here forever because the stream
        # callback awaited queue.put().  The explicit policy drops "two" and
        # keeps the newest progress events.
        await asyncio.wait_for(
            bus.publish(
                OrchestratorEvent(event_type=EventType.TOKEN, session_id="s1", content="four")
            ),
            timeout=0.1,
        )
        assert (await anext(stream)).content == "three"
        assert (await anext(stream)).content == "four"
        await stream.aclose()

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
        assert OrchestrationState is SharedOrchestrationState

    @pytest.mark.asyncio
    async def test_blocked_planning_can_continue_only_into_approval(
        self, engine: OrchestrationEngine
    ) -> None:
        proposal = ExecutionPlan.from_steps(
            "Safe fallback",
            "Validated deterministic proposal",
            [TaskNode(name="Inspect", agent="ANALYZER")],
            session_id="blocked-session",
        )
        engine._planning_results["blocked-session"] = PlanningResult(
            status="blocked",
            source="deterministic_fallback",
            error="provider returned malformed output",
            deterministic_proposal=proposal,
        )
        engine._state["blocked-session"] = OrchestrationState.PLANNING_BLOCKED

        continued = await engine.continue_planning("blocked-session")

        assert continued is not None
        assert continued.status == "ready"
        assert continued.plan is proposal
        assert proposal.approved is False
        assert engine.get_state("blocked-session") == OrchestrationState.AWAITING_APPROVAL
        approval = engine.request_approval(proposal.plan_id)
        assert approval is not None
        assert approval.session_id == "blocked-session"

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
    async def test_execute_plan_cancellation_wins_over_optimistic_executor_result(
        self, event_bus: EventBus
    ) -> None:
        """A concurrent cancellation cannot be reported back as completed."""
        completed_result = OrchestrationResult(
            run_id="run",
            state=OrchestrationState.COMPLETED,
            completed_tasks=1,
        )

        async def complete_after_cancellation(*_args, cancellation_event, **_kwargs):
            cancellation_event.set()
            return completed_result, MagicMock()

        plan_executor = MagicMock()
        plan_executor.execute = complete_after_cancellation
        engine = OrchestrationEngine(
            llm_client=MagicMock(),
            registry={},
            event_bus=event_bus,
            plan_executor=plan_executor,
        )
        plan = ExecutionPlan.from_steps(
            "Test", "Desc", [TaskNode(name="Task")], session_id="s1"
        )

        result = await engine.execute_plan(plan, "s1", auto_approve=True)

        assert result.state == OrchestrationState.CANCELLED
        assert engine.get_state("s1") == OrchestrationState.CANCELLED

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
    async def test_spawned_task_runs_in_same_plan(self, event_bus: EventBus) -> None:
        call_count = 0

        async def run_agent(_request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield (
                    '<event>tool_result|spawn_task|{"status":"spawned",'
                    '"task_name":"Verify","description":"Run focused tests",'
                    '"agent":"DEBUGGER"}</event>'
                )
            else:
                yield "<event>answer</event>Verification complete"

        agent = MagicMock()
        agent.name = "CODER"
        agent.run = run_agent
        dynamic_engine = OrchestrationEngine(
            llm_client=MagicMock(),
            registry={"CODER": agent, "DEBUGGER": agent},
            event_bus=event_bus,
            max_parallel=2,
        )
        initial = TaskNode(name="Implement", agent="CODER")
        plan = ExecutionPlan.from_steps("Dynamic", "Spawn verification", [initial])

        result = await dynamic_engine.execute_plan(plan, "s1", auto_approve=True)

        assert result.completed_tasks == 2
        assert call_count == 2
        assert len(plan.dependency_graph.get_all_tasks()) == 2

    @pytest.mark.asyncio
    async def test_execute_with_dependencies(self, engine: OrchestrationEngine) -> None:
        t1 = TaskNode(name="First", agent="CODER")
        t2 = TaskNode(name="Second", agent="CODER", depends_on=[t1.task_id])
        plan = ExecutionPlan.from_steps("Sequential", "Dependent tasks", [t1, t2], session_id="s1")
        plan.approved = True

        result = await engine.execute_plan(plan, "s1", auto_approve=True)
        assert result.completed_tasks == 2

    @pytest.mark.asyncio
    async def test_failed_predecessor_blocks_dependent_task(
        self, engine: OrchestrationEngine, event_bus: EventBus
    ) -> None:
        """A failed hand-off must never start its dependent agent."""
        predecessor = MagicMock()
        predecessor.name = "CODER"
        predecessor.run = AsyncMock(side_effect=RuntimeError("predecessor failed"))
        dependent = MagicMock()
        dependent.name = "ANALYZER"
        dependent.run = AsyncMock(return_value=iter(["should not run"]))
        engine._registry.update({"CODER": predecessor, "ANALYZER": dependent})

        first = TaskNode(name="First", agent="CODER", max_retries=0)
        second = TaskNode(
            name="Second", agent="ANALYZER", depends_on=[first.task_id], max_retries=0
        )
        plan = ExecutionPlan.from_steps("Failure hand-off", "desc", [first, second])

        result = await engine.execute_plan(plan, "s1", auto_approve=True)

        assert result.state == OrchestrationState.FAILED
        assert result.failed_tasks == 1
        assert result.blocked_tasks == 1
        assert dependent.run.await_count == 0
        assert second.status == TaskStatus.BLOCKED
        events = await event_bus.get_recent_events(limit=100)
        assert any(event.event_type == EventType.TASK_BLOCKED for event in events)

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

    @pytest.mark.asyncio
    async def test_task_can_recover_after_entering_retrying(
        self, engine: OrchestrationEngine
    ) -> None:
        attempts = 0

        async def flaky_run(_request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary provider failure")
            yield "Recovered with verified output"

        agent = MagicMock()
        agent.name = "CODER"
        agent.run = flaky_run
        engine._registry["CODER"] = agent

        task = TaskNode(name="Retry once", agent="CODER", max_retries=1)
        plan = ExecutionPlan.from_steps("Retry", "Recover", [task], session_id="s1")

        result = await engine.execute_plan(plan, "s1", auto_approve=True)

        assert attempts == 2
        assert task.retry_count == 1
        assert task.status == TaskStatus.COMPLETED
        assert result.state == OrchestrationState.COMPLETED
        assert result.completed_tasks == 1

    @pytest.mark.asyncio
    async def test_task_fails_when_agent_output_contains_tool_error(
        self, engine: OrchestrationEngine
    ) -> None:
        failing_output = (
            '<event>tool_call|write_file|{"path": "x.txt", "content": "hi"}</event>'
            "<event>tool_error|Permission denied: blocked path</event>"
        )

        async def _run_with_tool_error(_request):
            for token in [failing_output]:
                yield token

        tool_fail_agent = MagicMock()
        tool_fail_agent.name = "CODER"
        tool_fail_agent.run = _run_with_tool_error
        engine._registry["CODER"] = tool_fail_agent

        t1 = TaskNode(name="Write file", agent="CODER")
        plan = ExecutionPlan.from_steps(
            "Tool fail", "Should fail on tool error", [t1], session_id="s1"
        )
        plan.approved = True

        result = await engine.execute_plan(plan, "s1", auto_approve=True)
        assert result.state == OrchestrationState.FAILED
        assert result.failed_tasks == 1
        artifact = result.task_results[t1.task_id]
        assert artifact["status"] == "failed"

    @pytest.mark.asyncio
    async def test_autonomous_primary_failure_is_preserved(
        self, event_bus: EventBus, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(engine_module, "require_disk_headroom", lambda _path: None)
        """A failed primary plan must not be overwritten by final review success."""
        plan = ExecutionPlan.from_steps(
            "Primary plan",
            "desc",
            [TaskNode(name="Analyze", agent="ANALYZER")],
            session_id="s1",
        )
        plan_creator = MagicMock()
        plan_creator.create = AsyncMock(return_value=plan)
        failed_result = OrchestrationResult(
            run_id="primary",
            state=OrchestrationState.FAILED,
            failed_tasks=1,
            errors=["primary task failed"],
        )
        plan_executor = MagicMock()
        plan_executor.execute = AsyncMock(return_value=(failed_result, MagicMock()))
        engine = OrchestrationEngine(
            llm_client=MagicMock(),
            registry={},
            event_bus=event_bus,
            plan_creator=plan_creator,
            plan_executor=plan_executor,
        )

        result = await engine.execute_autonomous("objective", "s1")

        assert result.state == OrchestrationState.FAILED
        assert engine.get_state("s1") == OrchestrationState.FAILED
        # No verification or review may run after a terminal primary failure.
        assert plan_executor.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_autonomous_primary_cancellation_is_preserved(
        self, event_bus: EventBus, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(engine_module, "require_disk_headroom", lambda _path: None)
        """Cancellation must stop the autonomous cycle before later phases."""
        plan = ExecutionPlan.from_steps(
            "Primary plan",
            "desc",
            [TaskNode(name="Analyze", agent="ANALYZER")],
            session_id="s1",
        )
        plan_creator = MagicMock()
        plan_creator.create = AsyncMock(return_value=plan)
        cancelled_result = OrchestrationResult(
            run_id="primary",
            state=OrchestrationState.CANCELLED,
        )
        plan_executor = MagicMock()
        plan_executor.execute = AsyncMock(return_value=(cancelled_result, MagicMock()))
        engine = OrchestrationEngine(
            llm_client=MagicMock(),
            registry={},
            event_bus=event_bus,
            plan_creator=plan_creator,
            plan_executor=plan_executor,
        )

        result = await engine.execute_autonomous("objective", "s1")

        assert result.state == OrchestrationState.CANCELLED
        assert engine.get_state("s1") == OrchestrationState.CANCELLED
        assert plan_executor.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_autonomous_final_review_failure_is_preserved(
        self, event_bus: EventBus, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(engine_module, "require_disk_headroom", lambda _path: None)
        """A failed final review cannot turn a run into COMPLETED."""
        plan = ExecutionPlan.from_steps(
            "Primary plan",
            "desc",
            [TaskNode(name="Analyze", agent="ANALYZER")],
            session_id="s1",
        )
        plan_creator = MagicMock()
        plan_creator.create = AsyncMock(return_value=plan)
        primary_result = OrchestrationResult(
            run_id="primary",
            state=OrchestrationState.COMPLETED,
            completed_tasks=1,
        )
        review_failure = OrchestrationResult(
            run_id="review",
            state=OrchestrationState.FAILED,
            failed_tasks=1,
            errors=["review agent failed"],
        )
        plan_executor = MagicMock()
        plan_executor.execute = AsyncMock(
            side_effect=[(primary_result, MagicMock()), (review_failure, MagicMock())]
        )
        engine = OrchestrationEngine(
            llm_client=MagicMock(),
            registry={},
            event_bus=event_bus,
            plan_creator=plan_creator,
            plan_executor=plan_executor,
        )

        result = await engine.execute_autonomous("objective", "s1", max_verify_iterations=0)

        assert result is review_failure
        assert result.state == OrchestrationState.FAILED
        assert engine.get_state("s1") == OrchestrationState.FAILED


class TestToolErrorExtraction:
    def test_extract_tool_errors_from_react_output(self) -> None:
        output = (
            "Planning..."
            "<event>tool_error|Write operation failed</event>"
            "<event>tool_error|Disk full</event>"
        )
        errors = _extract_tool_errors(output)
        assert errors == ["Write operation failed", "Disk full"]

    def test_extract_spawn_requests_from_react_output(self) -> None:
        output = (
            'before<event>tool_result|spawn_task|{"status":"spawned",'
            '"task_name":"Verify","description":"Run tests","agent":"DEBUGGER"}'
            "</event>after"
        )

        assert extract_spawn_requests(output) == [
            {
                "status": "spawned",
                "task_name": "Verify",
                "description": "Run tests",
                "agent": "DEBUGGER",
            }
        ]


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
