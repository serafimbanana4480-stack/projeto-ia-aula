"""Durable recovery endpoints must keep run state tenant scoped."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.orchestrator.routes import chat, meta
from backend.runtime import primary
from backend.runtime.run_coordinator import RunState


def _record(user_id: str, run_id: str = "run-owned") -> SimpleNamespace:
    return SimpleNamespace(
        run_id=run_id,
        user_id=user_id,
        state=RunState.RUNNING,
        goal=f"goal for {user_id}",
        session_id=f"session-{user_id}",
        project_id="",
    )


def _request(coordinator: object) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(run_coordinator=coordinator))
    )


def test_resumable_runs_are_filtered_to_authenticated_owner() -> None:
    owner = _record("alice", "run-alice")
    other = _record("bob", "run-bob")
    legacy = _record("", "run-legacy-without-owner")

    class Coordinator:
        def find_resumable_runs(self, *, user_id: str) -> list[SimpleNamespace]:
            assert user_id == "alice"
            # Also verify that the route checks ownership if a faulty or older
            # coordinator implementation returns a cross-tenant or ownerless
            # legacy record.
            return [owner, other, legacy]

    response = asyncio.run(
        meta.list_resumable_runs(_request(Coordinator()), _auth={"user_id": "alice"})
    )

    assert response.count == 1
    assert [run["run_id"] for run in response.runs] == ["run-alice"]
    assert response.runs[0]["goal"] == "goal for alice"


def test_ownerless_legacy_run_cannot_be_listed_or_restored() -> None:
    legacy = _record("", "run-legacy-without-owner")

    class Coordinator:
        restored = False

        def find_resumable_runs(self, *, user_id: str) -> list[SimpleNamespace]:
            assert user_id == "alice"
            return [legacy]

        def get_run(self, _run_id: str) -> SimpleNamespace:
            return legacy

        def restore(self, _run_id: str) -> None:
            self.restored = True

    coordinator = Coordinator()
    request = _request(coordinator)

    listed = asyncio.run(meta.list_resumable_runs(request, _auth={"user_id": "alice"}))
    assert listed.count == 0
    assert listed.runs == []

    with pytest.raises(HTTPException) as error:
        asyncio.run(meta.resume_run(request, legacy.run_id, _auth={"user_id": "alice"}))

    assert error.value.status_code == 404
    assert error.value.detail == "Run not found"
    assert coordinator.restored is False


def test_resume_of_another_users_run_returns_not_found_without_restoring() -> None:
    class Coordinator:
        restored = False

        def get_run(self, _run_id: str) -> SimpleNamespace:
            return _record("bob", "run-bob")

        def restore(self, _run_id: str) -> None:
            self.restored = True

    coordinator = Coordinator()
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            meta.resume_run(
                _request(coordinator), "run-bob", _auth={"user_id": "alice"}
            )
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Run not found"
    assert coordinator.restored is False


def test_resume_of_owned_run_restores_its_checkpoint() -> None:
    class Coordinator:
        record = _record("alice", "run-alice")

        def get_run(self, _run_id: str) -> SimpleNamespace:
            return self.record

        def restore(self, _run_id: str) -> SimpleNamespace:
            self.record.state = RunState.RECOVERING
            return SimpleNamespace(
                payload={"plan": ["continue"]},
                checkpoint_id="checkpoint-1",
                phase="after_task",
                created_at="2026-10-25T00:00:00Z",
            )

    response = asyncio.run(
        meta.resume_run(
            _request(Coordinator()), "run-alice", _auth={"user_id": "alice"}
        )
    )

    assert response.run_id == "run-alice"
    assert response.state == "recovering"
    assert response.checkpoint["plan"] == ["continue"]


def test_idempotent_chat_adoption_scopes_lookup_to_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record("alice", "run-alice")
    record.memory_refs = ["idempotency:stable-key"]
    lookups: list[tuple[str, str | None]] = []

    class Coordinator:
        def find_resumable_runs(
            self, *, session_id: str | None, user_id: str | None
        ) -> list[SimpleNamespace]:
            lookups.append((session_id or "", user_id))
            return [record]

        def update_progress(self, _run_id: str, *, memory_refs: list[str]) -> SimpleNamespace:
            record.memory_refs = memory_refs
            return record

        def transition(
            self, _run_id: str, state: RunState, *, reason: str
        ) -> SimpleNamespace:
            record.state = state
            return record

    coordinator = Coordinator()
    monkeypatch.setattr(primary, "get_run_coordinator", lambda: coordinator)

    adopted = primary.RunLifecycle.begin(
        goal=record.goal,
        session_id=record.session_id,
        user_id="alice",
        idempotency_key="stable-key",
    )

    assert adopted is not None
    assert adopted.run_id == "run-alice"
    assert lookups == [("session-alice", "alice")]


def test_recovered_chat_retry_reenters_when_the_old_process_has_no_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.runtime import events

    monkeypatch.setattr(events, "get_active_run_event_stream", lambda _run_id: None)

    assert not chat._should_replay_idempotent_primary_run(
        SimpleNamespace(run_id="run-recovered", state=RunState.RECOVERING)
    )


def test_recovered_chat_retry_attaches_to_an_already_resumed_live_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.runtime import events

    monkeypatch.setattr(events, "get_active_run_event_stream", lambda _run_id: object())

    assert chat._should_replay_idempotent_primary_run(
        SimpleNamespace(run_id="run-resumed", state=RunState.RECOVERING)
    )
