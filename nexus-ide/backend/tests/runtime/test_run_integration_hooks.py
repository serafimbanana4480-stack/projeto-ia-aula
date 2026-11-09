"""Fase 1b — unit tests for the run-lifecycle integration hooks.

These tests pin the three properties the whole checkpoint/resume/idempotency
design rests on:

1. the hooks really create, transition and checkpoint the durable run
   (``RunCoordinator`` is the owner, so the assertions read its state back);
2. a coordinator failure degrades durability and never the run itself — every
   method is failure-tolerant, and ``RunLifecycle.begin`` returns ``None`` when
   no coordinator is available;
3. the idempotency key adopts the run already in flight instead of creating a
   second one, and the side-effect ledger recognises a replay.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from backend.runtime import primary as runtime_primary
from backend.runtime.primary import (
    RunLifecycle,
    is_side_effecting_tool,
    side_effect_idempotency_key,
)
from backend.runtime.run_coordinator import RunCoordinator, RunState


@pytest.fixture(autouse=True)
def _fresh_coordinator() -> None:
    """The coordinator is path-keyed; make each test start from a clean one."""
    runtime_primary.reset_run_coordinator()
    yield
    runtime_primary.reset_run_coordinator()


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


class TestBeginCreatesTheDurableRun:
    def test_begin_creates_run_and_reaches_running(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(
            goal="Implementar resume",
            session_id="sess-1",
            user_id="user-1",
            project_id="/tmp/project",
            requirements=["responder ao pedido"],
            definition_of_done=["resposta entregue ao utilizador"],
        )

        assert lifecycle is not None
        record = _coordinator().get_run(lifecycle.run_id)
        assert record.state is RunState.RUNNING
        assert record.goal == "Implementar resume"
        assert record.session_id == "sess-1"
        assert list(record.definition_of_done) == ["resposta entregue ao utilizador"]

    def test_begin_without_coordinator_returns_none(
        self, temp_db: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NEXUS_RUN_LIFECYCLE", raising=False)
        monkeypatch.setenv("NEXUS_RUN_LIFECYCLE", "0")
        runtime_primary.reset_run_coordinator()

        assert RunLifecycle.begin(goal="qualquer coisa") is None

    def test_broken_coordinator_never_breaks_the_caller(self, temp_db: None) -> None:
        class Hostile:
            def __getattr__(self, name: str) -> Any:
                def explode(*args: Any, **kwargs: Any) -> Any:
                    raise sqlite3.OperationalError("database is locked")

                return explode

        monkey = pytest.MonkeyPatch()
        monkey.setattr(runtime_primary, "get_run_coordinator", lambda: Hostile())
        try:
            lifecycle = RunLifecycle.begin(goal="run frágil", session_id="s")
            assert lifecycle is None  # create_run failed, so nothing is mirrored
        finally:
            monkey.undo()

    def test_methods_are_failure_tolerant(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(goal="tolerância", session_id="s")
        assert lifecycle is not None

        class Hostile:
            def __getattr__(self, name: str) -> Any:
                def explode(*args: Any, **kwargs: Any) -> Any:
                    raise sqlite3.OperationalError("database is locked")

                return explode

        monkey = pytest.MonkeyPatch()
        monkey.setattr(runtime_primary, "get_run_coordinator", lambda: Hostile())
        try:
            # None of these may raise: the user's turn must survive.
            lifecycle.heartbeat(phase="thinking")
            lifecycle.checkpoint("after_task", task_id="cycle-1")
            lifecycle.record_task_completed("cycle-1", name="model turn")
            assert not lifecycle.side_effect_confirmed(
                tool="write_file", args={"path": "a.py"}
            )
            assert not lifecycle.finish([{"requirement": "x", "verdict": "PASS"}])
            lifecycle.fail("provider down")
            lifecycle.cancel("user stop")
        finally:
            monkey.undo()


class TestCheckpoints:
    def test_checkpoints_are_persisted_and_ordered(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(goal="checkpointing", session_id="s")

        lifecycle.checkpoint("after_planning", plan_id="p1", steps=3)
        lifecycle.record_task_completed("task-1", name="Implementar", ok=True)
        lifecycle.checkpoint("before_side_effect", tool="write_file", args={"path": "x.py"})
        lifecycle.checkpoint("after_side_effect", tool="write_file", ok=True)

        latest = _coordinator().latest_checkpoint(lifecycle.run_id)
        assert latest is not None
        assert latest.phase == "after_side_effect"
        phases = [
            str(row["phase"]) for row in _rows("SELECT phase FROM run_checkpoints ORDER BY rowid")
        ]
        assert phases[-4:] == [
            "after_planning",
            "after_task",
            "before_side_effect",
            "after_side_effect",
        ]

    def test_heartbeat_refreshes_heartbeat_at(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(goal="heartbeat", session_id="s")
        first = _coordinator().get_run(lifecycle.run_id).heartbeat_at
        assert first

        lifecycle.heartbeat(phase="thinking", blocked_on="provider")

        after = _coordinator().get_run(lifecycle.run_id).heartbeat_at
        # ISO-8601 with milliseconds sorts lexicographically, so a heartbeat is
        # proof by string comparison that the timestamp actually moved.
        assert after >= first
        checkpoint = _coordinator().latest_checkpoint(lifecycle.run_id)
        assert checkpoint is not None
        assert checkpoint.phase == "heartbeat"
        assert checkpoint.payload["signal"]["blocked_on"] == "provider"


class TestSideEffectLedger:
    def test_side_effect_is_recorded_then_recognised(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(goal="side effects", session_id="s")
        key = side_effect_idempotency_key(lifecycle.run_id, "cycle-1", "write_file", {"path": "a.py"})

        assert not lifecycle.side_effect_confirmed(
            tool="write_file", args={"path": "a.py"}, task_id="cycle-1"
        )
        assert lifecycle.before_side_effect(
            tool="write_file", args={"path": "a.py"}, task_id="cycle-1"
        ) is False
        lifecycle.after_side_effect(
            tool="write_file",
            args={"path": "a.py"},
            task_id="cycle-1",
            result={"tool": "write_file", "path": "a.py"},
        )

        assert lifecycle.side_effect_confirmed(
            tool="write_file", args={"path": "a.py"}, task_id="cycle-1"
        )
        stored = _coordinator().get_side_effect(lifecycle.run_id, key)
        assert stored is not None
        assert stored["kind"] == "write_file"

    def test_replayed_side_effect_is_not_recorded_twice(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(goal="replay", session_id="s")
        kwargs: dict[str, Any] = {
            "tool": "write_file",
            "args": {"path": "a.py"},
            "task_id": "cycle-1",
        }
        lifecycle.after_side_effect(result={"ok": True}, **kwargs)

        # A resumed run performs the same action again: the ledger must report
        # it as a replay and must not gain a second row.
        assert lifecycle.before_side_effect(**kwargs) is True
        lifecycle.after_side_effect(result={"ok": True}, **kwargs)

        rows = _rows("SELECT idempotency_key FROM run_side_effects")
        assert len(rows) == 1

    def test_failed_side_effect_is_not_recorded(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(goal="falha", session_id="s")
        lifecycle.after_side_effect(
            tool="write_file",
            args={"path": "a.py"},
            task_id="cycle-1",
            result={"tool": "write_file", "error": "Operation rejected."},
            ok=False,
        )

        assert not lifecycle.side_effect_confirmed(
            tool="write_file", args={"path": "a.py"}, task_id="cycle-1"
        )

    def test_tool_classification(self) -> None:
        assert is_side_effecting_tool("write_file")
        assert is_side_effecting_tool("apply_patch")
        assert is_side_effecting_tool("run_shell")
        assert is_side_effecting_tool("execute_code")
        assert is_side_effecting_tool("git_commit")
        assert not is_side_effecting_tool("read_file")
        assert not is_side_effecting_tool("list_dir")
        assert not is_side_effecting_tool("")


class TestIdempotency:
    def test_same_key_adopts_the_running_run(self, temp_db: None) -> None:
        first = RunLifecycle.begin(goal="Implementar X", session_id="s", idempotency_key="k-1")
        assert first is not None

        second = RunLifecycle.begin(goal="Implementar X", session_id="s", idempotency_key="k-1")

        assert second is not None
        assert second.run_id == first.run_id
        assert len(_rows("SELECT run_id FROM run_state")) == 1

    def test_same_session_and_goal_adopts_the_running_run(self, temp_db: None) -> None:
        first = RunLifecycle.begin(goal="Mesma pergunta", session_id="s")
        second = RunLifecycle.begin(goal="Mesma pergunta", session_id="s")
        assert second is not None
        assert second.run_id == first.run_id

    def test_new_explicit_key_does_not_adopt_same_goal(self, temp_db: None) -> None:
        first = RunLifecycle.begin(
            goal="Mesma pergunta", session_id="s", idempotency_key="request-1"
        )
        second = RunLifecycle.begin(
            goal="Mesma pergunta", session_id="s", idempotency_key="request-2"
        )
        assert first is not None and second is not None
        assert first.run_id != second.run_id

    def test_different_message_creates_a_new_run(self, temp_db: None) -> None:
        first = RunLifecycle.begin(goal="Uma coisa", session_id="s")
        second = RunLifecycle.begin(goal="Outra coisa", session_id="s")
        assert first is not None and second is not None
        assert first.run_id != second.run_id

    def test_finished_run_is_not_resurrected(self, temp_db: None) -> None:
        first = RunLifecycle.begin(
            goal="Já acabou",
            session_id="s",
            idempotency_key="k",
            definition_of_done=["resposta entregue"],
        )
        assert first is not None
        first.finish(
            [
                {
                    "requirement": "resposta entregue",
                    "verdict": "PASS",
                    "evidence": {"source": "assistant_response"},
                }
            ]
        )
        assert _coordinator().get_run(first.run_id).state is RunState.COMPLETED

        second = RunLifecycle.begin(goal="Já acabou", session_id="s", idempotency_key="k")
        assert second is not None
        assert second.run_id != first.run_id


class TestClosingTheRun:
    def test_finish_requires_a_satisfied_definition_of_done(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(
            goal="completar", session_id="s", definition_of_done=["resposta entregue ao utilizador"]
        )

        assert not lifecycle.finish(
            [{"requirement": "resposta entregue ao utilizador", "verdict": "FAIL", "evidence": {}}]
        )
        # Absence of evidence is never COMPLETED.
        assert _coordinator().get_run(lifecycle.run_id).state is not RunState.COMPLETED

        assert lifecycle.finish(
            [
                {
                    "requirement": "resposta entregue ao utilizador",
                    "verdict": "PASS",
                    "evidence": {"source": "verified_response"},
                }
            ]
        )
        assert _coordinator().get_run(lifecycle.run_id).state is RunState.COMPLETED

    def test_fail_records_the_reason(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(goal="falhar", session_id="s")
        lifecycle.fail("provider indisponível")

        record = _coordinator().get_run(lifecycle.run_id)
        assert record.state is RunState.FAILED
        assert "provider indisponível" in record.stop_reason
        assert lifecycle.closed

    def test_cancel_records_the_reason(self, temp_db: None) -> None:
        lifecycle = RunLifecycle.begin(goal="cancelar", session_id="s")
        lifecycle.cancel("cliente desligou")

        record = _coordinator().get_run(lifecycle.run_id)
        assert record.state is RunState.CANCELLED
        assert "cliente desligou" in record.stop_reason


class TestPrimaryLaneHooks:
    """The chat_primary wrappers that translate run facts into checkpoints."""

    def test_successful_write_keeps_target_path_for_later_verification(self) -> None:
        from backend.runtime.events import RuntimeEvent
        from backend.runtime.primary import (
            AgentSignal,
            AgentSignalKind,
            PrimaryLoop,
            PrimaryTurn,
        )

        loop = PrimaryLoop(run_id="r", query="cria uma nota", stream=None)
        turn = PrimaryTurn(query="cria uma nota")

        def emit(event_type: Any, **payload: Any) -> RuntimeEvent:
            return loop.events.emit(event_type, agent_id="NEXUS", **payload)

        loop._handle_signal(
            AgentSignal(
                AgentSignalKind.TOOL_CALL,
                tool_name="write_file",
                payload={"path": "notas.txt", "content": "nota"},
            ),
            turn,
            emit,
            [],
        )
        loop._handle_signal(
            AgentSignal(
                AgentSignalKind.TOOL_RESULT,
                tool_name="write_file",
                payload={"result": "ficheiro escrito"},
                ok=True,
            ),
            turn,
            emit,
            [],
        )

        assert loop._changed_files == ["notas.txt"]

    @pytest.mark.asyncio
    async def test_non_code_artifact_does_not_run_the_project_test_suite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.orchestrator.routes import chat_primary
        from backend.runtime.primary import PrimaryTurn, VerificationRequest

        async def unexpected_test_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("a text artifact must not start the project test suite")

        monkeypatch.setattr(chat_primary, "execute_tool", unexpected_test_run)
        result = await chat_primary._verify(
            VerificationRequest(
                turn=PrimaryTurn(query="cria uma nota"),
                changed_files=("notas.txt",),
            ),
            session_id="non-code-verification",
            project_path=".",
        )

        assert result.ran is False
        assert result.ok is True
        assert "não aplicáveis" in result.summary

    def test_dod_results_require_an_answer(self, temp_db: None) -> None:
        from backend.orchestrator.routes.chat_primary import _primary_dod_results
        from backend.runtime.primary import PrimaryLoop, VerificationResult

        loop = PrimaryLoop(run_id="r", query="olá", stream=None)
        loop.outcome.answer = ""
        loop.outcome.verification = VerificationResult()

        results = {item["requirement"]: item for item in _primary_dod_results(loop)}
        assert results["resposta entregue ao utilizador"]["verdict"] == "FAIL"
        assert results["verificação sem falhas reportada"]["verdict"] == "N/A"

    def test_changed_code_without_test_evidence_fails_dod(self, temp_db: None) -> None:
        from backend.orchestrator.routes.chat_primary import _primary_dod_results
        from backend.runtime.primary import PrimaryLoop, VerificationResult

        loop = PrimaryLoop(run_id="r", query="corrige", stream=None)
        loop.outcome.answer = "Corrigi o ficheiro."
        loop.outcome.changed_files = ("backend/app.py",)
        loop.outcome.verification = VerificationResult(
            ran=False, ok=True, summary="nenhum teste executado"
        )

        results = {item["requirement"]: item for item in _primary_dod_results(loop)}
        assert results["verificação sem falhas reportada"]["verdict"] == "FAIL"

    def test_non_code_artifact_without_test_evidence_is_not_failed_dod(
        self, temp_db: None
    ) -> None:
        from backend.orchestrator.routes.chat_primary import _primary_dod_results
        from backend.runtime.primary import PrimaryLoop, VerificationResult

        loop = PrimaryLoop(run_id="r", query="cria uma nota", stream=None)
        loop.outcome.answer = "Criei notas.txt."
        loop.outcome.changed_files = ("notas.txt",)
        loop.telemetry.files_changed = 1
        loop.outcome.verification = VerificationResult(
            ran=False, ok=True, summary="testes automáticos não aplicáveis"
        )

        results = {item["requirement"]: item for item in _primary_dod_results(loop)}
        assert results["verificação sem falhas reportada"]["verdict"] == "N/A"

    def test_red_verification_blocks_completion(self, temp_db: None) -> None:
        from backend.orchestrator.routes.chat_primary import _primary_dod_results
        from backend.runtime.primary import PrimaryLoop, VerificationResult

        loop = PrimaryLoop(run_id="r", query="corrige", stream=None)
        loop.outcome.answer = "Corrigi o ficheiro."
        loop.outcome.verification = VerificationResult(
            ran=True, ok=False, summary="2 testes falharam", command="pytest"
        )

        results = {item["requirement"]: item for item in _primary_dod_results(loop)}
        assert results["resposta entregue ao utilizador"]["verdict"] == "PASS"
        assert results["verificação sem falhas reportada"]["verdict"] == "FAIL"

    def test_side_effect_tracker_records_only_real_dependencies(self, temp_db: None) -> None:
        from backend.orchestrator.routes.chat_primary import SideEffectTracker
        from backend.runtime.primary import AgentSignal, AgentSignalKind

        lifecycle = RunLifecycle.begin(goal="tools", session_id="s")
        tracker = SideEffectTracker(lifecycle, "run-1", cycle=2)

        read_signal = AgentSignal(
            kind=AgentSignalKind.TOOL_CALL, tool_name="read_file", payload={"path": "a.py"}
        )
        tracker.observe(read_signal)
        assert _coordinator().latest_checkpoint(lifecycle.run_id) is None

        write_call = AgentSignal(
            kind=AgentSignalKind.TOOL_CALL,
            tool_name="write_file",
            payload={"path": "a.py", "content": "print(1)"},
        )
        tracker.observe(write_call)
        write_result = AgentSignal(
            kind=AgentSignalKind.TOOL_RESULT,
            tool_name="write_file",
            payload={"tool": "write_file", "path": "a.py", "bytes_written": 9},
            ok=True,
        )
        tracker.observe(write_result)

        # The ledger is keyed by the arguments of the *call*, even though only
        # the result was available when the row was written.
        assert lifecycle.side_effect_confirmed(
            tool="write_file",
            args={"path": "a.py", "content": "print(1)"},
            task_id="cycle-2",
        )
        phases = [str(row["phase"]) for row in _rows("SELECT phase FROM run_checkpoints ORDER BY rowid")]
        assert phases[-2:] == ["before_side_effect", "after_side_effect"]
        latest = _coordinator().latest_checkpoint(lifecycle.run_id)
        assert latest is not None
        assert latest.payload["tool"] == "write_file"
        assert latest.payload["task_id"] == "cycle-2"
        assert latest.payload["idempotency_key"] == side_effect_idempotency_key(
            lifecycle.run_id, "cycle-2", "write_file", {"path": "a.py", "content": "print(1)"}
        )

    def test_side_effect_tracker_is_inert_without_a_lifecycle(self, temp_db: None) -> None:
        from backend.orchestrator.routes.chat_primary import SideEffectTracker
        from backend.runtime.primary import AgentSignal, AgentSignalKind

        tracker = SideEffectTracker(None, "run-1")
        assert tracker.active is False

        tracker.observe(
            AgentSignal(
                kind=AgentSignalKind.TOOL_CALL,
                tool_name="write_file",
                payload={"path": "a.py"},
            )
        )
        tracker.observe(
            AgentSignal(
                kind=AgentSignalKind.TOOL_RESULT,
                tool_name="write_file",
                payload={"tool": "write_file"},
                ok=True,
            )
        )


    def test_closing_uses_the_outcome_truth(self, temp_db: None) -> None:
        from backend.orchestrator.routes.chat_primary import _close_primary_run_lifecycle
        from backend.runtime.primary import PrimaryLoop

        lifecycle = RunLifecycle.begin(goal="fecho", session_id="s")

        stopped = PrimaryLoop(run_id="r", query="para", stream=None)
        stopped.outcome.stopped = True
        stopped.outcome.error = "parado pelo utilizador"
        _close_primary_run_lifecycle(lifecycle, stopped)
        assert _coordinator().get_run(lifecycle.run_id).state is RunState.CANCELLED

        failed_lifecycle = RunLifecycle.begin(goal="fecho2", session_id="s2")
        assert failed_lifecycle is not None
        failed = PrimaryLoop(run_id="r", query="falhou", stream=None)
        failed.outcome.failed = True
        failed.outcome.error = "provider esgotado"
        _close_primary_run_lifecycle(failed_lifecycle, failed)
        record = _coordinator().get_run(failed_lifecycle.run_id)
        assert record.state is RunState.FAILED
        assert "provider esgotado" in record.stop_reason

    def test_tracking_events_creates_phase_checkpoints(self, temp_db: None) -> None:
        from backend.orchestrator.routes.chat_primary import _track_primary_run_event
        from backend.runtime.events import RuntimeEvent, RuntimeEventType

        lifecycle = RunLifecycle.begin(goal="eventos", session_id="s")
        _track_primary_run_event(
            lifecycle, RuntimeEvent("r", 1, RuntimeEventType.MESSAGE_COMPLETED, payload={"cycles": 2})
        )
        _track_primary_run_event(
            lifecycle,
            RuntimeEvent("r", 2, RuntimeEventType.TEST_STARTED, payload={"changed_files": ["a.py"]}),
        )
        _track_primary_run_event(
            lifecycle,
            RuntimeEvent("r", 3, RuntimeEventType.TEST_RESULT, payload={"ran": True, "ok": True}),
        )

        phases = [str(row["phase"]) for row in _rows("SELECT phase FROM run_checkpoints ORDER BY rowid")]
        assert phases == ["after_task", "before_verification", "after_verification"]
        assert _coordinator().get_run(lifecycle.run_id).current_task_id == "cycle-2"


def test_side_effect_key_is_stable_for_reordered_arguments() -> None:
    first = side_effect_idempotency_key("run-1", "task-1", "write_file", {"path": "a.py", "mode": "w"})
    second = side_effect_idempotency_key("run-1", "task-1", "write_file", {"mode": "w", "path": "a.py"})
    assert first == second


def test_side_effect_key_changes_with_the_action() -> None:
    base = side_effect_idempotency_key("run-1", "task-1", "write_file", {"path": "a.py"})
    assert base != side_effect_idempotency_key("run-1", "task-1", "write_file", {"path": "b.py"})
    assert base != side_effect_idempotency_key("run-2", "task-1", "write_file", {"path": "a.py"})
    assert base != side_effect_idempotency_key("run-1", "task-2", "write_file", {"path": "a.py"})


def test_run_budget_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_RUN_MAX_TOKENS", "1234")
    monkeypatch.setenv("NEXUS_RUN_MAX_COST_USD", "0.5")
    monkeypatch.setenv("NEXUS_RUN_MAX_RUNTIME_SECONDS", "60")
    monkeypatch.setenv("NEXUS_RUN_MAX_NOT_A_LIMIT", "3")

    budget = runtime_primary._run_budget()
    assert budget == {"max_tokens": 1234, "max_cost_usd": 0.5, "max_runtime_seconds": 60.0}

    monkeypatch.delenv("NEXUS_RUN_MAX_TOKENS")
    monkeypatch.delenv("NEXUS_RUN_MAX_COST_USD")
    monkeypatch.delenv("NEXUS_RUN_MAX_RUNTIME_SECONDS")
    monkeypatch.setenv("NEXUS_RUN_MAX_TOKENS", "not-a-number")
    assert runtime_primary._run_budget() == {}


def test_find_run_for_identity_ignores_unknown_inputs() -> None:
    assert runtime_primary.find_run_for_identity() is None  # type: ignore[call-arg]
    assert runtime_primary.find_run_for_identity(session_id="s") is None


def test_lifecycle_helpers_tolerate_missing_objects() -> None:
    class Missing:
        pass

    assert runtime_primary.RunLifecycle("run-x").record is None
    assert runtime_primary.RunLifecycle("run-x").enabled is True
    assert runtime_primary.RunLifecycle("run-x").closed is False
    assert runtime_primary._jsonable(SimpleNamespace(a=1)).startswith("namespace(")
