from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest

from backend.orchestrator.infinity.vibe_director import (
    VibeDirector,
    WorkerState,
    drop_director,
    register_director,
)
from backend.orchestrator.infinity.vibe_store import VibeStateStore


@pytest.mark.asyncio
async def test_director_reuses_worker_and_refreshes_runner_after_failure() -> None:
    attempts = 0

    async def failing_runner(_worker, _message: str) -> str:
        raise RuntimeError("temporary provider failure")

    director = VibeDirector(session_id="vibe-test", runner=failing_runner)
    created = director.spawn(tier="good", prompt="first request", name="worker")
    worker = director.get(created["id"])
    assert worker is not None
    await director.wait([worker.id], timeout=1)
    assert worker.state.value == "idle"
    assert worker.error == "RuntimeError: temporary provider failure"

    async def recovered_runner(_worker, message: str) -> str:
        nonlocal attempts
        attempts += 1
        return f"completed: {message}"

    director.set_runner(recovered_runner, tier_models={"good": "test-model"})
    director.send(worker.id, "follow-up")
    await director.wait([worker.id], timeout=1)

    assert attempts == 1
    assert worker.error is None
    assert worker.model_id == "test-model"
    assert worker.turn_count == 1
    assert worker.history == [
        {"role": "user", "content": "follow-up"},
        {"role": "assistant", "content": "completed: follow-up"},
    ]


@pytest.mark.asyncio
async def test_queued_turn_keeps_the_runner_bound_to_its_chat_request() -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    release_second = asyncio.Event()
    seen: list[tuple[str, str]] = []

    async def first_runner(_worker, message: str) -> str:
        seen.append(("first", message))
        first_started.set()
        await release_first.wait()
        return "first result"

    async def second_runner(_worker, message: str) -> str:
        seen.append(("second", message))
        second_started.set()
        await release_second.wait()
        return "second result"

    director = VibeDirector(session_id="vibe-queue-test", runner=first_runner)
    created = director.spawn(
        tier="good", prompt="first message", runner=first_runner
    )
    worker = director.get(created["id"])
    assert worker is not None
    await first_started.wait()

    director.send(worker.id, "second message", runner=second_runner)
    release_first.set()
    try:
        first_settlement = await director.wait([worker.id], timeout=1)
        assert first_settlement[0]["settled"] is True
        assert first_settlement[0]["state"] == "streaming"
        await second_started.wait()
        release_second.set()
        await director.wait([worker.id], timeout=1)
    finally:
        release_first.set()
        release_second.set()

    assert seen == [("first", "first message"), ("second", "second message")]
    assert worker.history[-2:] == [
        {"role": "user", "content": "second message"},
        {"role": "assistant", "content": "second result"},
    ]


@pytest.mark.asyncio
async def test_wait_returns_when_the_first_watched_worker_settles() -> None:
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    fast_finished = asyncio.Event()

    async def runner(_worker, message: str) -> str:
        if message == "slow":
            slow_started.set()
            await release_slow.wait()
        else:
            fast_finished.set()
        return f"done: {message}"

    director = VibeDirector(session_id="vibe-first-settlement", runner=runner)
    slow = director.spawn(tier="good", prompt="slow")
    await slow_started.wait()
    fast = director.spawn(tier="fast", prompt="fast")

    try:
        await asyncio.wait_for(fast_finished.wait(), timeout=1)
        results = await asyncio.wait_for(director.wait(timeout=5), timeout=1)
        by_id = {result["id"]: result for result in results}

        assert by_id[fast["id"]]["settled"] is True
        assert by_id[fast["id"]]["state"] == "idle"
        assert by_id[slow["id"]]["settled"] is False
        assert by_id[slow["id"]]["state"] == "streaming"
    finally:
        release_slow.set()
        await director.wait([slow["id"]], timeout=1)


@pytest.mark.asyncio
async def test_wait_preserves_failed_turn_when_queued_turn_starts_immediately() -> None:
    failure_started = asyncio.Event()
    release_failure = asyncio.Event()
    recovery_started = asyncio.Event()
    release_recovery = asyncio.Event()

    async def runner(_worker, message: str) -> str:
        if message == "fail":
            failure_started.set()
            await release_failure.wait()
            raise RuntimeError("first turn failed")
        recovery_started.set()
        await release_recovery.wait()
        return "recovered result"

    director = VibeDirector(session_id="vibe-failed-settlement", runner=runner)
    created = director.spawn(tier="good", prompt="fail")
    worker_id = created["id"]
    await failure_started.wait()
    assert director.send(worker_id, "recover")["action"] == "queued"

    try:
        release_failure.set()
        failed = await asyncio.wait_for(director.wait([worker_id], timeout=1), timeout=1)
        await recovery_started.wait()
        assert failed[0]["settled"] is True
        assert failed[0]["state"] == "streaming"
        assert failed[0]["error"] is None  # The queued retry already started.
        assert failed[0]["settlement"]["outcome"] == "failed"
        assert failed[0]["settlement"]["error"] == "RuntimeError: first turn failed"

        release_recovery.set()
        recovered = await director.wait([worker_id], timeout=1)
        assert recovered[0]["settled"] is True
        assert recovered[0]["settlement"]["outcome"] == "completed"
        assert recovered[0]["settlement"]["result"] == "recovered result"
    finally:
        release_failure.set()
        release_recovery.set()


@pytest.mark.asyncio
async def test_director_restores_completed_worker_and_history(tmp_path) -> None:
    store = VibeStateStore(tmp_path, "persisted-vibe-session")

    async def runner(_worker, message: str) -> str:
        return f"result: {message}"

    director = VibeDirector(
        session_id="persisted-vibe-session",
        runner=runner,
        tier_models={"good": "model-before-restart"},
        persistence_store=store,
    )
    created = director.spawn(tier="good", prompt="remember this")
    await director.wait([created["id"]], timeout=1)

    restored = VibeDirector(
        session_id="persisted-vibe-session",
        runner=runner,
        tier_models={"good": "model-after-restart"},
        persistence_store=store,
    )
    worker = restored.get(created["id"])
    assert worker is not None
    assert worker.state is WorkerState.IDLE
    assert worker.model_id == "model-after-restart"
    assert worker.turn_count == 1
    assert worker.last_result == "result: remember this"
    assert worker.history == [
        {"role": "user", "content": "remember this"},
        {"role": "assistant", "content": "result: remember this"},
    ]


@pytest.mark.asyncio
async def test_restart_marks_inflight_worker_interrupted_without_rerunning(tmp_path) -> None:
    store = VibeStateStore(tmp_path, "interrupted-vibe-session")
    started = asyncio.Event()
    calls: list[str] = []

    async def runner(_worker, message: str) -> str:
        calls.append(message)
        started.set()
        await asyncio.Future()

    director = VibeDirector(
        session_id="interrupted-vibe-session",
        runner=runner,
        persistence_store=store,
    )
    created = director.spawn(tier="good", prompt="in flight")
    worker = director.get(created["id"])
    assert worker is not None
    await started.wait()
    director.send(worker.id, "queued follow-up")

    # Keep the durable snapshot from the instant before process termination.
    store.save(director._state_payload())
    task = worker.task
    assert task is not None
    director._persistence_store = None
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    restarted_calls: list[str] = []

    async def restarted_runner(_worker, message: str) -> str:
        restarted_calls.append(message)
        return "unexpected rerun"

    restored = VibeDirector(
        session_id="interrupted-vibe-session",
        runner=restarted_runner,
        persistence_store=store,
    )
    recovered = restored.get(worker.id)
    assert recovered is not None
    assert recovered.state is WorkerState.IDLE
    assert recovered.error is not None and "backend restart" in recovered.error
    assert "queued follow-up(s) were discarded" in recovered.error
    assert recovered.history == [{"role": "user", "content": "in flight"}]
    settlements = await restored.wait([worker.id], timeout=0)
    assert settlements[0]["settlement"]["outcome"] == "interrupted"
    assert calls == ["in flight"]
    assert restarted_calls == []


def test_dropping_director_removes_its_persisted_session(tmp_path) -> None:
    store = VibeStateStore(tmp_path, "deleted-vibe-session")
    store.save({"version": 1, "session_id": "deleted-vibe-session", "workers": []})
    director = VibeDirector(
        session_id="deleted-vibe-session",
        runner=lambda _worker, _message: None,
        persistence_store=store,
    )
    register_director(director)

    drop_director("deleted-vibe-session")

    assert not store.path.exists()
