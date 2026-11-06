"""Fase 1 — failure-injection suite for the durable run (NEXUS IDE).

Ownership: this file plus the ``test_failure_injection_*`` helper next to it.
Nothing else is touched and nothing is committed.

What this suite proves
----------------------
Every failure a run can suffer is injected against **real** code and observed
through **real** state: the real :class:`~backend.runtime.run_coordinator.RunCoordinator`
on a throwaway SQLite file under ``tmp_path`` (the global ``temp_db`` fixture
repoints ``db.DB_PATH`` at it per test), the real dead-letter service and its
:func:`~backend.runtime.dead_letter_service.classify_error` contract, the real
watchdog, the real tool registry, the real provider adapters speaking to a real
HTTP transport (``httpx.MockTransport``), the real task scheduler, and — for the
process-death scenario — a real child process killed with SIGKILL, the pattern
``test_run_resume_e2e.py`` established.

For every scenario the tests assert the same evidence, and they assert it
without weakening: *detected* (the failure surfaced, with the cause in the error
text), *classified* (transient with a retry delay, or permanent), *retried*
(time-gated re-arm, never an immediate hammer), *checkpoint preserved* (the
resume surface survived the failure), *resumed* (the run is still listed as
resumable and restores its checkpoint), *no duplicate side effect* (the
idempotency ledger still holds exactly one row per confirmed action), and the
*final result* (a terminal state with an observable reason, or a continued run —
never a success the evidence does not support).

Deliberately out of scope
-------------------------
* **Backend restart after a crash (infra 3c)** is already proven by the
  real-subprocess e2e
  ``backend.tests.integration.test_run_resume_e2e.test_real_restart_resumes_the_run_the_process_left_open``
  (real uvicorn, SIGKILL mid-turn, resume, no duplicate side effect). It is
  referenced here, not repeated. The process-death scenario in this suite also
  kills a real process, but at the coordinator level, where the observable is
  the side-effect ledger rather than the HTTP lane.
* **Context overflow (agent 4c)** has a real, testable hook — the ReAct loop's
  ``AgentBase._is_context_overflow`` / ``_emergency_shrink_context`` — which is
  exercised below. The *primary run lane* has no overflow hook of its own, so no
  such capability is claimed for it: the run-level assertion is the
  definition-of-done gate, which is what keeps a truncated answer from looking
  like a completed run.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.agents.base import AgentBase
from backend.llm.factory import ResilientLLMProvider
from backend.llm.openai_provider import OpenAIProvider, ProviderHTTPStatusError
from backend.observability.event_system import EventBus
from backend.orchestrator.routes.chat_primary import (
    PRIMARY_DOD_ANSWER,
    PRIMARY_DOD_VERIFIED,
    _close_primary_run_lifecycle,
)
from backend.runtime import primary as runtime_primary
from backend.runtime.dead_letter_service import (
    DEFAULT_TRANSIENT_RETRY_AFTER_SECONDS,
    RECOVERABILITY_PERMANENT,
    RECOVERABILITY_TRANSIENT,
    DeadLetterRejected,
    DeadLetterService,
    classify_error,
)
from backend.runtime.primary import (
    PrimaryLoop,
    RunLifecycle,
    is_side_effecting_tool,
    side_effect_idempotency_key,
)
from backend.runtime.run_context import reset_current_run_id, set_current_run_id
from backend.runtime.run_coordinator import (
    DoDNotSatisfied,
    RunCoordinator,
    RunRecord,
    RunState,
)
from backend.runtime.run_watchdog import RunWatchdog, WatchdogAction, WatchdogSignal
from backend.tasks.autonomous_tasks import AutonomousTaskManager, TaskStatus, TaskType
from backend.token_management import ContextOverflowError
from backend.tools import registry as tool_registry
from backend.tools.ollama_client import OllamaClient
from backend.tools.registry import (
    ToolSpec,
    execute_tool,
    register_tool,
    reset_tool_failures,
    tool_failure_count,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CHILD_PYTHON = sys.executable

_MESSAGES = [{"role": "user", "content": "faz o trabalho"}]

#: Per-test guard: no scenario may need real wall-clock. Backoff schedules are
#: observed (the sleeps the adapter really performs), never slept through.
TIMEOUT = 120

#: Tool/state names this suite injects. Unique per scenario so a failure streak
#: in one test cannot leak into another through the registry's breaker.
CRASH_TOOL = "fi_crash_tool"
TIMEOUT_TOOL = "fi_timeout_tool"
MALFORMED_TOOL = "fi_malformed_tool"
SESSION = "fi-session"


# ── doubles that reproduce only the *shape* of the outside world ───────────


class _FailingProvider:
    """A provider that always fails with *error* (the injected failure)."""

    provider_name = "scripted-failing"

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls = 0

    async def chat_complete(self, *_args: Any, **_kwargs: Any) -> str:
        self.calls += 1
        raise self._error

    async def chat_stream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[str]:
        self.calls += 1
        raise self._error
        yield ""  # pragma: no cover - makes this an async generator


class _ScriptedProvider:
    """A provider that answers with a fixed string (the failover target)."""

    provider_name = "scripted-answer"

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.calls = 0

    async def chat_complete(self, *_args: Any, **_kwargs: Any) -> str:
        self.calls += 1
        return self._answer

    async def chat_stream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[str]:
        self.calls += 1
        yield self._answer


class _ScriptedTaskManager:
    """The task-manager seam the dead-letter service delegates re-arming to."""

    def __init__(self, answer: str = "requeued") -> None:
        self.answer = answer
        self.requeued: list[str] = []

    async def requeue_task(self, task_id: str) -> str:
        self.requeued.append(task_id)
        return self.answer


class FakeClock:
    """An injectable "now", so a run can be aged without sleeping."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


# ── helpers ───────────────────────────────────────────────────────────────


def _active_run(coordinator: RunCoordinator, **kwargs: Any) -> RunRecord:
    """A run on the machine's own legal path: CREATED → PLANNING → RUNNING."""
    run = coordinator.create_run(goal="fazer o trabalho", requirements=["acabar"], **kwargs)
    coordinator.transition(run.run_id, RunState.PLANNING)
    return coordinator.transition(run.run_id, RunState.RUNNING)


def _iso(offset_seconds: float) -> str:
    moment = datetime.now(UTC) + timedelta(seconds=offset_seconds)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _stale_heartbeat(coordinator: RunCoordinator, run_id: str, seconds: float) -> None:
    """Backdate a heartbeat exactly as a stalled run would leave it."""
    from backend.persistence import db

    db.update_run_row(run_id, {"heartbeat_at": _iso(-seconds)}, db_path=coordinator.db_path)


def _openai_provider(*, status: int | None = None, body: str = "") -> OpenAIProvider:
    """A real OpenAI-compatible provider wired to an in-process transport.

    No network and no API key: the transport answers with exactly what the
    scenario needs, and every layer above it is the production one.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if status is None:
            return httpx.Response(200, content=body.encode())
        return httpx.Response(status, text=body)

    provider = OpenAIProvider("http://provider.invalid", api_key=None)
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://provider.invalid"
    )
    return provider


def _ollama_like_client(
    *, status: int | None = None, body: str = "", raise_exc: BaseException | None = None
) -> OllamaClient:
    """A real Ollama client on an in-process transport (same idea as above)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if raise_exc is not None:
            raise raise_exc
        if status is None:
            return httpx.Response(200, content=body.encode())
        return httpx.Response(status, text=body)

    return OllamaClient("http://ollama.invalid", transport=httpx.MockTransport(handler))


@contextlib.contextmanager
def injected_tool(
    name: str,
    *,
    handler: Callable[..., Any] | None = None,
    timeout_seconds: float | None = None,
) -> Iterator[ToolSpec]:
    """Register a purpose-built tool for one test, then remove it again."""
    spec = ToolSpec(
        name=name,
        description="failure-injection probe",
        handler=handler,
        schema={"type": "object", "properties": {}},
        timeout_seconds=timeout_seconds,
    )
    register_tool(spec)
    reset_tool_failures(SESSION)
    try:
        yield spec
    finally:
        tool_registry._registry.pop(name, None)


@contextlib.contextmanager
def db_outage(monkeypatch: pytest.MonkeyPatch, message: str) -> Iterator[None]:
    """A window in which every run-state connection raises *message*.

    The patch is on the one function the run-state layer opens its connections
    with, so the injection hits reads and writes alike — the same seam a real
    ``OperationalError`` (unwritable file, locked database, disk error) arrives
    through.
    """
    from backend.persistence import db as db_module

    real = db_module.run_state_connection

    @contextlib.contextmanager
    def broken(*_args: Any, **_kwargs: Any) -> Iterator[sqlite3.Connection]:
        raise sqlite3.OperationalError(message)
        yield  # pragma: no cover - unreachable; keeps this a context manager

    monkeypatch.setattr(db_module, "run_state_connection", broken)
    try:
        yield
    finally:
        # Restore *this* patch only. ``monkeypatch.undo()`` would also undo the
        # ``temp_db`` fixture's DB_PATH patch (same MonkeyPatch instance), which
        # would silently move the test back onto the real database.
        monkeypatch.setattr(db_module, "run_state_connection", real)


def _checkpoint_count(coordinator: RunCoordinator, run_id: str) -> int:
    return len(coordinator.list_checkpoints(run_id, limit=1000))


def _side_effect_rows(db_file: Path, run_id: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT idempotency_key, kind FROM run_side_effects WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _wait_for(predicate: Callable[[], bool], *, timeout: float = 45.0) -> bool:
    """Poll a side effect of the child process; never a fixed sleep."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


@pytest.fixture(autouse=True)
def _fresh_run_coordinator() -> Iterator[None]:
    """The process-wide coordinator is path-keyed; start each test clean."""
    runtime_primary.reset_run_coordinator()
    yield
    runtime_primary.reset_run_coordinator()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A database file of this suite's own, for the child-process scenario."""
    return tmp_path / "failure_injection.db"


@pytest.fixture
def coordinator(temp_db: None) -> RunCoordinator:
    """The real coordinator on the per-test application database.

    The same database ``RunLifecycle`` and the tool-budget hook read, so a run
    opened through one is visible through the others — exactly as in production.
    """
    return RunCoordinator()


# ══════════════════════════════════════════════════════════════════════════
# 1. PROVIDER
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.timeout(TIMEOUT)
async def test_provider_rate_limit_429_is_transient_and_retry_is_scheduled_not_hammered(
    coordinator: RunCoordinator,
) -> None:
    """(a) 429: detected, classified transient, retry_after defined, failover.

    The injection is a real provider adapter answering 429 over a real
    transport. The retry contract is the dead-letter queue's ``retry_after``:
    an immediate re-arm must be refused, and one allowed once the delay passed.
    """
    provider = _openai_provider(status=429, body='{"error": {"message": "Too Many Requests"}}')
    try:
        with pytest.raises(ProviderHTTPStatusError) as excinfo:
            await provider.chat_complete("scripted-model", _MESSAGES)
    finally:
        await provider.aclose()
    error = excinfo.value

    # detected: the failure surfaced, with the status in the error text.
    assert error.status_code == 429
    assert "429" in str(error)

    # classified: transient, with a concrete retry delay.
    verdict = classify_error(error)
    assert verdict["recoverability"] == RECOVERABILITY_TRANSIENT
    assert verdict["retry_after"] == DEFAULT_TRANSIENT_RETRY_AFTER_SECONDS
    assert verdict["error_class"] == "providerhttpstatuserror"

    # A rate-limited provider does not fail the run when another provider can
    # answer: the failover chain hands the call over.
    chain = ResilientLLMProvider(
        _FailingProvider(ProviderHTTPStatusError(429, "Too Many Requests")),
        [_ScriptedProvider("resposta do provider de fallback")],
    )
    assert (
        await chain.chat_complete("scripted-model", _MESSAGES)
        == "resposta do provider de fallback"
    )

    # retried: the parked failure carries the delay, and the delay is honoured.
    run = _active_run(coordinator)
    service = DeadLetterService(coordinator)
    # ``park`` classifies from the stored ``error_class`` (it does not read the
    # traceback), so a producer parking the provider's own message — the shape a
    # caller with no typed exception has — keeps the transient verdict.
    parked = service.park(
        {
            "run_id": run.run_id,
            "task_id": "turn-1",
            "error_class": str(error),
            "sanitized_traceback": str(error),
            "attempts": 1,
        }
    )
    assert "429" in parked["error_class"]
    assert parked["recoverability"] == RECOVERABILITY_TRANSIENT
    assert parked["retry_after"], "a transient failure must say when to retry"
    assert parked["state"] == "open"
    assert service.list(run_id=run.run_id, recoverability=RECOVERABILITY_TRANSIENT) == [parked]

    with pytest.raises(DeadLetterRejected):
        await service.retry(parked["id"])

    # ... and once the delay has passed the same call re-arms the unit.
    due = service.park(
        {
            "run_id": run.run_id,
            "task_id": "turn-1",
            "error_class": str(error),
            "retry_after": _iso(-1),
        }
    )
    action = await DeadLetterService(
        coordinator, task_manager=_ScriptedTaskManager()
    ).retry(due["id"])
    assert action.state == "retrying"
    assert action.task_result == "requeued"

    # Recorded finding: parking only the adapter's *class name* parks as
    # "unknown". ``park`` never reads the traceback, so the same 429 that the
    # classifier calls transient is handed to a human instead. Pinned here as the
    # behaviour it is, not as the behaviour it should be.
    class_only = service.park(
        {
            "run_id": run.run_id,
            "task_id": "turn-1",
            "error_class": type(error).__name__,
        }
    )
    assert class_only["recoverability"] == "unknown"
    assert class_only["retry_after"] is None

    # checkpoint preserved + resumable: the failure parked nothing destructively.
    boundary = coordinator.checkpoint(
        run.run_id, phase="heartbeat", payload={"blocked_on": "provider"}
    )
    assert coordinator.latest_checkpoint(run.run_id) == boundary
    assert coordinator.get_run(run.run_id) in coordinator.find_resumable_runs()

    # final result: neither failed nor silently completed — the definition of
    # done still gates the run, so a rate limit cannot fake a success.
    lifecycle = RunLifecycle.begin(
        goal="entregar a resposta",
        session_id="fi-429",
        definition_of_done=["resposta entregue ao utilizador"],
    )
    assert lifecycle is not None
    assert (
        lifecycle.finish(
            [{"requirement": "resposta entregue ao utilizador", "verdict": "UNKNOWN"}]
        )
        is False
    )
    record = coordinator.get_run(lifecycle.run_id)
    assert record is not None
    assert record.state is not RunState.COMPLETED
    assert record in coordinator.find_resumable_runs()


@pytest.mark.timeout(TIMEOUT)
async def test_provider_500_and_timeout_are_retried_with_backoff_then_parked_as_transient(
    coordinator: RunCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) 500/timeout: retried with backoff, then classified transient.

    The backoff schedule is *observed* — the sleeps the adapter really performs
    — instead of slept through, which is why this needs no real time.
    """
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

    cases = (
        ("500", 500, None),
        ("timeout", None, httpx.ReadTimeout("read timed out")),
    )
    for label, status, transport_exc in cases:
        sleeps.clear()
        attempts = {"n": 0}

        def handler(
            request: httpx.Request,
            _attempts: dict[str, int] = attempts,
            _status: int | None = status,
            _exc: BaseException | None = transport_exc,
        ) -> httpx.Response:
            _attempts["n"] += 1
            if _exc is not None:
                raise _exc
            return httpx.Response(_status or 500, text="upstream exploded")

        client = OllamaClient(
            "http://ollama.invalid", transport=httpx.MockTransport(handler)
        )
        try:
            with pytest.raises(Exception) as excinfo:  # noqa: B017 - two error shapes
                await client.chat_complete("scripted-model", _MESSAGES)
        finally:
            await client.aclose()
        error = excinfo.value

        # detected: the failure surfaced, with the cause in the text.
        assert attempts["n"] > 1, f"{label}: a retryable failure must be retried"
        assert "500" in str(error) or "timeout" in str(error).lower(), label

        # retried: with a growing, bounded backoff.
        assert sleeps, f"{label}: a retryable failure must back off"
        assert sleeps == sorted(sleeps), f"{label}: backoff must grow"
        assert len(sleeps) <= 4, f"{label}: the retry budget must be bounded"

        # classified: transient, with a retry delay (5xx/timeout is the world).
        verdict = classify_error(error)
        assert verdict["recoverability"] == RECOVERABILITY_TRANSIENT, label
        assert verdict["retry_after"] == DEFAULT_TRANSIENT_RETRY_AFTER_SECONDS, label

    # The parked entry keeps the attempts and the delay. ``park`` classifies from
    # the stored error_class, so the message shape carries the verdict.
    run = _active_run(coordinator)
    service = DeadLetterService(coordinator)
    failure_message = "POST /api/chat failed after 5 attempts: HTTP 500"
    parked = service.park(
        {
            "run_id": run.run_id,
            "task_id": "turn-1",
            "error_class": failure_message,
            "sanitized_traceback": failure_message,
            "attempts": 5,
        }
    )
    assert "500" in parked["error_class"]
    assert parked["recoverability"] == RECOVERABILITY_TRANSIENT
    assert parked["attempts"] == 5
    assert parked["retry_after"]
    assert parked["run_id"] == run.run_id
    assert parked["state"] == "open"
    assert service.list(run_id=run.run_id, recoverability=RECOVERABILITY_TRANSIENT) == [parked]

    # checkpoint preserved + resumable: the failure parked nothing destructively.
    boundary = coordinator.checkpoint(run.run_id, phase="heartbeat", payload={"on": "provider"})
    assert coordinator.latest_checkpoint(run.run_id) == boundary
    assert coordinator.get_run(run.run_id) in coordinator.find_resumable_runs()


@pytest.mark.timeout(TIMEOUT)
async def test_provider_malformed_json_is_permanent_and_dead_lettered_with_error_class(
    coordinator: RunCoordinator,
) -> None:
    """(c) malformed provider JSON: permanent (schema), DLQ with error_class.

    The injection is a truncated response body from a real adapter: the parse
    failure is raised by production code, not by this test.
    """
    provider = _openai_provider(
        body='{"choices": [{"message": {"content": "resposta truncada'
    )
    try:
        with pytest.raises(json.JSONDecodeError) as excinfo:
            await provider.chat_complete("scripted-model", _MESSAGES)
    finally:
        await provider.aclose()
    error = excinfo.value

    # detected + classified: a schema defect in the payload is permanent.
    verdict = classify_error(error)
    assert verdict["recoverability"] == RECOVERABILITY_PERMANENT
    assert verdict["error_class"] == "jsondecodeerror"
    assert verdict["retry_after"] is None, "a permanent failure is never auto-retried"

    # It reaches the dead-letter queue carrying its class, with no retry delay.
    run = _active_run(coordinator)
    service = DeadLetterService(coordinator)
    parked = service.park(
        {
            "run_id": run.run_id,
            "task_id": "turn-1",
            "error_class": type(error).__name__,
            "sanitized_traceback": "Expecting ',' delimiter: line 1 column 44",
        }
    )
    assert parked["error_class"] == "JSONDecodeError"
    assert parked["recoverability"] == RECOVERABILITY_PERMANENT
    assert parked["retry_after"] is None
    assert service.list(run_id=run.run_id, recoverability=RECOVERABILITY_PERMANENT) == [parked]
    assert service.list(run_id=run.run_id, recoverability=RECOVERABILITY_TRANSIENT) == []

    # A malformed payload cannot serve as evidence, so the run fails explicitly
    # (with an observable reason) instead of completing on it — and the
    # checkpoint it wrote before the failure is still there to resume from.
    lifecycle = RunLifecycle.begin(
        goal="entregar a resposta",
        session_id="fi-malformed",
        definition_of_done=["resposta entregue ao utilizador"],
    )
    assert lifecycle is not None
    lifecycle.heartbeat(blocked_on="provider")
    assert _checkpoint_count(coordinator, lifecycle.run_id) >= 1

    loop = PrimaryLoop(run_id=lifecycle.run_id, query="faz o trabalho", stream=None)
    loop.outcome.failed = True
    loop.outcome.error = f"provider returned malformed JSON: {type(error).__name__}"
    _close_primary_run_lifecycle(lifecycle, loop)

    record = coordinator.get_run(lifecycle.run_id)
    assert record is not None
    assert record.state is RunState.FAILED
    assert "malformed JSON" in record.stop_reason
    preserved = coordinator.latest_checkpoint(lifecycle.run_id)
    assert preserved is not None
    assert preserved.payload["signal"]["blocked_on"] == "provider"


@pytest.mark.timeout(TIMEOUT)
async def test_provider_model_unavailable_fails_the_run_with_an_observable_reason(
    coordinator: RunCoordinator,
) -> None:
    """(d) model unavailable: run FAILED with a reason, checkpoint preserved.

    A missing model is permanent (a retry asks for the same missing model), so
    the run must fail loudly rather than loop, and never look completed.
    """
    provider = _ollama_like_client(
        status=404, body='{"error": "model \'ghost\' not found"}'
    )
    try:
        with pytest.raises(Exception) as excinfo:
            await provider.chat_complete("ghost", _MESSAGES)
    finally:
        await provider.aclose()
    error = excinfo.value

    # detected: the run saw it, and the missing model is in the error text.
    assert "ghost" in str(error)
    assert "404" in str(error)

    # classified: permanent — the request names something that does not exist.
    verdict = classify_error(error)
    assert verdict["recoverability"] == RECOVERABILITY_PERMANENT
    assert verdict["retry_after"] is None

    # Every provider in the chain is down the same way: the call itself fails,
    # so the run has no answer to stand on.
    chain = ResilientLLMProvider(
        _FailingProvider(RuntimeError("model 'ghost' not found")),
        [_FailingProvider(RuntimeError("model 'ghost' not found"))],
    )
    with pytest.raises(Exception, match="All providers failed"):
        await chain.chat_complete("ghost", _MESSAGES)

    # The primary lane closes the run as FAILED with the reason recorded, and
    # the checkpoint written before the provider call survives it.
    lifecycle = RunLifecycle.begin(
        goal="entregar a resposta",
        session_id="fi-model",
        definition_of_done=["resposta entregue ao utilizador"],
    )
    assert lifecycle is not None
    lifecycle.checkpoint("after_planning", plan_id="p1")
    assert _checkpoint_count(coordinator, lifecycle.run_id) >= 1

    loop = PrimaryLoop(run_id=lifecycle.run_id, query="faz o trabalho", stream=None)
    loop.outcome.failed = True
    loop.outcome.error = f"provider esgotado: {error}"
    _close_primary_run_lifecycle(lifecycle, loop)

    record = coordinator.get_run(lifecycle.run_id)
    assert record is not None
    assert record.state is RunState.FAILED
    assert "ghost" in record.stop_reason
    assert record.stop_reason
    resumable = [item.run_id for item in coordinator.find_resumable_runs()]
    assert lifecycle.run_id not in resumable, "a failed run is not offered as resumable"
    preserved = coordinator.latest_checkpoint(lifecycle.run_id)
    assert preserved is not None
    assert preserved.payload["plan_id"] == "p1"


# ══════════════════════════════════════════════════════════════════════════
# 2. TOOL
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.timeout(TIMEOUT)
async def test_tool_handler_crash_is_classified_and_never_completes_the_run(
    coordinator: RunCoordinator,
) -> None:
    """(a) tool crash: detected, classified, and never a silent COMPLETED."""

    async def crashing(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("tool handler exploded")

    with injected_tool(CRASH_TOOL, handler=crashing):
        result = await execute_tool(CRASH_TOOL, SESSION, {})
        assert result["ok"] is False
        assert result["error_category"] == "tool"
        assert "exploded" in result["error"]
        assert result["consecutive_failures"] == 1
        assert result["evidence"]["verified"] is False

        # classified: a crash is something the queue can act on (it has a class).
        verdict = classify_error(RuntimeError("tool handler exploded"))
        assert verdict["error_class"] == "runtimeerror"
        assert verdict["recoverability"] in {RECOVERABILITY_PERMANENT, "unknown"}
        assert verdict["reason"]

        # A crashed handler is not a confirmed side effect: a replay cannot be
        # mistaken for work already done.
        lifecycle = RunLifecycle.begin(
            goal="corrigir o ficheiro",
            session_id="fi-crash",
            definition_of_done=["correção aplicada"],
        )
        assert lifecycle is not None
        assert not lifecycle.side_effect_confirmed(tool=CRASH_TOOL, args={}, task_id="cycle-1")
        assert (
            lifecycle.finish([{"requirement": "correção aplicada", "verdict": "UNKNOWN"}]) is False
        )
        record = coordinator.get_run(lifecycle.run_id)
        assert record is not None
        assert record.state is not RunState.COMPLETED

        # The circuit breaker stops the loop from hammering the broken tool, and
        # the run then fails explicitly with the reason — never silently done.
        for _ in range(2):
            assert (await execute_tool(CRASH_TOOL, SESSION, {}))["ok"] is False
        blocked = await execute_tool(CRASH_TOOL, SESSION, {})
        assert blocked["ok"] is False
        assert blocked["circuit_open"] is True
        assert tool_failure_count(CRASH_TOOL, SESSION) == 3

        lifecycle.fail(f"tool {CRASH_TOOL} crashed: tool handler exploded")
        failed = coordinator.get_run(lifecycle.run_id)
        assert failed is not None
        assert failed.state is RunState.FAILED
        assert "crashed" in failed.stop_reason


@pytest.mark.timeout(TIMEOUT)
async def test_tool_timeout_charges_the_run_and_leaves_a_recoverable_state(
    coordinator: RunCoordinator,
) -> None:
    """(b) tool timeout: usage/BudgetVerdict recorded, WAITING_TOOL → RUNNING."""

    async def never_finishes(**_kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {"ok": True}  # pragma: no cover - the timeout wins first

    with injected_tool(TIMEOUT_TOOL, handler=never_finishes, timeout_seconds=0.2):
        run = _active_run(coordinator, budget={"max_tool_calls": 1})
        token = set_current_run_id(run.run_id)
        try:
            first = await execute_tool(TIMEOUT_TOOL, SESSION, {})
        finally:
            reset_current_run_id(token)

        # detected: the timeout is reported as a timeout, not as a hang.
        assert first["ok"] is False
        assert first["error_category"] == "timeout"
        assert first["timed_out"] is True
        assert first["exit_code"] == 124

        # usage registered against the run's budget.
        verdict = coordinator.budget_status(run.run_id)
        assert verdict.usage["tool_calls"] == 1
        assert verdict.ok is True

        # The next call is refused by the budget *before* any handler runs, and
        # the verdict is the one the operator configured.
        token = set_current_run_id(run.run_id)
        try:
            blocked = await execute_tool(TIMEOUT_TOOL, SESSION, {})
        finally:
            reset_current_run_id(token)
        assert blocked["ok"] is False
        assert blocked["error_category"] == "budget_exceeded"
        assert blocked["budget_exceeded"] == {"tool_calls": "2>1"}
        assert blocked["result"] is None, "no handler ran"

        exceeded = coordinator.budget_status(run.run_id)
        assert exceeded.ok is False
        assert exceeded.exceeded == {"tool_calls": "2>1"}
        assert exceeded.usage["tool_calls"] == 2

        # The state machine: the run was waiting on the tool, and waiting →
        # running is a legal move, so a timed-out tool leaves a recoverable run.
        waiting = coordinator.transition(run.run_id, RunState.WAITING_TOOL)
        assert waiting.state is RunState.WAITING_TOOL
        resumed = coordinator.transition(run.run_id, RunState.RUNNING)
        assert resumed.state is RunState.RUNNING
        assert coordinator.get_run(run.run_id) in coordinator.find_resumable_runs()


@pytest.mark.timeout(TIMEOUT)
async def test_malformed_tool_result_is_permanent_and_cannot_serve_as_evidence(
    coordinator: RunCoordinator,
) -> None:
    """(c) malformed tool result: surfaced as a failure, permanent, no evidence.

    This build validates a tool's *arguments* against its schema but has no
    dedicated result-schema validator, so the injection is a handler that
    answers with a schema-invalid payload: ``execute_tool`` must report it as a
    failure (never as success), and the failure must classify as permanent.
    """

    async def malformed(**_kwargs: Any) -> dict[str, Any]:
        # A result that violates the contract the caller expects: no path, no
        # content, and an explicit error field instead of the required data.
        return {"status": "error", "summary": "invalid result: missing required 'path'"}

    with injected_tool(MALFORMED_TOOL, handler=malformed):
        result = await execute_tool(MALFORMED_TOOL, SESSION, {})
        assert result["ok"] is False
        assert result["error_category"] == "tool"
        assert "invalid result" in result["error"]
        assert result["evidence"]["verified"] is False

        # classified: a schema defect is permanent — a retry repeats it.
        verdict = classify_error(result["error"])
        assert verdict["recoverability"] == RECOVERABILITY_PERMANENT
        assert verdict["retry_after"] is None

        run = _active_run(coordinator)
        service = DeadLetterService(coordinator)
        parked = service.park(
            {
                "run_id": run.run_id,
                "task_id": "cycle-1",
                "error_class": "SchemaError",
                "sanitized_traceback": result["error"],
            }
        )
        assert parked["recoverability"] == RECOVERABILITY_PERMANENT
        assert parked["retry_after"] is None
        assert parked["error_class"] == "SchemaError"

        # A malformed result is not evidence: the run cannot complete on it.
        lifecycle = RunLifecycle.begin(
            goal="aplicar a correção",
            session_id="fi-malformed-result",
            definition_of_done=["correção aplicada"],
        )
        assert lifecycle is not None
        assert (
            lifecycle.finish(
                [
                    {
                        "requirement": "correção aplicada",
                        "verdict": "UNKNOWN",
                        "evidence": result,
                    }
                ]
            )
            is False
        )
        record = coordinator.get_run(lifecycle.run_id)
        assert record is not None
        assert record.state is not RunState.COMPLETED
        assert record in coordinator.find_resumable_runs()


@pytest.mark.timeout(TIMEOUT)
def test_killed_process_leaves_a_resumable_run_and_never_repeats_a_confirmed_side_effect(
    tmp_path: Path, db_path: Path
) -> None:
    """(d) process death: real subprocess, SIGKILL mid-side-effect.

    The child process confirms one side effect (real file append + ledger row),
    then starts a second one and is killed between the real-world action and its
    durable record. The run must stay resumable, keep its checkpoint, and never
    repeat the *confirmed* effect.
    """
    effect_file = tmp_path / "side-effect.txt"
    ready = tmp_path / "ready.marker"
    mid = tmp_path / "mid.marker"
    log_path = tmp_path / "worker.log"

    parent = RunCoordinator(db_path=str(db_path))
    run = _active_run(parent, definition_of_done=["trabalho aplicado"])
    first_key = side_effect_idempotency_key(
        run.run_id, "cycle-1", "write_file", {"path": "side-effect.txt", "content": "one"}
    )
    second_key = side_effect_idempotency_key(
        run.run_id, "cycle-2", "write_file", {"path": "side-effect.txt", "content": "two"}
    )
    parent.checkpoint(run.run_id, phase="after_planning", payload={"plan_id": "p1", "steps": 2})

    command = [
        str(CHILD_PYTHON),
        "-m",
        "backend.tests.integration.test_failure_injection_worker",
        "--db",
        str(db_path),
        "--run-id",
        run.run_id,
        "--first-key",
        first_key,
        "--second-key",
        second_key,
        "--effect-file",
        str(effect_file),
        "--ready-marker",
        str(ready),
        "--mid-marker",
        str(mid),
    ]
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), PYTHONUNBUFFERED="1")
    with log_path.open("w", encoding="utf-8") as log:
        child = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, repo interpreter
            command,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            assert _wait_for(mid.exists), (
                "the child never reached the middle of its second side effect; "
                f"log tail:\n{log_path.read_text(encoding='utf-8', errors='replace')[-2000:]}"
            )
        finally:
            child.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=60)

    assert child.returncode is not None

    # detected + resumable: the run survived the process going away.
    rows = _side_effect_rows(db_path, run.run_id)
    assert [row["idempotency_key"] for row in rows] == [first_key], rows
    assert effect_file.read_text(encoding="utf-8") == "effect-one\neffect-two\n"

    # checkpoint preserved: the newest boundary is the mid-effect one.
    latest = parent.latest_checkpoint(run.run_id)
    assert latest is not None
    assert latest.phase == "before_side_effect"
    assert latest.payload["idempotency_key"] == second_key
    assert parent.is_side_effect_confirmed(run.run_id, first_key)
    assert not parent.is_side_effect_confirmed(run.run_id, second_key)

    # resumed: the run is offered as resumable and restores its checkpoint.
    resumable = [item.run_id for item in parent.find_resumable_runs()]
    assert run.run_id in resumable
    restored = parent.restore(run.run_id)
    assert restored.checkpoint_id == latest.checkpoint_id
    assert parent.get_run(run.run_id).state is RunState.RECOVERING

    # no duplicate side effect: replaying the confirmed effect is recognised as
    # a replay, the ledger keeps exactly one row, and the file is untouched.
    assert parent.is_side_effect_confirmed(run.run_id, first_key) is True
    parent.record_side_effect(
        run.run_id, first_key, kind="write_file", result_digest="digest-effect-one"
    )
    rows_after = _side_effect_rows(db_path, run.run_id)
    assert [row["idempotency_key"] for row in rows_after] == [first_key]
    assert effect_file.read_text(encoding="utf-8").count("effect-one") == 1
    assert effect_file.read_text(encoding="utf-8").count("effect-two") == 1

    # final result: the run can finish — but only through the definition of done.
    parent.transition(run.run_id, RunState.RUNNING, reason="recovered and continuing")
    with pytest.raises(DoDNotSatisfied):
        parent.complete(run.run_id, [])  # no evidence: never a free completion
    completed = parent.complete(
        run.run_id,
        [{"requirement": "trabalho aplicado", "verdict": "PASS", "evidence": {"file": "x"}}],
    )
    assert completed.state is RunState.COMPLETED


# ══════════════════════════════════════════════════════════════════════════
# 3. INFRA
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.timeout(TIMEOUT)
def test_database_outage_does_not_corrupt_the_run_and_the_recovery_is_recorded(
    coordinator: RunCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) DB unavailable: the run is not corrupted and recovers observably."""
    lifecycle = RunLifecycle.begin(
        goal="entregar a resposta",
        session_id="fi-db-outage",
        definition_of_done=["resposta entregue ao utilizador"],
    )
    assert lifecycle is not None
    boundary = coordinator.checkpoint(
        lifecycle.run_id, phase="after_planning", payload={"plan_id": "p1"}
    )
    before = coordinator.get_run(lifecycle.run_id)
    assert before is not None
    checkpoints_before = _checkpoint_count(coordinator, lifecycle.run_id)

    with db_outage(monkeypatch, "unable to open database file"):
        # The outage is real at the persistence layer: it raises there, so the
        # run layer's tolerance below is not vacuous.
        with pytest.raises(sqlite3.OperationalError):
            coordinator.checkpoint(lifecycle.run_id, phase="heartbeat", payload={})

        # A durability outage degrades durability, never the user's turn.
        lifecycle.heartbeat(blocked_on="database")
        lifecycle.checkpoint("after_task", task_id="cycle-1")
        lifecycle.record_task_completed("cycle-1", name="model turn")
        lifecycle.update_progress(current_task_id="cycle-2")
        lifecycle.before_side_effect(tool="write_file", args={"path": "a.py"}, task_id="cycle-2")
        lifecycle.after_side_effect(
            tool="write_file", args={"path": "a.py"}, task_id="cycle-2", result={"written": True}
        )
        assert not lifecycle.side_effect_confirmed(
            tool="write_file", args={"path": "a.py"}, task_id="cycle-2"
        )
        # No evidence, no completion — the gate still refuses during the outage.
        assert (
            lifecycle.finish(
                [{"requirement": "resposta entregue ao utilizador", "verdict": "UNKNOWN"}]
            )
            is False
        )

    # Nothing was written, so nothing was corrupted: the run is exactly where
    # it was, and its checkpoint is still the one it wrote before the outage.
    after = coordinator.get_run(lifecycle.run_id)
    assert after is not None
    assert after.state is before.state
    assert after.goal == before.goal
    assert after.requirements == before.requirements
    assert _checkpoint_count(coordinator, lifecycle.run_id) == checkpoints_before
    assert coordinator.latest_checkpoint(lifecycle.run_id) == boundary
    assert not lifecycle.side_effect_confirmed(
        tool="write_file", args={"path": "a.py"}, task_id="cycle-2"
    ), "an unacknowledged side effect must not claim to be confirmed"

    # Recovery, recorded: the same writes now succeed against the same run.
    recovered = coordinator.checkpoint(
        lifecycle.run_id, phase="after_task", payload={"task_id": "cycle-1", "ok": True}
    )
    assert coordinator.latest_checkpoint(lifecycle.run_id) == recovered
    assert _checkpoint_count(coordinator, lifecycle.run_id) == checkpoints_before + 1
    assert coordinator.get_run(lifecycle.run_id) in coordinator.find_resumable_runs()
    restored = coordinator.restore(lifecycle.run_id)
    assert restored.checkpoint_id == recovered.checkpoint_id


@pytest.mark.timeout(TIMEOUT)
def test_database_lock_is_survived_by_the_run_and_the_watchdog(
    coordinator: RunCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) DB locked: the run keeps its state and the watchdog still decides."""
    lifecycle = RunLifecycle.begin(
        goal="entregar a resposta",
        session_id="fi-db-lock",
        definition_of_done=["resposta entregue ao utilizador"],
    )
    assert lifecycle is not None
    boundary = coordinator.checkpoint(
        lifecycle.run_id, phase="after_planning", payload={"plan_id": "p1"}
    )
    before = coordinator.get_run(lifecycle.run_id)
    assert before is not None

    # The heartbeat is backdated *before* the lock: a stalled run must still be
    # recognisable while the database cannot be read.
    _stale_heartbeat(coordinator, lifecycle.run_id, 600)
    stalled = coordinator.get_run(lifecycle.run_id)
    assert stalled is not None

    with db_outage(monkeypatch, "database is locked"):
        # The run layer's writes degrade instead of raising.
        lifecycle.heartbeat(blocked_on="database")
        lifecycle.update_progress(current_task_id="cycle-9")
        assert lifecycle.finish([]) is False
        assert lifecycle.closed is False

        # The watchdog keeps working off the last known state: a locked database
        # must neither blind it nor break it.
        watchdog = RunWatchdog(coordinator, clock=FakeClock(), stale_heartbeat_seconds=60.0)
        decision = watchdog.decide(stalled)
        assert decision is not None
        assert WatchdogSignal.STALE_HEARTBEAT.value in decision.signal_names
        assert decision.action in {
            WatchdogAction.PAUSE,
            WatchdogAction.ESCALATE,
            WatchdogAction.RECOVER,
            WatchdogAction.FAIL,
        }
        assert decision.action.value not in {"complete", "completed"}
        # Its view of the run is degraded, not wrong: no budget verdict, and it
        # says so instead of guessing.
        assert not any(
            signal["signal"] == WatchdogSignal.BUDGET_EXCEEDED.value for signal in decision.signals
        )
        assert watchdog.snapshot()["watching_tasks"] is False

    # Recovery: the run is exactly where it was, and writable again.
    after = coordinator.get_run(lifecycle.run_id)
    assert after is not None
    assert after.state is before.state
    assert after.goal == before.goal
    assert coordinator.latest_checkpoint(lifecycle.run_id) == boundary
    recovered = coordinator.checkpoint(
        lifecycle.run_id, phase="heartbeat", payload={"blocked_on": "recovered"}
    )
    assert coordinator.latest_checkpoint(lifecycle.run_id) == recovered
    assert coordinator.get_run(lifecycle.run_id) in coordinator.find_resumable_runs()


# Infra (c) backend restart is deliberately NOT repeated here: it is proven by
# backend/tests/integration/test_run_resume_e2e.py::
# test_real_restart_resumes_the_run_the_process_left_open (real uvicorn, SIGKILL
# mid-turn, resume across a restart, no duplicate side effect).


@pytest.mark.timeout(TIMEOUT)
async def test_worker_crash_recovers_the_task_quarantined_and_never_auto_runs() -> None:
    """(d) worker crash: a RUNNING task is recovered quarantined, never auto-run."""
    calls: list[int] = []

    async def write_effect(**_kwargs: Any) -> dict[str, bool]:
        calls.append(1)
        return {"ok": True}

    manager = AutonomousTaskManager(EventBus())
    manager.handlers.register("fi_write_effect", write_effect, read_only=False)
    task_id = await manager.create_custom_task(
        name="fi write-effect task",
        task_type=TaskType.MONITORING,
        handler_name="fi_write_effect",
        parameters={"n": 1},
        max_retries=3,
    )
    assert calls == []
    await manager.stop()

    # The worker crashed mid-execution: the persisted row is left 'running',
    # exactly as a killed process leaves it.
    from backend.persistence.db import update_scheduled_task_status

    update_scheduled_task_status(task_id, "running", started_at=_iso(0))

    # A brand-new process recovers the task. Under the default policy it must be
    # quarantined: a handler may already have applied half of its side effects.
    recovered = AutonomousTaskManager(EventBus())
    recovered.handlers.register("fi_write_effect", write_effect, read_only=False)
    try:
        await recovered.start()
        task = await recovered.get_task(task_id)
        assert task is not None
        assert task.status is TaskStatus.WAITING
        assert task.metadata.get("recovered_state") == "interrupted"
        assert task.metadata.get("interrupted") is True
        # Not in the execution queue. The built-in read-only tasks a fresh start
        # schedules are a different matter; the interrupted one is not.
        assert all(item.task_id != task_id for item in recovered.scheduler.task_queue)
        assert task_id in recovered.scheduler._quarantined

        await asyncio.sleep(1.5)  # let the scheduler loop prove it will not run
        assert calls == [], "an interrupted task must never be auto-run"
        assert (await recovered.get_task(task_id)).status is TaskStatus.WAITING

        # Even the explicit opt-in must not run an interrupted task.
        await recovered.stop()
        opted_in = AutonomousTaskManager(EventBus())
        opted_in.handlers.register("fi_write_effect", write_effect, read_only=False)
        try:
            await opted_in.start(resume_pending=True)
            await asyncio.sleep(1.5)
            assert calls == []
            assert (await opted_in.get_task(task_id)).status is TaskStatus.WAITING

            # An operator requeue is the only thing that re-arms it.
            assert await opted_in.requeue_task(task_id) == "requeued"
            await asyncio.sleep(1.5)
            assert calls == [1], "an explicit requeue must re-arm the task"
            assert (await opted_in.get_task(task_id)).status is TaskStatus.COMPLETED
        finally:
            await opted_in.stop()
    finally:
        await recovered.stop()


# ══════════════════════════════════════════════════════════════════════════
# 4. AGENT
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.timeout(TIMEOUT)
async def test_invalid_tool_call_is_refused_by_the_contract_and_never_a_fake_success(
    coordinator: RunCoordinator,
) -> None:
    """(a) invalid tool call: the contract rejects it; the run never fakes it."""
    result = await execute_tool("fi_no_such_tool", SESSION, {"anything": 1})

    # detected + rejected: an unknown tool is a typed rejection, not a success.
    assert result["ok"] is False
    assert result["error_category"] == "unknown_tool"
    assert "fi_no_such_tool" in result["error"]
    assert result["result"] is None
    assert result["evidence"]["verified"] is False

    # An unknown tool is not a side-effecting tool, so nothing was applied and
    # nothing is waiting in the ledger.
    assert is_side_effecting_tool("fi_no_such_tool") is False

    lifecycle = RunLifecycle.begin(
        goal="aplicar a correção",
        session_id="fi-unknown-tool",
        definition_of_done=["correção aplicada"],
    )
    assert lifecycle is not None
    assert not lifecycle.side_effect_confirmed(
        tool="fi_no_such_tool", args={"anything": 1}, task_id="cycle-1"
    )

    # The run either continues (the rejection is one recoverable step) or fails
    # explicitly — what it must never do is complete on the strength of it.
    assert (
        lifecycle.finish([{"requirement": "correção aplicada", "verdict": "UNKNOWN"}]) is False
    )
    continuing = coordinator.get_run(lifecycle.run_id)
    assert continuing is not None
    assert continuing.state is not RunState.COMPLETED
    assert continuing in coordinator.find_resumable_runs()

    lifecycle.fail("tool fi_no_such_tool is not available in this build")
    failed = coordinator.get_run(lifecycle.run_id)
    assert failed is not None
    assert failed.state is RunState.FAILED
    assert "not available" in failed.stop_reason


@pytest.mark.timeout(TIMEOUT)
def test_repeated_error_stagnation_is_decided_by_the_watchdog_and_never_completed(
    coordinator: RunCoordinator,
) -> None:
    """(b) repeated error: the watchdog sees stagnation and decides, never completes."""
    run = _active_run(coordinator, definition_of_done=["resposta entregue"])
    # The loop symptom: the same failing tool, again and again.
    for _ in range(4):
        coordinator.checkpoint(
            run.run_id, phase="after_task", payload={"tool_calls": ["fi_broken_tool"]}
        )
    # Progress was attempted (retries) and then stopped (heartbeat went quiet).
    coordinator.update_progress(run.run_id, current_task_id="cycle-9", retry_count=5)
    _stale_heartbeat(coordinator, run.run_id, 600)

    watchdog = RunWatchdog(
        coordinator,
        clock=FakeClock(),
        stale_heartbeat_seconds=60.0,
        repeated_tool_threshold=3,
    )
    decision = watchdog.decide(run)

    # detected: both the loop and the absence of progress are reported.
    assert decision is not None
    assert WatchdogSignal.REPEATED_TOOL.value in decision.signal_names
    assert WatchdogSignal.STALE_HEARTBEAT.value in decision.signal_names
    repeated = next(
        signal
        for signal in decision.signals
        if signal["signal"] == WatchdogSignal.REPEATED_TOOL.value
    )
    assert repeated["tool"] == "fi_broken_tool"
    assert repeated["occurrences"] == 4

    # decided: PAUSE / ESCALATE / FAIL / RECOVER when the watchdog owns the
    # transition, or a strategy handover when the orchestrator does. Never a
    # completion: nothing in the action set can close a run as COMPLETED.
    assert decision.action in {
        WatchdogAction.PAUSE,
        WatchdogAction.ESCALATE,
        WatchdogAction.FAIL,
        WatchdogAction.RECOVER,
        WatchdogAction.CHANGE_STRATEGY,
        WatchdogAction.REPLAN,
        WatchdogAction.RETRY,
    }
    assert decision.action.value not in {"complete", "completed"}

    # A sweep records the decision durably, next to the run's own boundaries.
    asyncio.run(watchdog.evaluate_once())
    recorded = [
        checkpoint
        for checkpoint in coordinator.list_checkpoints(run.run_id, limit=5)
        if checkpoint.payload.get("watchdog")
    ]
    assert recorded, "the watchdog must leave evidence behind"
    assert recorded[0].payload["action"] == decision.action.value
    assert recorded[0].phase in {"watchdog", "heartbeat"}

    # Whatever the action, the run is not completed by it.
    after = coordinator.get_run(run.run_id)
    assert after is not None
    assert after.state is not RunState.COMPLETED
    assert after.state in {
        RunState.RUNNING,
        RunState.PAUSED,
        RunState.FAILED,
        RunState.RECOVERING,
    }


@pytest.mark.timeout(TIMEOUT)
def test_watchdog_fails_a_run_whose_repeated_errors_exhausted_its_budget(
    coordinator: RunCoordinator,
) -> None:
    """(b, cont.) repeated errors that exhaust a budget: FAIL, with a reason."""
    run = _active_run(coordinator, budget={"max_tool_calls": 2})
    coordinator.record_usage(run.run_id, tool_calls=3)
    for _ in range(3):
        coordinator.checkpoint(
            run.run_id, phase="after_task", payload={"tool_calls": ["fi_broken_tool"]}
        )

    watchdog = RunWatchdog(coordinator, clock=FakeClock(), stale_heartbeat_seconds=60.0)
    decision = watchdog.decide(run)
    assert decision is not None
    assert WatchdogSignal.BUDGET_EXCEEDED.value in decision.signal_names
    assert decision.action is WatchdogAction.FAIL
    assert decision.applies_itself is True

    record = watchdog.apply(decision)
    assert record is not None
    assert record.state is RunState.FAILED
    assert "budget exceeded" in record.stop_reason
    # The evidence that produced the decision is still readable afterwards.
    assert coordinator.list_checkpoints(run.run_id, limit=5)


@pytest.mark.timeout(TIMEOUT)
def test_context_overflow_is_detected_and_shrunk_instead_of_losing_the_run(
    coordinator: RunCoordinator,
) -> None:
    """(c) context overflow: the shrink hook fires; the run gate still holds.

    The hook is the ReAct loop's own (``AgentBase._is_context_overflow`` /
    ``_emergency_shrink_context``); the primary run lane has no overflow hook of
    its own, so nothing is claimed for it here beyond the definition-of-done gate
    that keeps a truncated answer from looking like a completed run.
    """

    class _OverflowProbe(AgentBase):
        name = "fi-overflow-probe"
        model_key = "nano"
        prompt_file = "router"

        async def _execute(self, request):  # noqa: ANN001 - mirrors the ABC
            yield "ok"  # pragma: no cover - the probe never executes a turn

    agent = _OverflowProbe()

    # detected: the provider wordings that mean "the prompt does not fit".
    for error in (
        ValueError("This model's maximum context length is 8192 tokens"),
        ContextOverflowError("context overflow: 9000 tokens + 512 output reserve"),
        RuntimeError("request too large for gpt-4o"),
    ):
        assert agent._is_context_overflow(error) is True, error
    assert agent._is_context_overflow(ValueError("boom")) is False
    coded = RuntimeError("provider refused the request")
    coded.code = "context_window_exceeded"  # structured code, no prose
    assert agent._is_context_overflow(coded) is True

    # The emergency path drops the oldest half, keeps the newest steps and says
    # what is missing instead of inventing content.
    steps = "\nTool ".join(f"tool_{index} returned: {'x' * 200}" for index in range(12))
    shrunk = agent._emergency_shrink_context(steps)
    assert len(shrunk) < len(steps)
    assert "Context truncated after a context overflow" in shrunk
    assert "tool_11" in shrunk, "the newest steps are the ones worth keeping"
    assert "tool_0" not in shrunk

    # The run-level consequence: an overflow classifies as *transient*. The agent
    # answers it with an emergency-shrink and the run continues on the reduced
    # context, so re-arming the parked turn is worthwhile and the queue carries a
    # retry delay. This is intentional — a context overflow the agent can shrink
    # out of is "retry later, with less input", not a defect in the work.
    service = DeadLetterService(coordinator)
    run = _active_run(coordinator, definition_of_done=["resposta entregue"])
    parked = service.park(
        {
            "run_id": run.run_id,
            "task_id": "turn-1",
            "error_class": ContextOverflowError.__name__,
            "sanitized_traceback": "context length exceeded",
        }
    )
    # RESOLVED finding: ContextOverflowError used to fall through to "unknown" (a
    # human triaged it) because the classifier had no entry for it. It is now
    # classified transient on purpose — the agent shrinks the context and carries
    # on — so the parked turn is re-armed after retry_after; its base ValueError
    # (a real defect) stays permanent because class-name matching is exact.
    assert parked["recoverability"] == RECOVERABILITY_TRANSIENT
    assert parked["retry_after"], "an overflow is re-armed later; retry_after is set"

    # A shrunk answer is still not evidence: the run cannot complete on it.
    lifecycle = RunLifecycle.begin(
        goal="entregar a resposta",
        session_id="fi-overflow",
        definition_of_done=["resposta entregue ao utilizador"],
    )
    assert lifecycle is not None
    assert (
        lifecycle.finish(
            [{"requirement": "resposta entregue ao utilizador", "verdict": "UNKNOWN"}]
        )
        is False
    )
    record = coordinator.get_run(lifecycle.run_id)
    assert record is not None
    assert record.state is not RunState.COMPLETED
    assert record in coordinator.find_resumable_runs()


def test_primary_lane_dod_requirements_are_the_ones_the_e2e_checks() -> None:
    """The requirements the primary lane enforces, read from the real module.

    Pinned so this suite's completion assertions cannot drift from the ones the
    restart e2e asserts on the same lane.
    """
    assert PRIMARY_DOD_ANSWER
    assert PRIMARY_DOD_VERIFIED
    assert PRIMARY_DOD_ANSWER != PRIMARY_DOD_VERIFIED
