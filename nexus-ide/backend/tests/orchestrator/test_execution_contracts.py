from __future__ import annotations

import json

import pytest

from backend.models.api import StreamEvent
from backend.orchestrator.execution_contracts import (
    ErrorCategory,
    ExecutionError,
    ExecutionMode,
    ExecutionOutcome,
    ExecutionState,
    RunContext,
    is_terminal_state,
    terminal_state_for,
)


def test_context_round_trips_correlation_fields() -> None:
    context = RunContext(
        session_id="s1",
        run_id="r1",
        correlation_id="c1",
        mission_id="m1",
        project_path="C:/work/app",
        mode=ExecutionMode.MISSION,
    )
    restored = RunContext.from_dict(context.to_dict())
    assert restored == context
    assert json.loads(json.dumps(context.to_dict())) == context.to_dict()


def test_only_terminal_states_can_complete() -> None:
    assert is_terminal_state(ExecutionState.COMPLETED)
    assert is_terminal_state(ExecutionState.BLOCKED)
    assert not is_terminal_state(ExecutionState.EXECUTING)
    assert terminal_state_for(ExecutionState.FAILED) is ExecutionState.FAILED
    assert terminal_state_for(ExecutionState.EXECUTING) is None


def test_failed_provider_outcome_cannot_claim_completion() -> None:
    outcome = ExecutionOutcome(
        context=RunContext("s1", "r1", "c1", None, None, ExecutionMode.CHAT),
        state=ExecutionState.FAILED,
        error=ExecutionError(
            category=ErrorCategory.PROVIDER,
            message="provider unavailable",
        ),
    )
    assert outcome.completion_proven is False
    assert outcome.to_dict()["error"]["category"] == "provider"


def test_completion_requires_verification_and_no_failures() -> None:
    context = RunContext("s1", "r1", "c1", None, None, ExecutionMode.CHAT)
    assert ExecutionOutcome(context=context, state=ExecutionState.COMPLETED).to_dict()[
        "completion_proven"
    ] is False
    assert ExecutionOutcome(
        context=context,
        state=ExecutionState.COMPLETED,
        evidence=[{"verified": True}],
    ).to_dict()["completion_proven"] is True
    assert ExecutionOutcome(
        context=context,
        state=ExecutionState.COMPLETED,
        evidence=[{"verified": True}],
        failed_tasks=["task-1"],
    ).to_dict()["completion_proven"] is False


def test_completion_requires_every_evidence_item_to_be_verified() -> None:
    context = RunContext("s1", "r1", "c1", None, None, ExecutionMode.CHAT)
    for evidence in ([{"verified": True}, {"verified": False}], [{"result": "ok"}]):
        outcome = ExecutionOutcome(
            context=context,
            state=ExecutionState.COMPLETED,
            evidence=evidence,
        )
        assert outcome.to_dict()["completion_proven"] is False


def test_context_rejects_empty_correlation_ids() -> None:
    with pytest.raises(ValueError):
        RunContext("", "r1", "c1", None, None, ExecutionMode.CHAT)
    with pytest.raises(ValueError):
        RunContext("s1", " ", "c1", None, None, ExecutionMode.CHAT)


def test_stream_event_execution_metadata_is_optional() -> None:
    event = StreamEvent(type="token", content="hello")
    assert event.execution is None
    event_with_execution = StreamEvent(
        type="execution_state",
        execution={"state": "executing", "run_id": "r1"},
    )
    assert event_with_execution.execution == {"state": "executing", "run_id": "r1"}
