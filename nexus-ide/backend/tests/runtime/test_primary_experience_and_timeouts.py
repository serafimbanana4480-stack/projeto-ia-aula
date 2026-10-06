"""Primary loop hardening: experience capture + per-run timeout guard.

Complements ``test_phase3_primary_loop.py``. The rule under test is the one
the chat contract depends on: experience capture and robustness guards may
change how honestly a run *reports*, never whether it *reports* — exactly
one terminal event, and the ``(run_id, seq)`` order holds in every scenario.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from typing import Any

import pytest

import backend.runtime.primary as primary_module
from backend.runtime.primary import (
    AgentSignal,
    AgentSignalKind,
    Observation,
    PrimaryLoop,
    PrimaryTurn,
)


# ---------------------------------------------------------------- helpers
class FakeBus:
    """Records every call the loop makes, persisting nothing."""

    def __init__(self, *, fail_on_complete: bool = False) -> None:
        self.started: list[dict[str, Any]] = []
        self.trajectories: list[dict[str, Any]] = []
        self.completed: list[dict[str, Any]] = []
        self.fail_on_complete = fail_on_complete

    def start_trace(self, **kwargs: Any) -> dict[str, Any]:
        trace = {"task_id": f"task_{len(self.started)}", **kwargs}
        self.started.append(trace)
        return trace

    def record_trajectory(self, trace: dict[str, Any], **kwargs: Any) -> None:
        self.trajectories.append({"task_id": trace["task_id"], **kwargs})

    def complete(self, trace: dict[str, Any], **kwargs: Any) -> str:
        if self.fail_on_complete:
            raise RuntimeError("lake is closed")
        self.completed.append({"task_id": trace["task_id"], **kwargs})
        return str(trace["task_id"])


def token(text: str) -> AgentSignal:
    return AgentSignal(AgentSignalKind.TOKEN, text=text)


def transient_error(text: str = "upstream 503") -> AgentSignal:
    return AgentSignal(
        AgentSignalKind.ERROR,
        text=text,
        ok=False,
        payload={"reason": "rate_limit"},
    )


async def observe(_turn: PrimaryTurn) -> Observation:
    return Observation(summary="projeto", files_inspected=1)


async def collect(loop: PrimaryLoop) -> list:
    return [event async for event in loop.run()]


def types_of(events: list) -> list[str]:
    return [event.type.value for event in events]


def assert_dense_order(events: list) -> None:
    seqs = [event.seq for event in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "seq must be strictly increasing"


# ------------------------------------------------------- experience capture
@pytest.mark.asyncio
async def test_completed_run_publishes_exactly_one_experience_trace() -> None:
    bus = FakeBus()
    loop = PrimaryLoop(
        run_id="run-exp-ok",
        query="corrige o typo",
        stream=signals_token_only("Feito."),
        experience_bus=bus,
        session_id="sess-1",
        project_path="/tmp/project",
    )
    events = await collect(loop)

    assert len(bus.completed) == 1, "one completed run, one trace"
    record = bus.completed[0]
    assert record["success"] is True
    assert record["output"] == "Feito."
    assert record["files_modified"] == []
    assert bus.started[0]["prompt"] == "corrige o typo"
    assert bus.started[0]["session_id"] == "sess-1"
    assert bus.trajectories == [
        {
            "task_id": "task_0",
            "agent": "NEXUS",
            "action": "run_completed",
            "observation": "Run ended after 1 cycle(s).",
            "success": True,
            "error": None,
            "input_data": {"cycles": 1},
        }
    ]
    assert types_of(events)[-1] == "run_completed"
    assert_dense_order(events)


@pytest.mark.asyncio
async def test_failed_run_still_publishes_once_with_success_false() -> None:
    """A red final verification ends the run as failed — and is captured."""
    bus = FakeBus()

    def verify(_request: object):
        from backend.runtime.primary import VerificationResult

        return VerificationResult(ran=True, ok=False, summary="1 falhou")

    loop = PrimaryLoop(
        run_id="run-exp-fail",
        query="corrige o bug",
        stream=signals_token_only("Apliquei a alteração."),
        verify=verify,
        max_cycles=1,
        experience_bus=bus,
        project_path="/tmp/project",
    )
    events = await collect(loop)

    assert loop.outcome.failed is True
    assert types_of(events)[-1] == "run_failed"
    assert len(bus.completed) == 1
    assert bus.completed[0]["success"] is False
    assert "verificação final falhou" in bus.completed[0]["error"]
    # Exactly one terminal event, still in order.
    assert types_of(events).count("run_failed") == 1
    assert_dense_order(events)


@pytest.mark.asyncio
async def test_nexus_experience_off_disables_publishing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    bus = FakeBus()
    loop = PrimaryLoop(
        run_id="run-exp-off",
        query="qualquer coisa",
        stream=signals_token_only("olá"),
        experience_bus=bus,
    )
    events = await collect(loop)

    assert loop.outcome.succeeded
    assert bus.started == [] and bus.completed == [], "the flag must silence the bus"
    assert types_of(events)[-1] == "run_completed"


@pytest.mark.asyncio
async def test_broken_bus_never_breaks_the_run() -> None:
    bus = FakeBus(fail_on_complete=True)
    loop = PrimaryLoop(
        run_id="run-exp-broken",
        query="tarefa",
        stream=signals_token_only("resposta"),
        experience_bus=bus,
    )
    events = await asyncio.wait_for(collect(loop), timeout=5)

    assert loop.outcome.succeeded
    assert types_of(events)[-1] == "run_completed"
    assert_dense_order(events)


@pytest.mark.asyncio
async def test_missing_experience_stack_does_not_break_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No injected bus + unimportable experience module ⇒ run still completes."""
    monkeypatch.delenv("NEXUS_EXPERIENCE_OFF", raising=False)
    monkeypatch.setattr(primary_module, "_experience_bus_cache", None)
    monkeypatch.setitem(sys.modules, "backend.experience.bus", None)
    loop = PrimaryLoop(
        run_id="run-exp-missing",
        query="tarefa",
        stream=signals_token_only("ok"),
    )
    events = await asyncio.wait_for(collect(loop), timeout=5)

    assert loop.outcome.succeeded
    assert types_of(events)[-1] == "run_completed"


# ------------------------------------------------------------ timeout guard
@pytest.mark.asyncio
async def test_hung_provider_is_cut_by_the_run_timeout() -> None:
    calls: list[int] = []

    def factory(_turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        calls.append(1)

        async def iterator() -> AsyncIterator[AgentSignal]:
            yield token("a começar")
            await asyncio.sleep(3600)
            yield token("nunca")  # pragma: no cover

        return iterator()

    loop = PrimaryLoop(
        run_id="run-timeout",
        query="tarefa interminável",
        stream=factory,
        observe=observe,
        run_timeout=0.05,
        project_path="/tmp/project",
    )
    started = asyncio.get_running_loop().time()
    events = await asyncio.wait_for(collect(loop), timeout=5)

    elapsed = asyncio.get_running_loop().time() - started
    assert loop.outcome.failed is True
    assert "limite de 0s" in loop.outcome.error or "limite" in loop.outcome.error
    assert types_of(events)[-1] == "run_failed"
    assert types_of(events).count("run_failed") == 1
    assert elapsed < 5, "a hung provider must not hang the turn"
    assert_dense_order(events)


@pytest.mark.asyncio
async def test_no_timeout_configured_means_unchanged_behavior() -> None:
    loop = PrimaryLoop(
        run_id="run-notimeout",
        query="tarefa normal",
        stream=signals_token_only("terminou"),
        run_timeout=0,
    )
    events = await collect(loop)
    assert loop.outcome.succeeded
    assert types_of(events)[-1] == "run_completed"


# --------------------------------------------------- transient retry hook
@pytest.mark.asyncio
async def test_transient_provider_error_is_retried_once_then_succeeds() -> None:
    calls: list[int] = []

    def factory(_turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        calls.append(1)
        attempt = len(calls)

        async def iterator() -> AsyncIterator[AgentSignal]:
            if attempt == 1:
                yield transient_error()
                return
            yield token("recuperado")

        return iterator()

    loop = PrimaryLoop(
        run_id="run-retry-ok",
        query="pergunta",
        stream=factory,
    )
    events = await asyncio.wait_for(collect(loop), timeout=5)

    assert calls == [1, 1], "exactly one silent retry"
    assert loop.outcome.succeeded
    assert loop.outcome.answer == "recuperado"
    assert loop.telemetry.retries == 1
    assert types_of(events)[-1] == "run_completed"
    assert "run_failed" not in types_of(events)
    assert_dense_order(events)


@pytest.mark.asyncio
async def test_persistent_transient_error_is_retried_at_most_once() -> None:
    calls: list[int] = []

    def factory(_turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        calls.append(1)

        async def iterator() -> AsyncIterator[AgentSignal]:
            yield transient_error("rate limited")

        return iterator()

    loop = PrimaryLoop(
        run_id="run-retry-red",
        query="pergunta",
        stream=factory,
    )
    events = await asyncio.wait_for(collect(loop), timeout=5)

    assert len(calls) == 2, "first attempt plus one retry, nothing more"
    assert loop.outcome.failed is True
    assert "rate limited" in loop.outcome.error
    assert types_of(events)[-1] == "run_failed"
    assert types_of(events).count("run_failed") == 1


@pytest.mark.asyncio
async def test_no_retry_after_user_visible_output() -> None:
    """Once tokens reached the user, a retry would duplicate the message."""
    calls: list[int] = []

    def factory(_turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        calls.append(1)

        async def iterator() -> AsyncIterator[AgentSignal]:
            yield token("parcial ")
            yield transient_error()

        return iterator()

    loop = PrimaryLoop(
        run_id="run-retry-visible",
        query="pergunta",
        stream=factory,
    )
    events = await asyncio.wait_for(collect(loop), timeout=5)

    assert len(calls) == 1, "retrying after visible output would repeat text"
    assert loop.outcome.failed is True
    assert types_of(events).count("message_delta") == 1


@pytest.mark.asyncio
async def test_fatal_error_is_never_retried() -> None:
    calls: list[int] = []

    def factory(_turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        calls.append(1)

        async def iterator() -> AsyncIterator[AgentSignal]:
            yield AgentSignal(AgentSignalKind.ERROR, text="bad request", ok=False)

        return iterator()

    loop = PrimaryLoop(
        run_id="run-fatal-noretry",
        query="pergunta",
        stream=factory,
    )
    events = await asyncio.wait_for(collect(loop), timeout=5)

    assert len(calls) == 1
    assert loop.outcome.failed is True
    assert loop.outcome.error == "bad request"
    assert types_of(events)[-1] == "run_failed"


# ------------------------------------------------------------------ factory
def signals_token_only(text: str):
    def factory(_turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        async def iterator() -> AsyncIterator[AgentSignal]:
            await asyncio.sleep(0)
            yield token(text)

        return iterator()

    return factory
