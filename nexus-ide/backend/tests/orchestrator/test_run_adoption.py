"""Adoption of the durable run a previous process left behind.

``OrchestrationEngine._run_lifecycle_for`` used to create a brand-new durable
run on every cycle, even when the same session and goal already owned a
non-terminal one. Two runs for one unit of work means two checkpoints, two
side-effect ledgers and two budgets — precisely the state a restart must NOT
duplicate, because the ledger is what stops a resumed execution from writing
the same file twice.

These tests pin the three properties of the adoption:

1. a non-terminal run for the same identity is adopted (same run id, no second
   row) and re-enters ``RUNNING`` with the reason ``"adopted after restart"``;
2. no matching run means behaviour is unchanged: a new run is created;
3. a failing lookup degrades to that same "create a new one" path — the cycle
   itself is never what breaks.
"""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from backend.orchestrator.dependency_graph import ExecutionPlan
from backend.orchestrator.engine import ADOPTED_RUN_REASON, OrchestrationEngine, OrchestrationState
from backend.orchestrator.events import EventBus
from backend.runtime import primary as runtime_primary
from backend.runtime import run_context
from backend.runtime.run_coordinator import RunCoordinator, RunState

GOAL = "Implementar a auditoria"
SESSION = "sess-adoption"


def _engine() -> OrchestrationEngine:
    return OrchestrationEngine(
        llm_client=object(),
        registry={},
        event_bus=EventBus(),
    )


def _coordinator() -> RunCoordinator:
    coordinator = runtime_primary.get_run_coordinator()
    assert coordinator is not None
    return coordinator


def _rows(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(_coordinator().db_path))
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute(sql, params))
    finally:
        conn.close()


def _run_ids() -> list[str]:
    return [str(row["run_id"]) for row in _rows("SELECT run_id FROM run_state ORDER BY rowid")]


@pytest.fixture(autouse=True)
def _fresh_coordinator() -> None:
    """The coordinator is path-keyed; each test gets its own database."""
    runtime_primary.reset_run_coordinator()
    run_context.set_current_run_id("")
    yield
    # Engine lifecycle tests that call the private creation helper directly do
    # not run the production close/finally path, so they must not leak the
    # active run into later tests.
    run_context.set_current_run_id("")
    runtime_primary.reset_run_coordinator()


def test_restarted_cycle_adopts_the_run_it_left_behind(
    temp_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine()

    # A previous process left a NON-terminal run for the same identity.
    existing = _coordinator().create_run(
        goal=GOAL,
        requirements=["passo-1"],
        session_id=SESSION,
        user_id="alice",
    )
    _coordinator().transition(existing.run_id, RunState.PLANNING, reason="planned before restart")
    monkeypatch.setattr(runtime_primary, "find_run_for_identity", lambda **_: existing)

    first = engine._run_lifecycle_for(goal=GOAL, session_id=SESSION, user_id="alice")

    assert first is not None
    assert first.run_id == existing.run_id

    # Dropping the in-memory mirror is the "the process restarted" case: the
    # engine has to re-adopt from the ledger instead of forking a second run.
    engine._forget_run_lifecycle(SESSION)
    second = engine._run_lifecycle_for(goal=GOAL, session_id=SESSION, user_id="alice")

    assert second is not None
    assert second.run_id == first.run_id
    assert _run_ids() == [existing.run_id], "adoption must never create a second run"

    record = _coordinator().get_run(first.run_id)
    assert record is not None
    assert record.state is RunState.RUNNING
    assert record.stop_reason == ADOPTED_RUN_REASON
    assert record.goal == GOAL


def test_an_already_running_run_is_adopted_without_an_illegal_move(
    temp_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RUNNING → RUNNING is refused by the state machine; adoption is not."""
    engine = _engine()
    existing = _coordinator().create_run(
        goal=GOAL, requirements=["p"], session_id=SESSION, user_id="alice"
    )
    _coordinator().transition(existing.run_id, RunState.PLANNING, reason="planned")
    _coordinator().transition(existing.run_id, RunState.RUNNING, reason="already executing")
    monkeypatch.setattr(runtime_primary, "find_run_for_identity", lambda **_: existing)

    lifecycle = engine._run_lifecycle_for(goal=GOAL, session_id=SESSION, user_id="alice")

    assert lifecycle is not None
    assert lifecycle.run_id == existing.run_id
    assert _run_ids() == [existing.run_id]
    record = _coordinator().get_run(lifecycle.run_id)
    assert record is not None
    assert record.state is RunState.RUNNING


def test_a_terminal_run_is_never_adopted(
    temp_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finished goal starts fresh; a completed run must not be resurrected."""
    engine = _engine()
    finished = _coordinator().create_run(
        goal=GOAL, requirements=["p"], session_id=SESSION, user_id="alice"
    )
    _coordinator().transition(finished.run_id, RunState.PLANNING, reason="planned")
    _coordinator().transition(finished.run_id, RunState.RUNNING, reason="execution")
    _coordinator().transition(finished.run_id, RunState.COMPLETED, reason="done")
    monkeypatch.setattr(runtime_primary, "find_run_for_identity", lambda **_: None)

    lifecycle = engine._run_lifecycle_for(goal=GOAL, session_id=SESSION, user_id="alice")

    assert lifecycle is not None
    assert lifecycle.run_id != finished.run_id
    assert len(_run_ids()) == 2


def test_no_matching_run_creates_a_new_one(
    temp_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine()
    monkeypatch.setattr(runtime_primary, "find_run_for_identity", lambda **_: None)

    lifecycle = engine._run_lifecycle_for(
        goal="Objetivo novo", session_id=SESSION, user_id="alice"
    )

    assert lifecycle is not None
    record = _coordinator().get_run(lifecycle.run_id)
    assert record is not None
    assert record.goal == "Objetivo novo"
    assert record.state is RunState.RUNNING
    assert _run_ids() == [lifecycle.run_id]


def test_legacy_engine_run_is_owned_and_adopted_only_within_user_scope(
    temp_db: None,
) -> None:
    engine = _engine()
    coordinator = _coordinator()
    other_users_run = coordinator.create_run(
        goal=GOAL,
        requirements=["passo-bob"],
        session_id=SESSION,
        user_id="bob",
    )
    coordinator.transition(
        other_users_run.run_id,
        RunState.PLANNING,
        reason="planned by another user",
    )

    try:
        lifecycle = engine._run_lifecycle_for(
            goal=GOAL,
            session_id=SESSION,
            user_id="alice",
        )

        assert lifecycle is not None
        assert lifecycle.run_id != other_users_run.run_id
        record = coordinator.get_run(lifecycle.run_id)
        assert record is not None
        assert record.user_id == "alice"
        assert [item.run_id for item in coordinator.find_resumable_runs(user_id="alice")] == [
            lifecycle.run_id
        ]
        bob_runs = coordinator.find_resumable_runs(user_id="bob")
        assert [item.run_id for item in bob_runs] == [other_users_run.run_id]
        assert bob_runs[0].user_id == "bob"
    finally:
        # `_run_lifecycle_for` installs the active-run ContextVar; production
        # callers clean its token in `_close_autonomous_run`'s finally path.
        engine._close_autonomous_run(SESSION)


def test_ownerless_engine_request_does_not_adopt_an_authenticated_run(
    temp_db: None,
) -> None:
    engine = _engine()
    coordinator = _coordinator()
    another_users_run = coordinator.create_run(
        goal=GOAL,
        requirements=["step"],
        session_id=SESSION,
        user_id="alice",
    )
    coordinator.transition(
        another_users_run.run_id,
        RunState.PLANNING,
        reason="owned by alice",
    )

    try:
        lifecycle = engine._run_lifecycle_for(goal=GOAL, session_id=SESSION)

        assert lifecycle is not None
        assert lifecycle.run_id != another_users_run.run_id
        record = coordinator.get_run(lifecycle.run_id)
        assert record is not None
        assert record.user_id == ""
        assert [item.run_id for item in coordinator.find_resumable_runs(user_id="alice")] == [
            another_users_run.run_id
        ]
    finally:
        engine._close_autonomous_run(SESSION)


def test_execute_plan_persists_the_authenticated_owner(temp_db: None) -> None:
    engine = _engine()
    plan = ExecutionPlan.from_steps(
        title="Owned plan",
        description="The durable run must keep its authenticated owner",
        steps=[],
        session_id=SESSION,
    )
    plan.plan_id = "plan-owned"
    plan.approved = True

    class FakePlanExecutor:
        async def execute(self, *_args: Any, **_kwargs: Any) -> tuple[SimpleNamespace, None]:
            return (
                SimpleNamespace(
                    state=OrchestrationState.COMPLETED,
                    errors=[],
                    task_results={},
                ),
                None,
            )

    engine._plan_executor = FakePlanExecutor()  # type: ignore[assignment]

    asyncio.run(
        engine.execute_plan(
            plan,
            SESSION,
            auto_approve=True,
            user_id="alice",
        )
    )

    owned_runs = _coordinator().find_resumable_runs(user_id="alice")
    assert len(owned_runs) == 1
    assert owned_runs[0].user_id == "alice"
    assert owned_runs[0].session_id == SESSION


def test_a_failing_lookup_degrades_to_creating_a_new_run(
    temp_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Durability being unavailable must never break the orchestration."""
    engine = _engine()

    def explode(**_kwargs: Any) -> None:
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(runtime_primary, "find_run_for_identity", explode)

    lifecycle = engine._run_lifecycle_for(
        goal="objetivo resiliente", session_id=SESSION, user_id="alice"
    )

    assert lifecycle is not None
    assert lifecycle.run_id
    assert _run_ids() == [lifecycle.run_id]


def test_the_in_memory_mirror_still_wins(temp_db: None) -> None:
    """A session already holding a mirror is served from it, ledger or not."""
    engine = _engine()
    first = engine._run_lifecycle_for(goal=GOAL, session_id=SESSION)
    assert first is not None

    # A crashed process left a second, non-terminal run for the same identity:
    # the live mirror still owns the session, so nothing is re-adopted.
    other = _coordinator().create_run(goal=GOAL, requirements=["p"], session_id=SESSION)
    _coordinator().transition(other.run_id, RunState.PLANNING, reason="left behind")

    second = engine._run_lifecycle_for(goal=GOAL, session_id=SESSION)

    assert second is first
    assert second.run_id != other.run_id
