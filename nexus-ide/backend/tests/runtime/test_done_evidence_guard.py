"""Regression checks for false completion of durable runs."""

import pytest

from backend.runtime.run_coordinator import DoDNotSatisfied, RunCoordinator, RunState


def test_empty_criteria_and_empty_evidence_do_not_complete(tmp_path):
    coordinator = RunCoordinator(db_path=str(tmp_path / "runs.db"))
    no_criteria = coordinator.create_run(goal="work", requirements=[])
    assert coordinator.verify_definition_of_done(no_criteria.run_id, [])['missing'][0]['reason'] == 'not_defined'
    run = coordinator.create_run(goal="work", requirements=["test"], definition_of_done=["test"])
    for state in (RunState.PLANNING, RunState.RUNNING):
        coordinator.transition(run.run_id, state)
    with pytest.raises(DoDNotSatisfied):
        coordinator.complete(run.run_id, [{"requirement": "test", "verdict": "PASS", "evidence": {}}])
    assert coordinator.get_run(run.run_id).state == RunState.RUNNING


def test_duplicate_verdicts_cannot_hide_failure(tmp_path):
    coordinator = RunCoordinator(db_path=str(tmp_path / "runs.db"))
    run = coordinator.create_run(goal="work", requirements=["test"], definition_of_done=["test"])
    results = [
        {"requirement": "test", "verdict": "FAIL", "evidence": {"exit_code": 1}},
        {"requirement": "test", "verdict": "PASS", "evidence": {"exit_code": 0}},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        coordinator.verify_definition_of_done(run.run_id, results)
