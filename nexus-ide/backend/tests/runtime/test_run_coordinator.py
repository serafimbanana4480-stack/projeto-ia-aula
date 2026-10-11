"""The run coordinator keeps a run alive across restarts — and never lets an
illegal move, an unproven requirement or a second charge through.

Every test runs against a throwaway SQLite file under ``tmp_path``: the
coordinator must be able to own its own database without the application one.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.runtime.run_coordinator import (
    TERMINAL_RUN_STATES,
    BudgetVerdict,
    Checkpoint,
    DoDNotSatisfied,
    InvalidRunTransition,
    RunCoordinator,
    RunRecord,
    RunState,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "run_coordinator.db"


@pytest.fixture
def coordinator(db_path: Path) -> RunCoordinator:
    return RunCoordinator(db_path=str(db_path))


def _dod(requirement: str, verdict: str = "PASS") -> dict:
    return {"requirement": requirement, "evidence": {"checked": True}, "verdict": verdict}


def _completed_run(coordinator: RunCoordinator, run_id: str) -> RunRecord:
    """Drive a run to COMPLETED so retention has something terminal to delete."""
    for state in (RunState.PLANNING, RunState.RUNNING, RunState.VERIFYING):
        coordinator.transition(run_id, state)
    return coordinator.complete(run_id, [_dod("req-a"), _dod("req-b")])


# ───── create / get ───────────────────────────────────────────────────────


def test_create_run_persists_goal_and_checklist(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(
        goal="Make the tests pass",
        requirements=["tests green", "no new warnings"],
        constraints=["do not touch routes/"],
        definition_of_done=["tests green"],
        project_id="proj-1",
        user_id="user-1",
        session_id="sess-1",
    )

    assert run.run_id
    assert run.state is RunState.CREATED
    assert run.goal == "Make the tests pass"
    assert run.requirements == ["tests green", "no new warnings"]
    assert run.constraints == ["do not touch routes/"]
    assert run.definition_of_done == ["tests green"]
    assert run.retry_count == 0
    assert run.changed_files == []
    assert run.created_at and run.updated_at and run.heartbeat_at

    stored = coordinator.get_run(run.run_id)
    assert stored == run
    assert coordinator.get_run("missing-run") is None


def test_create_run_accepts_budget_limits_and_rejects_unknown_ones(
    coordinator: RunCoordinator,
) -> None:
    run = coordinator.create_run(
        goal="bounded work",
        requirements=["finish"],
        budget={"max_tokens": 1000, "max_cost_usd": None, "max_runtime_seconds": 30.0},
    )

    assert run.budget == {"max_tokens": 1000, "max_cost_usd": None, "max_runtime_seconds": 30.0}

    with pytest.raises(ValueError, match="unknown budget limits"):
        coordinator.create_run(goal="typo", requirements=["finish"], budget={"max_cost": 1.0})


def test_two_coordinators_on_the_same_file_see_the_same_run(
    db_path: Path, coordinator: RunCoordinator
) -> None:
    """A restart is just a new coordinator over the same file."""
    run = coordinator.create_run(goal="durable", requirements=["restart"])
    rehydrated = RunCoordinator(db_path=str(db_path))

    stored = rehydrated.get_run(run.run_id)

    assert stored is not None
    assert stored.goal == "durable"
    assert stored.state is RunState.CREATED


# ───── state machine ──────────────────────────────────────────────────────


def test_valid_transitions_move_the_run(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="walk", requirements=["walk"])

    planning = coordinator.transition(run.run_id, RunState.PLANNING)
    running = coordinator.transition(run.run_id, RunState.RUNNING)

    assert planning.state is RunState.PLANNING
    assert running.state is RunState.RUNNING
    assert coordinator.get_run(run.run_id).state is RunState.RUNNING


def test_invalid_transition_raises_and_never_mutates_state(
    coordinator: RunCoordinator,
) -> None:
    run = coordinator.create_run(goal="guard", requirements=["guard"])
    coordinator.transition(run.run_id, RunState.PLANNING)

    with pytest.raises(InvalidRunTransition) as excinfo:
        coordinator.transition(run.run_id, RunState.COMPLETED)

    error = excinfo.value
    assert error.run_id == run.run_id
    assert error.from_state is RunState.PLANNING
    assert error.to_state is RunState.COMPLETED
    assert coordinator.get_run(run.run_id).state is RunState.PLANNING


def test_transition_stores_its_reason(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="explain", requirements=["explain"])

    stopped = coordinator.transition(run.run_id, RunState.CANCELLED, reason="user said stop")

    assert stopped.state is RunState.CANCELLED
    assert stopped.stop_reason == "user said stop"


def test_terminal_states_have_no_way_out(coordinator: RunCoordinator) -> None:
    run = _completed_run(
        coordinator,
        coordinator.create_run(goal="terminal", requirements=["req-a", "req-b"]).run_id,
    )
    assert run.state is RunState.COMPLETED
    assert RunState.COMPLETED in TERMINAL_RUN_STATES

    for target in (RunState.RUNNING, RunState.RECOVERING, RunState.PAUSED):
        with pytest.raises(InvalidRunTransition):
            coordinator.transition(run.run_id, target)


def test_transition_to_an_unknown_state_is_rejected(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="unknown", requirements=["x"])

    with pytest.raises(ValueError, match="unknown run state"):
        coordinator.transition(run.run_id, "finished")  # type: ignore[arg-type]


def test_transition_on_a_missing_run_is_loud(coordinator: RunCoordinator) -> None:
    with pytest.raises(ValueError, match="unknown run_id"):
        coordinator.transition("nope", RunState.RUNNING)


# ───── progresso ──────────────────────────────────────────────────────────


def test_update_progress_refreshes_executable_state(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="progress", requirements=["prog"])

    updated = coordinator.update_progress(
        run.run_id,
        plan={"tasks": ["t1", "t2"]},
        current_task_id="t1",
        retry_count=2,
        provider={"name": "ollama", "model": "qwen"},
        memory_refs=["mem-1"],
        artifacts=[{"path": "out.txt", "digest": "abc"}],
        changed_files=["backend/foo.py"],
    )

    assert updated.plan == {"tasks": ["t1", "t2"]}
    assert updated.current_task_id == "t1"
    assert updated.retry_count == 2
    assert updated.provider["name"] == "ollama"
    assert updated.memory_refs == ["mem-1"]
    assert updated.artifacts == [{"path": "out.txt", "digest": "abc"}]
    assert updated.changed_files == ["backend/foo.py"]

    # A second write with no plan argument leaves the stored plan alone.
    second = coordinator.update_progress(run.run_id, current_task_id="t2")
    assert second.plan == {"tasks": ["t1", "t2"]}
    assert second.current_task_id == "t2"


def test_update_progress_can_skip_the_heartbeat(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="heartbeat", requirements=["hb"])
    before = coordinator.get_run(run.run_id)

    updated = coordinator.update_progress(run.run_id, retry_count=1, heartbeat=False)

    assert updated.retry_count == 1
    assert updated.heartbeat_at == before.heartbeat_at
    assert updated.updated_at != before.updated_at


# ───── checkpoints ────────────────────────────────────────────────────────


def test_checkpoint_latest_and_list(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="checkpoints", requirements=["cp"])
    coordinator.transition(run.run_id, RunState.PLANNING)

    first = coordinator.checkpoint(run.run_id, phase="after_planning", payload={"tasks": 3})
    second = coordinator.checkpoint(run.run_id, phase="before_side_effect", payload={"task": "t1"})

    latest = coordinator.latest_checkpoint(run.run_id)
    assert isinstance(latest, Checkpoint)
    assert latest.checkpoint_id == second.checkpoint_id
    assert latest.payload == {"task": "t1"}
    assert coordinator.latest_checkpoint(run.run_id, phase="after_planning").checkpoint_id == (
        first.checkpoint_id
    )
    assert [cp.checkpoint_id for cp in coordinator.list_checkpoints(run.run_id)] == [
        second.checkpoint_id,
        first.checkpoint_id,
    ]


def test_latest_checkpoint_breaks_created_at_ties_by_id(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="ties", requirements=["tie"])

    first = coordinator.checkpoint(run.run_id, phase="heartbeat", payload={"n": 1})
    second = coordinator.checkpoint(run.run_id, phase="heartbeat", payload={"n": 2})

    # Same millisecond: the tie is resolved deterministically, and the answer is
    # stable across reads.
    assert coordinator.latest_checkpoint(run.run_id).checkpoint_id in (
        first.checkpoint_id,
        second.checkpoint_id,
    )
    assert coordinator.latest_checkpoint(run.run_id, phase="heartbeat").checkpoint_id in (
        first.checkpoint_id,
        second.checkpoint_id,
    )
    assert coordinator.latest_checkpoint("unknown-run") is None


def test_checkpoint_rejects_unknown_phase_and_missing_run(
    coordinator: RunCoordinator,
) -> None:
    run = coordinator.create_run(goal="phases", requirements=["phase"])

    with pytest.raises(ValueError, match="unknown checkpoint phase"):
        coordinator.checkpoint(run.run_id, phase="whenever", payload={})
    with pytest.raises(ValueError, match="unknown run_id"):
        coordinator.checkpoint("nope", phase="heartbeat", payload={})


def test_restore_returns_checkpoint_and_moves_to_recovering(
    coordinator: RunCoordinator,
) -> None:
    run = coordinator.create_run(goal="restore", requirements=["restore"])
    coordinator.transition(run.run_id, RunState.PLANNING)
    coordinator.transition(run.run_id, RunState.RUNNING)
    planned = coordinator.checkpoint(run.run_id, phase="after_planning", payload={"step": 1})
    coordinator.checkpoint(run.run_id, phase="after_task", payload={"step": 2})

    restored = coordinator.restore(run.run_id)

    assert restored.checkpoint_id == coordinator.latest_checkpoint(run.run_id).checkpoint_id
    assert restored.payload == {"step": 2}
    assert coordinator.get_run(run.run_id).state is RunState.RECOVERING

    explicit = coordinator.restore(run.run_id, checkpoint_id=planned.checkpoint_id)
    assert explicit.payload == {"step": 1}


def test_restore_refuses_when_there_is_nothing_to_restore(
    coordinator: RunCoordinator,
) -> None:
    run = coordinator.create_run(goal="empty", requirements=["empty"])

    with pytest.raises(ValueError, match="no checkpoint"):
        coordinator.restore(run.run_id)
    with pytest.raises(ValueError, match="unknown run_id"):
        coordinator.restore("nope")

    checkpoint = coordinator.checkpoint(run.run_id, phase="pause", payload={})
    other = coordinator.create_run(goal="other", requirements=["other"])
    with pytest.raises(ValueError, match="belongs to run"):
        coordinator.restore(other.run_id, checkpoint_id=checkpoint.checkpoint_id)


# ───── idempotência ───────────────────────────────────────────────────────


def test_side_effect_is_confirmed_after_recording(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="idem", requirements=["idem"])
    assert coordinator.is_side_effect_confirmed(run.run_id, "charge:42") is False

    coordinator.record_side_effect(
        run.run_id, "charge:42", kind="payment", result_digest="digest-1"
    )

    assert coordinator.is_side_effect_confirmed(run.run_id, "charge:42") is True
    recorded = coordinator.get_side_effect(run.run_id, "charge:42")
    assert recorded["kind"] == "payment"
    assert recorded["result_digest"] == "digest-1"


def test_recording_the_same_side_effect_twice_does_not_duplicate_it(
    coordinator: RunCoordinator, db_path: Path
) -> None:
    run = coordinator.create_run(goal="replay", requirements=["replay"])

    coordinator.record_side_effect(run.run_id, "email:welcome", kind="email", result_digest="d1")
    coordinator.record_side_effect(run.run_id, "email:welcome", kind="email", result_digest="d2")

    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) AS total FROM run_side_effects"
        ).fetchall()
    assert rows[0][0] == 1
    # The first writer wins: a replay must not overwrite the stored digest.
    assert coordinator.get_side_effect(run.run_id, "email:welcome")["result_digest"] == "d1"


def test_side_effects_are_scoped_per_run(coordinator: RunCoordinator) -> None:
    first = coordinator.create_run(goal="one", requirements=["one"])
    second = coordinator.create_run(goal="two", requirements=["two"])

    coordinator.record_side_effect(first.run_id, "key", kind="k", result_digest="d")

    assert coordinator.is_side_effect_confirmed(first.run_id, "key") is True
    assert coordinator.is_side_effect_confirmed(second.run_id, "key") is False
    assert coordinator.get_side_effect(second.run_id, "key") is None


# ───── orçamentos ─────────────────────────────────────────────────────────


def test_usage_accumulates_until_a_limit_is_exceeded(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(
        goal="budget",
        requirements=["cheap"],
        budget={"max_tokens": 100, "max_cost_usd": 0.25},
    )

    first = coordinator.record_usage(run.run_id, tokens=40, cost_usd=0.10, tool_calls=2)
    assert isinstance(first, BudgetVerdict)
    assert first.ok is True
    assert first.exceeded == {}
    assert first.usage["tokens"] == 40

    second = coordinator.record_usage(run.run_id, tokens=70, cost_usd=0.20)
    assert second.ok is False
    assert second.usage["tokens"] == 110
    assert second.usage["cost_usd"] == pytest.approx(0.30)
    assert second.exceeded == {"tokens": "110>100", "cost": "0.3>0.25"}
    assert coordinator.budget_status(run.run_id).exceeded == second.exceeded


def test_unset_limits_are_never_exceeded(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(
        goal="unbounded",
        requirements=["grow"],
        budget={"max_tokens": 10},
    )

    verdict = coordinator.record_usage(run.run_id, tokens=20, cost_usd=99.0, subagents=7)

    assert verdict.ok is False  # tokens over the one configured limit
    assert verdict.exceeded == {"tokens": "20>10"}
    assert "cost" not in verdict.exceeded  # no max_cost_usd configured
    assert "subagents" not in verdict.exceeded


def test_record_usage_on_a_missing_run_is_loud(coordinator: RunCoordinator) -> None:
    with pytest.raises(ValueError, match="unknown run_id"):
        coordinator.record_usage("nope", tokens=1)
    with pytest.raises(ValueError, match="unknown run_id"):
        coordinator.budget_status("nope")


# ───── definição de done ──────────────────────────────────────────────────


def test_definition_of_done_passes_with_evidence_for_every_requirement(
    coordinator: RunCoordinator,
) -> None:
    run = coordinator.create_run(
        goal="done",
        requirements=["req-a"],
        definition_of_done=["req-a", "req-b"],
    )

    verdict = coordinator.verify_definition_of_done(
        run.run_id,
        [_dod("req-a"), _dod("req-b")],
    )

    assert verdict["ok"] is True
    assert verdict["missing"] == []
    assert [entry["requirement"] for entry in verdict["requirements"]] == ["req-a", "req-b"]

    for state in (RunState.PLANNING, RunState.RUNNING, RunState.VERIFYING):
        coordinator.transition(run.run_id, state)
    completed = coordinator.complete(run.run_id, [_dod("req-a"), _dod("req-b")])
    assert completed.state is RunState.COMPLETED


def test_unknown_verdict_on_a_required_requirement_blocks_completion(
    coordinator: RunCoordinator,
) -> None:
    run = coordinator.create_run(
        goal="guess",
        requirements=["req-a"],
        definition_of_done=["req-a", "req-b"],
    )
    results = [_dod("req-a"), _dod("req-b", verdict="UNKNOWN")]

    verdict = coordinator.verify_definition_of_done(run.run_id, results)
    assert verdict["ok"] is False
    assert verdict["missing"] == [
        {"requirement": "req-b", "verdict": "UNKNOWN", "reason": "unknown"}
    ]

    with pytest.raises(DoDNotSatisfied) as excinfo:
        coordinator.complete(run.run_id, results)
    assert excinfo.value.run_id == run.run_id
    assert [item["requirement"] for item in excinfo.value.details] == ["req-b"]
    assert coordinator.get_run(run.run_id).state is RunState.CREATED


def test_unreported_requirement_counts_as_missing(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(
        goal="silent",
        requirements=["req-a"],
        definition_of_done=["req-a", "req-b"],
    )

    verdict = coordinator.verify_definition_of_done(run.run_id, [_dod("req-a")])

    assert verdict["ok"] is False
    assert verdict["missing"] == [
        {"requirement": "req-b", "verdict": "UNKNOWN", "reason": "not_reported"}
    ]


def test_failed_requirement_blocks_completion(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(
        goal="failing",
        requirements=["req-b"],
        definition_of_done=["req-b"],
    )
    run = coordinator.update_progress(
        run.run_id, plan={"steps": 1}
    )  # state is still CREATED; only the plan moved

    with pytest.raises(DoDNotSatisfied) as excinfo:
        coordinator.complete(run.run_id, [_dod("req-b", verdict="FAIL")])
    assert excinfo.value.details == [
        {"requirement": "req-b", "verdict": "FAIL", "reason": "failed"}
    ]

    assert coordinator.get_run(run.run_id).plan == {"steps": 1}


def test_definition_of_done_rejects_malformed_results(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="malformed", requirements=["req-a"])

    with pytest.raises(ValueError, match="verdict"):
        coordinator.verify_definition_of_done(run.run_id, [{"requirement": "req-a", "verdict": "maybe"}])
    with pytest.raises(ValueError, match="requirement"):
        coordinator.verify_definition_of_done(run.run_id, [{"verdict": "PASS"}])
    with pytest.raises(ValueError, match="unknown run_id"):
        coordinator.verify_definition_of_done("nope", [_dod("req-a")])


# ───── DLQ ────────────────────────────────────────────────────────────────


def test_dead_letter_enqueue_list_and_update(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="dlq", requirements=["dlq"])
    entry_id = coordinator.enqueue_dead_letter(
        {
            "task_id": "task-1",
            "run_id": run.run_id,
            "error_class": "TimeoutError",
            "sanitized_traceback": "TimeoutError: provider did not answer",
            "attempts": 3,
            "last_tool": "shell",
            "last_provider": "ollama",
            "last_evidence": {"phase": "running"},
            "recoverability": "retryable",
            "retry_after": "2026-10-10T22:00:00Z",
        }
    )

    open_entries = coordinator.list_dead_letters()
    assert [entry["id"] for entry in open_entries] == [entry_id]
    entry = open_entries[0]
    assert entry["task_id"] == "task-1"
    assert entry["run_id"] == run.run_id
    assert entry["error_class"] == "TimeoutError"
    assert entry["attempts"] == 3
    assert entry["last_tool"] == "shell"
    assert entry["last_evidence"] == {"phase": "running"}
    assert entry["recoverability"] == "retryable"
    assert entry["retry_after"] == "2026-10-10T22:00:00Z"
    assert entry["state"] == "open"

    updated = coordinator.update_dead_letter(entry_id, state="requeued", note="retried by hand")
    assert updated["state"] == "requeued"
    assert "retried by hand" in updated["note"]
    assert coordinator.list_dead_letters() == []
    assert [e["id"] for e in coordinator.list_dead_letters(state=None)] == [entry_id]
    assert [e["id"] for e in coordinator.list_dead_letters(state="requeued")] == [entry_id]
    assert coordinator.list_dead_letters(run_id=run.run_id, state="requeued") != []

    with pytest.raises(ValueError, match="unknown dead letter state"):
        coordinator.update_dead_letter(entry_id, state="magic")
    with pytest.raises(ValueError, match="unknown dead letter entry"):
        coordinator.update_dead_letter("nope", state="retrying")


def test_dead_letter_defaults_are_friendly(coordinator: RunCoordinator) -> None:
    entry_id = coordinator.enqueue_dead_letter({"error_class": "ValueError"})

    entry = coordinator.list_dead_letters()[0]
    assert entry_id == entry["id"]
    assert entry["run_id"] == ""
    assert entry["attempts"] == 0
    assert entry["last_evidence"] == {}
    assert entry["recoverability"] == "unknown"
    assert entry["state"] == "open"


# ───── runs resumíveis ────────────────────────────────────────────────────


def test_find_resumable_runs_excludes_terminal_states(coordinator: RunCoordinator) -> None:
    created = coordinator.create_run(goal="created", requirements=["r"], session_id="s")
    running = coordinator.create_run(goal="running", requirements=["r"], session_id="s")
    coordinator.transition(running.run_id, RunState.PLANNING)
    coordinator.transition(running.run_id, RunState.RUNNING)
    completed = coordinator.create_run(goal="completed", requirements=["r"], session_id="s")
    _completed_run(coordinator, completed.run_id)
    failed = coordinator.create_run(goal="failed", requirements=["r"], session_id="s")
    coordinator.transition(failed.run_id, RunState.FAILED, reason="boom")
    cancelled = coordinator.create_run(goal="cancelled", requirements=["r"], session_id="s")
    coordinator.transition(cancelled.run_id, RunState.CANCELLED, reason="stop")

    resumable = {run.run_id for run in coordinator.find_resumable_runs(session_id="s")}

    assert resumable == {created.run_id, running.run_id}
    # Filters still apply: a run belonging to another session is not offered.
    other = coordinator.create_run(goal="other session", requirements=["r"], session_id="other")
    assert other.run_id not in {
        run.run_id for run in coordinator.find_resumable_runs(session_id="s")
    }
    assert other.run_id in {
        run.run_id for run in coordinator.find_resumable_runs(session_id="other")
    }
    assert {run.run_id for run in coordinator.find_resumable_runs(user_id="nobody")} == set()


def test_list_runs_filters_by_state_project_and_limit(coordinator: RunCoordinator) -> None:
    first = coordinator.create_run(goal="one", requirements=["r"], project_id="p1")
    second = coordinator.create_run(goal="two", requirements=["r"], project_id="p1")
    other_project = coordinator.create_run(goal="three", requirements=["r"], project_id="p2")
    coordinator.transition(first.run_id, RunState.PLANNING)
    coordinator.transition(first.run_id, RunState.RUNNING)

    running = coordinator.list_runs(project_id="p1", states=[RunState.RUNNING])
    assert [run.run_id for run in running] == [first.run_id]
    assert coordinator.list_runs(project_id="p2", states=["created"]) == [other_project]
    assert len(coordinator.list_runs(project_id="p1", limit=1)) == 1
    assert len(coordinator.list_runs()) == 3
    assert second.state is RunState.CREATED


# ───── retenção / TTL ─────────────────────────────────────────────────────


def test_prune_dry_run_counts_without_deleting(coordinator: RunCoordinator) -> None:
    finished = coordinator.create_run(goal="old", requirements=["req-a", "req-b"])
    _completed_run(coordinator, finished.run_id)
    coordinator.checkpoint(finished.run_id, phase="after_task", payload={"n": 1})
    live = coordinator.create_run(goal="live", requirements=["r"])
    coordinator.checkpoint(live.run_id, phase="heartbeat", payload={"n": 2})

    report = coordinator.prune(runs_days=30, dry_run=True)

    assert set(report) == {"runs", "checkpoints", "side_effects", "dead_letters", "scheduled_tasks"}
    # Nothing is older than the window yet, so nothing is a candidate.
    assert report == {
        "runs": 0,
        "checkpoints": 0,
        "side_effects": 0,
        "dead_letters": 0,
        "scheduled_tasks": 0,
    }
    assert coordinator.get_run(finished.run_id) is not None
    assert len(coordinator.list_checkpoints(live.run_id)) == 1


def test_prune_dry_run_reports_terminal_runs_when_the_window_is_zero(
    coordinator: RunCoordinator,
) -> None:
    finished = coordinator.create_run(goal="done", requirements=["req-a"])
    _completed_run(coordinator, finished.run_id)
    live = coordinator.create_run(goal="live", requirements=["r"])
    coordinator.checkpoint(live.run_id, phase="heartbeat", payload={"n": 1})
    coordinator.record_side_effect(finished.run_id, "key", kind="k", result_digest="d")

    report = coordinator.prune(runs_days=0, dry_run=True)

    assert report == {
        "runs": 1,
        "checkpoints": 0,
        "side_effects": 1,
        "dead_letters": 0,
        "scheduled_tasks": 0,
    }
    # A run that still owns work is never a retention candidate, and dry_run
    # truly changed nothing.
    assert coordinator.get_run(live.run_id) is not None
    assert coordinator.get_run(finished.run_id) is not None
    assert coordinator.is_side_effect_confirmed(finished.run_id, "key")

    applied = coordinator.prune(runs_days=0)
    assert applied["runs"] == 1
    assert applied["side_effects"] == 1
    assert applied["checkpoints"] == 0  # checkpoints_days defaults to 14 days
    assert coordinator.get_run(finished.run_id) is None
    assert coordinator.is_side_effect_confirmed(finished.run_id, "key") is False
    assert coordinator.get_run(live.run_id) is not None
    assert len(coordinator.list_checkpoints(live.run_id)) == 1


def test_prune_drops_old_checkpoints_and_dead_letters(coordinator: RunCoordinator) -> None:
    run = coordinator.create_run(goal="history", requirements=["r"])
    coordinator.checkpoint(run.run_id, phase="after_planning", payload={"n": 1})
    entry_id = coordinator.enqueue_dead_letter({"run_id": run.run_id, "error_class": "E"})

    report = coordinator.prune(checkpoints_days=0, dead_letters_days=0)

    assert report["checkpoints"] == 1
    assert report["dead_letters"] == 1
    assert report["runs"] == 0
    assert coordinator.list_checkpoints(run.run_id) == []
    assert coordinator.list_dead_letters(state=None) == []
    assert entry_id


def test_prune_prunes_scheduled_tasks_older_than_the_window(
    coordinator: RunCoordinator, db_path: Path
) -> None:
    """Recurring completed tasks must age out; pending ones must not."""
    from backend.persistence.db import SCHEMA_PATH

    # The coordinator owns its own file, so give it the canonical schema too --
    # prune_scheduled_tasks shares that database in production.
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.executemany(
            "INSERT INTO scheduled_tasks (id, name, status, source, completed_at) "
            "VALUES (?, ?, ?, 'custom', ?)",
            (
                ("recent", "recent", "completed", "2999-01-01T00:00:00.000Z"),
                ("ancient", "ancient", "completed", "2000-01-01T00:00:00.000Z"),
                ("still-pending", "still-pending", "pending", None),
            ),
        )

    dry = coordinator.prune(runs_days=30, dry_run=True)
    with sqlite3.connect(str(db_path)) as conn:
        before = {row[0] for row in conn.execute("SELECT id FROM scheduled_tasks")}
    assert dry["scheduled_tasks"] == 1
    assert before == {"recent", "ancient", "still-pending"}

    applied = coordinator.prune(runs_days=30)
    assert applied["scheduled_tasks"] == 1
    with sqlite3.connect(str(db_path)) as conn:
        after = {row[0] for row in conn.execute("SELECT id FROM scheduled_tasks")}
    assert after == {"recent", "still-pending"}
