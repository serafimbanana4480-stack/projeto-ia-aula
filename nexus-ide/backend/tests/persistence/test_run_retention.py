"""The run-state retention must actually run.

``RunCoordinator.prune()`` had no production caller: only the tests called
it. The durable run tables (``run_state``, ``run_checkpoints``,
``run_side_effects``, ``run_dead_letters``) and the scheduled-task queue
therefore grew forever. The background loop of
``backend/orchestrator/session_lifecycle.py`` is the model that was followed:
the session GC loop now applies the retention on an interval.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.orchestrator.session_lifecycle import SessionLifecycleManager


async def test_prune_is_reachable_from_the_background_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The background loop must call ``RunCoordinator.prune()``."""
    from backend.runtime import run_coordinator

    calls: list[dict[str, Any]] = []

    def _fake_prune(self: Any, **kwargs: Any) -> dict[str, int]:
        calls.append(kwargs)
        return {
            "runs": 0,
            "checkpoints": 0,
            "side_effects": 0,
            "dead_letters": 0,
            "scheduled_tasks": 0,
        }

    monkeypatch.setattr(run_coordinator.RunCoordinator, "prune", _fake_prune)

    manager = SessionLifecycleManager(
        event_bus=None,
        gc_interval_minutes=60,
        run_retention_interval_minutes=0,
    )
    manager.start()
    try:
        await asyncio.sleep(0.2)
    finally:
        await manager.stop()

    assert calls, "the background loop must apply the run-state retention"
    assert calls[0]["runs_days"] == manager.run_retention_days
    assert "checkpoints_days" in calls[0]
    assert "dead_letters_days" in calls[0]


async def test_run_state_retention_removes_old_terminal_runs(
    tmp_path: Any,
) -> None:
    """The retention the background loop applies really deletes old state."""
    from backend.runtime.run_coordinator import RunCoordinator

    coordinator = RunCoordinator(str(tmp_path / "retention.db"))
    run = coordinator.create_run(
        goal="retention target",
        requirements=["done"],
        definition_of_done=["done"],
    )
    coordinator.transition(run.run_id, "failed", reason="retention fixture")

    counts = coordinator.prune(runs_days=0, checkpoints_days=0, dead_letters_days=0)

    assert counts["runs"] >= 1
    assert coordinator.get_run(run.run_id) is None
