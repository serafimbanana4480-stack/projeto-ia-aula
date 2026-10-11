"""The watchdog sees what a run's own coroutine cannot: that it stopped.

Each test drives one detector — stale heartbeat, exhausted budget, repeated
tool, ceiling — and pins what it must produce (the action, the recorded
evidence, who is allowed to act) and what it must never produce (a completion).

Runs are written into a throwaway SQLite file under ``tmp_path`` so the
watchdog owns its database exactly as it would in production.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.runtime import run_context
from backend.runtime.run_coordinator import RunCoordinator, RunRecord, RunState
from backend.runtime.run_watchdog import (
    WATCHDOG_CHECKPOINT_PHASES,
    RunWatchdog,
    WatchdogAction,
    WatchdogDecision,
    WatchdogSignal,
    start_watchdog,
    stop_watchdog,
)
from backend.tools.registry import ToolSpec, execute_tool, register_tool


@pytest.fixture
def coordinator(tmp_path) -> RunCoordinator:
    return RunCoordinator(db_path=str(tmp_path / "watchdog.db"))


class FakeClock:
    """An injectable "now", so a run can be aged without sleeping."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


def _watchdog(coordinator: RunCoordinator, clock: FakeClock, **kwargs) -> RunWatchdog:
    kwargs.setdefault("stale_heartbeat_seconds", 60.0)
    kwargs.setdefault("max_runtime_seconds", 600.0)
    kwargs.setdefault("interval_seconds", 5.0)
    return RunWatchdog(coordinator, clock=clock, **kwargs)


#: Twice the helper's stale threshold (60 s) and below its 3x escalation point
#: (180 s), so a heartbeat this old is "stalled", not yet "escalated".
STALE_AGE = 120


def _iso(delta_seconds: float) -> str:
    moment = datetime.now(UTC) + timedelta(seconds=delta_seconds)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _active_run(coordinator: RunCoordinator, *, budget: dict | None = None) -> RunRecord:
    run = coordinator.create_run(
        goal="ship the feature", requirements=["tests green", "docs updated"], budget=budget
    )
    # CREATED → PLANNING → RUNNING is the machine's own legal path.
    coordinator.transition(run.run_id, RunState.PLANNING)
    return coordinator.transition(run.run_id, RunState.RUNNING)


def _age_heartbeat(coordinator: RunCoordinator, run_id: str, seconds: float) -> None:
    """Backdate the heartbeat exactly as a stalled run would leave it."""
    from backend.persistence import db

    db.update_run_row(
        run_id, {"heartbeat_at": _iso(-seconds)}, db_path=coordinator.db_path
    )


def _record_tool_call(coordinator: RunCoordinator, run_id: str, tool: str) -> None:
    """Write the checkpoint a real loop writes when it calls a tool."""
    coordinator.checkpoint(
        run_id, phase="after_task", payload={"tool_calls": [tool], "task": "implement"}
    )


def _choose_transition(decision: WatchdogDecision) -> set[RunState]:
    """The states this decision can move the run to, as the watchdog sees it."""
    mapping = {
        WatchdogAction.PAUSE: {RunState.PAUSED},
        WatchdogAction.FAIL: {RunState.FAILED},
        WatchdogAction.RECOVER: {RunState.RECOVERING},
    }
    return mapping.get(decision.action, set())


# ───── a healthy run is nobody's business ────────────────────────────────


async def test_healthy_run_produces_no_decision(coordinator: RunCoordinator) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)

    decision = RunWatchdog(coordinator, clock=clock).decide(run)

    assert decision is None


async def test_a_sweep_of_healthy_runs_finds_nothing(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    _active_run(coordinator)

    decisions = await _watchdog(coordinator, clock).evaluate_once()

    assert decisions == []


async def test_run_waiting_for_a_human_is_not_a_stall(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    coordinator.transition(run.run_id, RunState.WAITING_APPROVAL)
    _age_heartbeat(coordinator, run.run_id, 3_600)

    decision = _watchdog(coordinator, clock, max_runtime_seconds=100_000.0).decide(run.run_id)

    assert decision is None, "waiting for a person is not a stall"


async def test_terminal_run_is_never_evaluated(coordinator: RunCoordinator) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    coordinator.transition(run.run_id, RunState.VERIFYING)
    coordinator.complete(
        run.run_id, [{"requirement": "tests green", "verdict": "PASS", "evidence": {}}]
    )
    clock.advance(10_000)

    assert _watchdog(coordinator, clock).decide(run.run_id) is None


# ───── 1. stale heartbeat ────────────────────────────────────────────────


async def test_stale_heartbeat_pauses_the_run(coordinator: RunCoordinator) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    _age_heartbeat(coordinator, run.run_id, STALE_AGE)
    watchdog = _watchdog(coordinator, clock)

    decision = watchdog.decide(run)

    assert decision is not None
    assert decision.action is WatchdogAction.PAUSE
    assert WatchdogSignal.STALE_HEARTBEAT.value in decision.signal_names
    assert "no heartbeat" in decision.reason
    assert decision.applies_itself is True

    record = watchdog.apply(decision)
    assert record is not None
    assert record.state is RunState.PAUSED


async def test_a_paused_run_nobody_resumed_is_escalated(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    _age_heartbeat(coordinator, run.run_id, STALE_AGE)
    watchdog = _watchdog(coordinator, clock)

    first = watchdog.decide(run)
    watchdog.apply(first)
    second = watchdog.decide(run.run_id)

    assert second is not None
    assert second.action is WatchdogAction.ESCALATE
    assert second.applies_itself is False, "escalation belongs to the orchestrator"


async def test_a_missing_heartbeat_is_a_stall(coordinator: RunCoordinator) -> None:
    """A run that never reported liveness at all must not be mistaken for work."""
    clock = FakeClock()
    run = coordinator.create_run(goal="no heartbeat yet", requirements=["finish"])
    from backend.persistence import db

    db.update_run_row(run.run_id, {"heartbeat_at": ""}, db_path=coordinator.db_path)

    decision = _watchdog(coordinator, clock).decide(run.run_id)

    assert decision is not None
    assert decision.action is WatchdogAction.PAUSE


# ───── 2. budget and runtime ─────────────────────────────────────────────


async def test_exhausted_budget_fails_the_run(coordinator: RunCoordinator) -> None:
    clock = FakeClock()
    run = _active_run(coordinator, budget={"max_tool_calls": 2})
    coordinator.record_usage(run.run_id, tool_calls=5)

    decision = _watchdog(coordinator, clock).decide(run)

    assert decision is not None
    assert decision.action is WatchdogAction.FAIL
    assert WatchdogSignal.BUDGET_EXCEEDED.value in decision.signal_names
    assert decision.reason.startswith("budget exceeded:")
    assert decision.applies_itself is True

    record = _watchdog(coordinator, clock).apply(decision)
    assert record is not None
    assert record.state is RunState.FAILED


async def test_budget_max_runtime_is_a_hard_limit(coordinator: RunCoordinator) -> None:
    clock = FakeClock()
    run = _active_run(coordinator, budget={"max_runtime_seconds": 30})
    clock.advance(300)
    # The heartbeat is fresh: the run is alive, it simply may not run this long.
    coordinator.update_progress(run.run_id, retry_count=0)

    decision = _watchdog(coordinator, clock).decide(run)

    assert decision is not None
    assert decision.action is WatchdogAction.FAIL
    signal = next(
        item for item in decision.signals if item["signal"] == WatchdogSignal.MAX_RUNTIME_EXCEEDED.value
    )
    assert signal["source"] == "budget.max_runtime_seconds"


async def test_configured_ceiling_pauses_without_failing(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    clock.advance(1_200)

    decision = _watchdog(
        coordinator,
        clock,
        max_runtime_seconds=600.0,
        # The heartbeat is fresh in wall-clock terms; only the ceiling fires.
        stale_heartbeat_seconds=5_000.0,
    ).decide(run)

    assert decision is not None
    assert decision.action is WatchdogAction.PAUSE
    assert "ceiling" in decision.reason


# ───── 3. the same tool again ────────────────────────────────────────────


async def test_repeated_tool_asks_for_a_strategy_change(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    for _ in range(3):
        _record_tool_call(coordinator, run.run_id, "web_search")

    decision = _watchdog(coordinator, clock).decide(run)

    assert decision is not None
    assert decision.action is WatchdogAction.CHANGE_STRATEGY
    assert decision.applies_itself is False
    assert "web_search" in decision.reason


async def test_a_run_that_never_stops_looping_asks_for_a_replan(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    for _ in range(6):
        _record_tool_call(coordinator, run.run_id, "read_file")

    decision = _watchdog(coordinator, clock, repeated_tool_threshold=3).decide(run)

    assert decision is not None
    assert decision.action is WatchdogAction.REPLAN
    assert decision.applies_itself is False


async def test_change_strategy_is_not_applied_by_the_watchdog(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    for _ in range(3):
        _record_tool_call(coordinator, run.run_id, "web_search")
    watchdog = _watchdog(coordinator, clock)

    decision = watchdog.decide(run)
    assert decision is not None
    assert watchdog.apply(decision) is None
    # The run is untouched: choosing another strategy is the orchestrator's.
    assert coordinator.get_run(run.run_id).state is RunState.RUNNING


# ───── 4. no decision ever completes a run ───────────────────────────────


async def test_no_watchdog_action_can_complete_a_run() -> None:
    assert "completed" not in {action.value for action in WatchdogAction}


async def test_no_stall_ever_produces_a_completion(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    scenarios = []
    stalled = _active_run(coordinator, budget={"max_tool_calls": 1})
    coordinator.record_usage(stalled.run_id, tool_calls=9)
    scenarios.append(stalled)
    quiet = _active_run(coordinator)
    _age_heartbeat(coordinator, quiet.run_id, STALE_AGE)
    scenarios.append(quiet)
    looping = _active_run(coordinator)
    for _ in range(5):
        _record_tool_call(coordinator, looping.run_id, "web_search")
    scenarios.append(looping)
    clock.advance(10_000)

    for run in scenarios:
        decision = _watchdog(coordinator, clock).decide(run)
        assert decision is not None, run.run_id
        assert decision.action.value != RunState.COMPLETED.value
        assert RunState.COMPLETED not in _choose_transition(decision)


# ───── 5. observability ──────────────────────────────────────────────────


async def test_a_decision_is_recorded_as_a_checkpoint(
    coordinator: RunCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    _age_heartbeat(coordinator, run.run_id, STALE_AGE)
    watchdog = _watchdog(coordinator, clock)

    with caplog.at_level(logging.WARNING, logger="backend.runtime.run_watchdog"):
        decisions = await watchdog.evaluate_once()

    assert len(decisions) == 1
    assert "[WATCHDOG]" in caplog.text
    assert run.run_id in caplog.text

    checkpoint = coordinator.latest_checkpoint(run.run_id)
    assert checkpoint is not None
    assert checkpoint.payload["watchdog"] is True
    assert checkpoint.payload["watchdog_phase"] == "watchdog"
    assert checkpoint.payload["action"] == WatchdogAction.PAUSE.value
    assert checkpoint.phase in WATCHDOG_CHECKPOINT_PHASES
    assert decisions[0].details["checkpoint_phase"] == checkpoint.phase


async def test_decisions_reach_the_orchestrator_callback(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    _age_heartbeat(coordinator, run.run_id, STALE_AGE)
    seen: list[WatchdogDecision] = []
    watchdog = _watchdog(coordinator, clock, on_decision=seen.append)

    decisions = await watchdog.evaluate_once()

    assert len(decisions) == 1
    assert seen == decisions


async def test_a_broken_callback_does_not_break_the_sweep(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    _age_heartbeat(coordinator, run.run_id, STALE_AGE)

    def explode(decision: object) -> None:
        raise RuntimeError("orchestrator hook is down")

    watchdog = _watchdog(coordinator, clock, on_decision=explode)
    decisions = await watchdog.evaluate_once()

    assert len(decisions) == 1
    assert watchdog.snapshot()["counts"]["decisions"] == 1


async def test_snapshot_reports_what_the_watchdog_sees(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    _age_heartbeat(coordinator, run.run_id, STALE_AGE)
    watchdog = _watchdog(coordinator, clock)
    await watchdog.evaluate_once()

    snapshot = watchdog.snapshot()

    assert snapshot["counts"]["sweeps"] == 1
    assert snapshot["counts"]["runs_seen"] == 1
    assert snapshot["counts"]["applied"] == 1
    assert snapshot["watching_tasks"] is False
    assert snapshot["decisions"][0]["action"] == WatchdogAction.PAUSE.value


# ───── 6. tasks ──────────────────────────────────────────────────────────


class FakeTaskManager:
    """The slice of the task manager the watchdog uses."""

    def __init__(self, tasks: list[object]) -> None:
        self._tasks = tasks

    async def get_tasks(self, *, limit: int = 100) -> list[object]:
        return list(self._tasks)


def _task(status: str, *, task_id: str, run_id: str = "", age_seconds: float = 0.0) -> object:
    return SimpleNamespace(
        task_id=task_id,
        name=task_id,
        status=status,
        error=None,
        metadata={"run_id": run_id} if run_id else {},
        updated_at=datetime.now() + timedelta(seconds=-age_seconds),
    )


async def test_a_stalled_task_is_reported(coordinator: RunCoordinator) -> None:
    clock = FakeClock()
    manager = FakeTaskManager([_task("running", task_id="task-stalled", age_seconds=900)])
    watchdog = _watchdog(coordinator, clock, task_manager=manager)

    decisions = await watchdog.evaluate_once()

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.action is WatchdogAction.PAUSE
    assert decision.target_kind == "task"
    assert decision.target_id == "task-stalled"
    assert WatchdogSignal.TASK_STALLED.value in decision.signal_names


async def test_a_failed_task_without_a_dead_letter_is_escalated(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    manager = FakeTaskManager([_task("failed", task_id="task-dead", age_seconds=1)])
    watchdog = _watchdog(coordinator, clock, task_manager=manager)

    decisions = await watchdog.evaluate_once()

    assert [d.action for d in decisions] == [WatchdogAction.ESCALATE]
    assert (
        WatchdogSignal.TASK_FAILED_UNEXPLAINED.value in decisions[0].signal_names
    ), "a FAILED task with nothing parked is the failure this rule exists for"


async def test_a_failed_task_with_a_dead_letter_is_explained(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    coordinator.enqueue_dead_letter({"task_id": "task-parked", "error_class": "TimeoutError"})
    manager = FakeTaskManager([_task("failed", task_id="task-parked", age_seconds=1)])
    watchdog = _watchdog(coordinator, clock, task_manager=manager)

    assert await watchdog.evaluate_once() == []


async def test_a_working_task_manager_is_optional(coordinator: RunCoordinator) -> None:
    clock = FakeClock()
    watchdog = _watchdog(coordinator, clock)
    assert await watchdog.evaluate_once() == []


async def test_a_stalled_run_is_recorded_once_per_cooldown(
    coordinator: RunCoordinator,
) -> None:
    """A run that stays stalled must not write a checkpoint every sweep."""
    clock = FakeClock()
    run = _active_run(coordinator)
    for _ in range(3):
        _record_tool_call(coordinator, run.run_id, "web_search")
    watchdog = _watchdog(
        coordinator, clock, interval_seconds=0.02, decision_cooldown_seconds=3_600.0
    )

    await watchdog.evaluate_once()
    await watchdog.evaluate_once()

    checkpoints = [
        checkpoint
        for checkpoint in coordinator.list_checkpoints(run.run_id)
        if checkpoint.payload.get("watchdog")
    ]
    assert len(checkpoints) == 1, "the second sweep repeated a decision it already recorded"
    assert watchdog.snapshot()["counts"]["decisions"] == 2, "but it still decided"
    assert watchdog.decisions[-1].action is WatchdogAction.CHANGE_STRATEGY


async def test_a_paused_run_is_not_paused_twice(coordinator: RunCoordinator) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    _age_heartbeat(coordinator, run.run_id, STALE_AGE)
    watchdog = _watchdog(coordinator, clock, decision_cooldown_seconds=0.0)

    first = watchdog.decide(run)
    assert watchdog.apply(first) is not None
    # The run is paused now; the next decision is an escalation, not a second
    # pause of an already-paused run.
    second = watchdog.decide(run.run_id)
    assert second.action is WatchdogAction.ESCALATE


# ───── 7. lifecycle ──────────────────────────────────────────────────────


async def test_start_watchdog_is_idempotent_and_stop_is_safe(
    coordinator: RunCoordinator,
) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    _age_heartbeat(coordinator, run.run_id, STALE_AGE)

    watchdog = start_watchdog(
        coordinator, interval_seconds=0.02, stale_heartbeat_seconds=60.0, clock=clock
    )
    again = start_watchdog(coordinator, interval_seconds=0.02, clock=clock)
    assert again is watchdog, "two loops would fight over the same run"

    for _ in range(100):
        if watchdog.decisions:
            break
        await asyncio.sleep(0.02)
    assert watchdog.decisions, "the loop never ran a sweep"

    stop_watchdog()
    assert watchdog.running is False
    await watchdog.wait_closed()
    stop_watchdog()  # stopping twice is not an error


async def test_the_loop_survives_a_failing_sweep(coordinator: RunCoordinator) -> None:
    clock = FakeClock()
    run = _active_run(coordinator)
    _age_heartbeat(coordinator, run.run_id, STALE_AGE)
    watchdog = _watchdog(coordinator, clock)

    class ExplodingCoordinator:
        """A coordinator whose reads fail on the first sweep only."""

        def __init__(self, inner: RunCoordinator) -> None:
            self._inner = inner
            self.calls = 0

        def list_runs(self, **kwargs: object) -> list[RunRecord]:
            self.calls += 1
            if self.calls == 1:
                raise OSError("database is locked")
            return self._inner.list_runs(**kwargs)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    watchdog._coordinator = ExplodingCoordinator(coordinator)  # type: ignore[assignment]
    watchdog.start()
    try:
        for _ in range(200):
            if watchdog.snapshot()["counts"]["sweeps"] >= 2:
                break
            await asyncio.sleep(0.02)
        assert watchdog.snapshot()["counts"]["sweeps"] >= 2
        assert watchdog.decisions, "the sweep after the failure still decided"
    finally:
        watchdog.stop()
        await watchdog.wait_closed()


# ───── 8. the budget hook in the tool registry ───────────────────────────


class TestRunContext:
    """The channel the budget hook reads; a global would cross-charge runs."""

    def test_no_run_is_the_default(self) -> None:
        assert run_context.get_current_run_id() == ""

    def test_setting_and_resetting_restores_the_previous_run(self) -> None:
        token = run_context.set_current_run_id("run-a")
        assert run_context.get_current_run_id() == "run-a"
        run_context.reset_current_run_id(token)
        assert run_context.get_current_run_id() == ""

    def test_active_run_scopes_the_value_to_the_block(self) -> None:
        with run_context.active_run("run-b"):
            assert run_context.get_current_run_id() == "run-b"
        assert run_context.get_current_run_id() == ""

    async def test_two_concurrent_tasks_do_not_share_the_run(self) -> None:
        """A context variable is per-task; a module global would not be."""

        async def read_after_a_tick() -> str:
            await asyncio.sleep(0)
            return run_context.get_current_run_id()

        async def with_run(run_id: str) -> str:
            token = run_context.set_current_run_id(run_id)
            try:
                return await read_after_a_tick()
            finally:
                run_context.reset_current_run_id(token)

        first, second = await asyncio.gather(with_run("run-1"), with_run("run-2"))
        assert (first, second) == ("run-1", "run-2")

    def test_a_blank_run_id_reads_as_no_run(self) -> None:
        token = run_context.set_current_run_id("   ")
        try:
            assert run_context.get_current_run_id() == ""
        finally:
            run_context.reset_current_run_id(token)


@pytest.fixture
def app_coordinator() -> RunCoordinator:
    """A coordinator on the application database (what the registry hook uses)."""
    return RunCoordinator()


@pytest.fixture
def budget_probe():
    """A registered, harmless tool whose execution can be observed."""

    async def handler(**_kwargs: object) -> dict:
        return {"ok": True, "ran": True}

    spec = ToolSpec(name="budget_probe_tool", description="probe", handler=handler)
    register_tool(spec)
    yield spec
    from backend.tools import registry as registry_module

    registry_module._registry.pop("budget_probe_tool", None)


async def _call_probe(run_id: str | None) -> dict:
    """Call the probe tool with *run_id* published (or nothing)."""
    if run_id is None:
        return await execute_tool("budget_probe_tool", "sess-budget", {})
    token = run_context.set_current_run_id(run_id)
    try:
        return await execute_tool("budget_probe_tool", "sess-budget", {})
    finally:
        run_context.reset_current_run_id(token)


async def test_without_a_run_the_hook_does_nothing(
    budget_probe: ToolSpec, app_coordinator: RunCoordinator
) -> None:
    """The no-op contract: a tool outside a run is charged to nothing."""
    result = await _call_probe(None)

    assert result["ok"] is True
    assert result["result"]["ran"] is True


async def test_a_tool_call_is_charged_to_the_active_run(
    budget_probe: ToolSpec, app_coordinator: RunCoordinator
) -> None:
    run = app_coordinator.create_run(goal="count my tools", requirements=["finish"])

    result = await _call_probe(run.run_id)

    assert result["ok"] is True
    assert app_coordinator.budget_status(run.run_id).usage["tool_calls"] == 1


async def test_an_exhausted_budget_blocks_the_tool_visibly(
    budget_probe: ToolSpec, app_coordinator: RunCoordinator
) -> None:
    run = app_coordinator.create_run(
        goal="bounded", requirements=["finish"], budget={"max_tool_calls": 1}
    )
    app_coordinator.record_usage(run.run_id, tool_calls=1)

    result = await _call_probe(run.run_id)

    assert result["ok"] is False
    assert result["error_category"] == "budget_exceeded"
    assert "budget exceeded" in result["error"]
    assert result["budget_exceeded"] == {"tool_calls": "2>1"}
    assert result["result"] is None, "no handler ran"
    # The blocked call is still accounted for: it was a real attempt.
    assert app_coordinator.budget_status(run.run_id).usage["tool_calls"] == 2


async def test_a_read_only_tool_is_blocked_too(
    budget_probe: ToolSpec, app_coordinator: RunCoordinator
) -> None:
    """Documented choice: there is no read-only exemption from a budget."""
    run = app_coordinator.create_run(
        goal="bounded", requirements=["finish"], budget={"max_tool_calls": 0}
    )

    result = await _call_probe(run.run_id)

    assert result["ok"] is False
    assert "budget exceeded" in result["error"]


async def test_a_vanished_run_never_blocks_a_tool(
    budget_probe: ToolSpec, app_coordinator: RunCoordinator
) -> None:
    """Accounting must not be able to stop work that has nothing to charge."""
    result = await _call_probe("run-that-does-not-exist")

    assert result["ok"] is True


async def test_the_hook_can_be_switched_off(
    budget_probe: ToolSpec, app_coordinator: RunCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_TOOL_BUDGET_HOOK", "0")
    run = app_coordinator.create_run(
        goal="bounded", requirements=["finish"], budget={"max_tool_calls": 0}
    )

    result = await _call_probe(run.run_id)

    assert result["ok"] is True
    assert app_coordinator.budget_status(run.run_id).usage["tool_calls"] == 0




