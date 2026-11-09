"""A dead letter is a promise: every parked failure can be read and acted on.

These tests pin the two halves of that promise:

* :func:`classify_error` — a rate limit and a schema error must never receive
  the same answer, or the queue either retries the unretryable forever or
  abandons the retryable immediately.
* :class:`DeadLetterService` — the inspect → retry → requeue → abandon cycle,
  the refusal paths (no task manager, retry too soon, nothing to re-arm), and
  the HTTP surface over them, including the one route-level fact that matters
  most: nothing here is reachable unauthenticated.

The router is exercised on its own app rather than through
``backend.orchestrator.main``: mounting it there belongs to the wiring change,
while its contract (paths, auth, status mapping) is testable here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware import auth as auth_module
from backend.orchestrator.routes.dead_letters import router
from backend.runtime.dead_letter_service import (
    RECOVERABILITY_PERMANENT,
    RECOVERABILITY_TRANSIENT,
    RECOVERABILITY_UNKNOWN,
    DeadLetterError,
    DeadLetterNotFound,
    DeadLetterRejected,
    DeadLetterService,
    DeadLetterUnavailable,
    classify_error,
)
from backend.runtime.run_coordinator import RunCoordinator
from backend.token_management import ContextOverflowError


@pytest.fixture
def coordinator() -> RunCoordinator:
    """The application database coordinator (what the routes use)."""
    return RunCoordinator()


class FakeTaskManager:
    """The slice of the task manager the service delegates to."""

    def __init__(self, result: str = "requeued") -> None:
        self.result = result
        self.calls: list[str] = []

    async def requeue_task(self, task_id: str) -> str:
        self.calls.append(task_id)
        return self.result


def _park(service: DeadLetterService, *, error: str = "TimeoutError", **kwargs) -> dict:
    entry = {
        "run_id": "run-1",
        "task_id": "task-1",
        "error_class": error,
        "sanitized_traceback": "Traceback (most recent call last): ...",
        "attempts": 3,
        "last_tool": "web_search",
        "last_provider": "openai",
    }
    entry.update(kwargs)
    return service.park(entry)


# ───── classification ────────────────────────────────────────────────────


class TestClassifyError:
    @pytest.mark.parametrize(
        "error",
        [
            "429 Too Many Requests",
            "503 Service Unavailable",
            "500 internal error",
            "502 Bad Gateway",
            TimeoutError("request timed out after 30s"),
            ConnectionError("connection reset by peer"),
            "rate limit exceeded, retry later",
            "The service is temporarily overloaded",
        ],
    )
    def test_transient_failures_are_retryable(self, error: object) -> None:
        verdict = classify_error(error)

        assert verdict["recoverability"] == RECOVERABILITY_TRANSIENT
        assert verdict["retry_after"] and verdict["retry_after"] > 0

    @pytest.mark.parametrize(
        "error",
        [
            ValueError("schema mismatch: expected a string"),
            TypeError("argument 'path' must be str"),
            KeyError("max_cost_usd"),
            "malformed tool arguments",
            "unknown budget limits: ['max_cost']",
            "invalid run transition",
        ],
    )
    def test_permanent_failures_are_not_retried(self, error: object) -> None:
        verdict = classify_error(error)

        assert verdict["recoverability"] == RECOVERABILITY_PERMANENT
        assert verdict["retry_after"] is None

    def test_an_unknown_failure_is_reported_as_unknown(self) -> None:
        verdict = classify_error(RuntimeError("something nobody predicted"))

        assert verdict["recoverability"] == RECOVERABILITY_UNKNOWN
        assert verdict["retry_after"] is None

    def test_a_transient_error_class_name_beats_its_message(self) -> None:
        """``TimeoutError("invalid schema")`` is still a timeout to retry."""
        verdict = classify_error(TimeoutError("invalid schema"))

        assert verdict["recoverability"] == RECOVERABILITY_TRANSIENT

    def test_a_permanent_class_beats_a_transient_looking_message(self) -> None:
        verdict = classify_error(ValueError("503 from an upstream service"))

        assert verdict["recoverability"] == RECOVERABILITY_PERMANENT

    def test_the_reason_explains_the_verdict(self) -> None:
        assert classify_error(ValueError("bad"))["reason"]
        assert classify_error("429 slow down")["reason"]

    def test_a_context_overflow_is_transient_because_the_agent_shrinks(self) -> None:
        """An overflow is the world asking for less input, not a defect.

        The ReAct agent answers it with an emergency-shrink and the run
        continues on the reduced context (``AgentBase._emergency_shrink_context``),
        so it belongs with the rate limits, not with the schema errors.
        """
        verdict = classify_error(
            ContextOverflowError("context overflow: 9000 tokens + 512 output reserve")
        )

        assert verdict["error_class"] == "contextoverflowerror"
        assert verdict["recoverability"] == RECOVERABILITY_TRANSIENT
        assert verdict["retry_after"] and verdict["retry_after"] > 0

    def test_context_overflow_is_transient_while_its_base_class_stays_permanent(self) -> None:
        """``ContextOverflowError`` subclasses ``ValueError`` — and is not
        classified by its base: class names are matched exactly, so the
        permanent ``ValueError`` verdict is untouched by the new entry."""
        assert issubclass(ContextOverflowError, ValueError)

        assert classify_error(ValueError("bad schema"))["recoverability"] == (
            RECOVERABILITY_PERMANENT
        )
        assert classify_error("ContextOverflowError")["recoverability"] == (
            RECOVERABILITY_TRANSIENT
        )


# ───── parking and reading ───────────────────────────────────────────────


class TestParkAndInspect:
    def test_a_parked_failure_carries_its_classification(
        self, service: DeadLetterService
    ) -> None:
        entry = _park(service, error="TimeoutError")

        assert entry["state"] == "open"
        assert entry["recoverability"] == RECOVERABILITY_TRANSIENT
        assert entry["classification"]["recoverability"] == RECOVERABILITY_TRANSIENT
        assert entry["retry_after"], "a transient failure says when to try again"

    def test_a_permanent_failure_is_parked_without_a_retry_time(
        self, service: DeadLetterService
    ) -> None:
        entry = _park(service, error="ValueError")

        assert entry["recoverability"] == RECOVERABILITY_PERMANENT
        assert entry["retry_after"] is None

    def test_parking_classifies_the_traceback_and_not_only_the_class_name(
        self, service: DeadLetterService
    ) -> None:
        """Regression: a 429 parked with its traceback is retryable, not unknown.

        ``ProviderHTTPStatusError`` is not a known transient class name, so the
        verdict used to come from ``error_class`` alone — ``unknown``, handed to
        a human — even though the traceback carried the 429 the classifier reads.
        """
        entry = _park(
            service,
            error="ProviderHTTPStatusError",
            sanitized_traceback="OpenAI-compatible API error 429: Too Many Requests",
        )

        assert entry["recoverability"] == RECOVERABILITY_TRANSIENT
        assert entry["retry_after"], "a rate limit must say when to try again"
        assert entry["classification"]["recoverability"] == RECOVERABILITY_TRANSIENT
        assert service.list(recoverability=RECOVERABILITY_TRANSIENT) == [entry]

    def test_a_permanent_class_still_wins_over_a_transient_traceback(
        self, service: DeadLetterService
    ) -> None:
        """Regression: reading the traceback must not promote a schema defect.

        The class is decided first, so a ValueError/TypeError/SchemaError whose
        traceback carries a retryable status stays permanent — a retry repeats it.
        """
        cases = (
            ("ValueError", "invalid schema for tool arguments; upstream answered 503"),
            ("TypeError", "argument 'path' must be str (connection reset by peer)"),
            ("SchemaError", "result schema mismatch: provider returned 502"),
        )
        for index, (error_class, traceback_text) in enumerate(cases):
            entry = _park(
                service,
                error=error_class,
                sanitized_traceback=traceback_text,
                task_id=f"task-{index}",
            )

            assert entry["recoverability"] == RECOVERABILITY_PERMANENT, error_class
            assert entry["retry_after"] is None, error_class
            assert entry["classification"]["recoverability"] == RECOVERABILITY_PERMANENT

    def test_a_context_overflow_is_parked_as_retryable(
        self, service: DeadLetterService
    ) -> None:
        """Regression: an overflow the agent can shrink out of is transient."""
        entry = _park(
            service,
            error="ContextOverflowError",
            sanitized_traceback="context length exceeded",
        )

        assert entry["recoverability"] == RECOVERABILITY_TRANSIENT
        assert entry["retry_after"], "a shrink-and-continue failure is worth retrying"
        assert entry["classification"]["error_class"] == "contextoverflowerror"

    def test_the_caller_can_override_the_classification(
        self, service: DeadLetterService
    ) -> None:
        entry = _park(service, error="TimeoutError", recoverability=RECOVERABILITY_PERMANENT)

        assert entry["recoverability"] == RECOVERABILITY_PERMANENT

    def test_inspect_returns_the_entry_with_its_history(
        self, service: DeadLetterService
    ) -> None:
        stored = _park(service)

        inspected = service.inspect(stored["id"])

        assert inspected["id"] == stored["id"]
        assert inspected["task_id"] == "task-1"
        assert inspected["classification"]["recoverability"] == RECOVERABILITY_TRANSIENT

    def test_inspect_of_a_missing_entry_is_a_clear_error(
        self, service: DeadLetterService
    ) -> None:
        with pytest.raises(DeadLetterNotFound):
            service.inspect("nope")

    def test_listing_filters_by_state_and_recoverability(
        self, service: DeadLetterService
    ) -> None:
        transient = _park(service, error="TimeoutError")
        permanent = _park(service, error="ValueError", task_id="task-2")

        everything = service.list(state=None)
        assert {entry["id"] for entry in everything} == {transient["id"], permanent["id"]}

        only_transient = service.list(state=None, recoverability=RECOVERABILITY_TRANSIENT)
        assert [entry["id"] for entry in only_transient] == [transient["id"]]

        by_run = service.list(state="open", run_id="run-1")
        assert len(by_run) == 2
        assert service.list(state="abandoned") == []

    def test_an_unclassified_entry_is_still_readable(
        self, coordinator: RunCoordinator
    ) -> None:
        """A producer that bypassed ``park`` must not leave an unreadable row."""
        entry_id = coordinator.enqueue_dead_letter(
            {"task_id": "task-raw", "error_class": "TimeoutError"}
        )
        service = DeadLetterService(coordinator)

        inspected = service.inspect(entry_id)

        assert inspected["recoverability"] == RECOVERABILITY_TRANSIENT
        assert inspected["classification"]["retry_after"]
        found = service.list(
            state=None, recoverability=RECOVERABILITY_TRANSIENT
        )
        assert [entry["id"] for entry in found] == [entry_id]

    def test_an_unclassified_entry_reads_its_traceback_as_evidence(
        self, coordinator: RunCoordinator
    ) -> None:
        """A raw producer's 429 traceback counts as evidence too, so the row
        reads as retryable instead of unexplained."""
        entry_id = coordinator.enqueue_dead_letter(
            {
                "task_id": "task-raw",
                "error_class": "ProviderHTTPStatusError",
                "sanitized_traceback": "OpenAI-compatible API error 503: Service Unavailable",
            }
        )
        service = DeadLetterService(coordinator)

        inspected = service.inspect(entry_id)

        assert inspected["recoverability"] == RECOVERABILITY_TRANSIENT
        assert service.list(state=None, recoverability=RECOVERABILITY_TRANSIENT) == [
            inspected
        ]


# ───── the operator cycle ────────────────────────────────────────────────


class TestOperatorCycle:
    async def test_inspect_then_retry_requeue_and_abandon(
        self, coordinator: RunCoordinator
    ) -> None:
        manager = FakeTaskManager()
        service = DeadLetterService(coordinator, task_manager=manager)

        # Unknown classification: no retry_after, so the retry gate is open.
        entry = _park(service, error="RuntimeError")

        inspected = service.inspect(entry["id"])
        assert inspected["state"] == "open"

        retried = await service.retry(entry["id"])
        assert retried.state == "retrying"
        assert manager.calls == ["task-1"]
        assert service.inspect(entry["id"])["state"] == "retrying"

        requeued = await service.requeue(entry["id"])
        assert requeued.state == "requeued"
        assert service.inspect(entry["id"])["note"].count("requeue") >= 1

        abandoned = service.abandon(entry["id"], reason="provider is gone for good")
        assert abandoned.state == "abandoned"
        assert "provider is gone" in service.inspect(entry["id"])["note"]

    async def test_retry_without_a_task_manager_is_an_operational_error(
        self, service: DeadLetterService
    ) -> None:
        entry = _park(service, error="RuntimeError")  # unknown: no retry gate

        with pytest.raises(DeadLetterUnavailable) as excinfo:
            await service.retry(entry["id"])

        assert "task manager" in str(excinfo.value)
        assert excinfo.value.http_status == 503
        # The queue is untouched by the failed attempt.
        assert service.inspect(entry["id"])["state"] == "open"

    async def test_retry_before_its_time_is_refused(
        self, coordinator: RunCoordinator
    ) -> None:
        manager = FakeTaskManager()
        service = DeadLetterService(coordinator, task_manager=manager)
        entry = _park(service, error="TimeoutError")  # retry_after: now + 60s

        with pytest.raises(DeadLetterRejected) as excinfo:
            await service.retry(entry["id"])

        assert "retry_after" in str(excinfo.value)
        assert manager.calls == [], "nothing was re-armed"
        assert service.inspect(entry["id"])["state"] == "open"

    async def test_requeue_overrides_the_retry_delay(
        self, coordinator: RunCoordinator
    ) -> None:
        manager = FakeTaskManager()
        service = DeadLetterService(coordinator, task_manager=manager)
        entry = _park(service, error="TimeoutError")

        requeued = await service.requeue(entry["id"])

        assert requeued.state == "requeued"
        assert manager.calls == ["task-1"]

    async def test_a_refusing_task_manager_surfaces_the_reason(
        self, coordinator: RunCoordinator
    ) -> None:
        manager = FakeTaskManager(result="unregistered")
        service = DeadLetterService(coordinator, task_manager=manager)
        entry = _park(service, error="RuntimeError")

        with pytest.raises(DeadLetterRejected) as excinfo:
            await service.requeue(entry["id"])

        assert "unregistered" in str(excinfo.value)
        assert service.inspect(entry["id"])["state"] == "open"

    async def test_an_entry_without_a_task_cannot_be_rearmed(
        self, coordinator: RunCoordinator
    ) -> None:
        service = DeadLetterService(coordinator, task_manager=FakeTaskManager())
        entry = _park(service, error="RuntimeError", task_id="")

        with pytest.raises(DeadLetterRejected) as excinfo:
            await service.requeue(entry["id"])

        assert "task_id" in str(excinfo.value)

    def test_replan_hands_over_without_rearming(
        self, coordinator: RunCoordinator
    ) -> None:
        service = DeadLetterService(coordinator, task_manager=FakeTaskManager())
        entry = _park(service)

        replanned = service.replan(entry["id"], plan="split the failing step in two")

        assert replanned.state == "replanned"
        assert "split the failing step" in service.inspect(entry["id"])["note"]

    def test_escalate_records_the_decision(
        self, coordinator: RunCoordinator
    ) -> None:
        service = DeadLetterService(coordinator)
        entry = _park(service)

        escalated = service.escalate(entry["id"], reason="three transient failures in a row")

        assert escalated.state == "escalated"
        assert "three transient failures" in service.inspect(entry["id"])["note"]

    def test_every_action_records_its_state_in_the_queue(
        self, coordinator: RunCoordinator
    ) -> None:
        service = DeadLetterService(coordinator)
        states = []
        for action in (service.abandon, service.escalate):
            entry = _park(service, task_id=f"task-{len(states)}")
            states.append(action(entry["id"]).state)
        entry = _park(service, task_id="task-replan")
        states.append(service.replan(entry["id"]).state)

        assert states == ["abandoned", "escalated", "replanned"]

    def test_an_action_on_a_missing_entry_changes_nothing(
        self, coordinator: RunCoordinator
    ) -> None:
        service = DeadLetterService(coordinator)

        with pytest.raises(DeadLetterNotFound):
            service.abandon("missing")

    def test_the_written_states_are_states_the_coordinator_knows(self) -> None:
        from backend.runtime.dead_letter_service import assert_states_are_known

        assert set(assert_states_are_known()) == {
            "retrying",
            "requeued",
            "replanned",
            "abandoned",
            "escalated",
        }


# ───── the HTTP surface ──────────────────────────────────────────────────


@pytest.fixture
def service(coordinator: RunCoordinator) -> DeadLetterService:
    return DeadLetterService(coordinator)


async def _fake_user() -> dict:
    return {"user_id": "dlq-test", "email": "dlq@test.local"}


def _client(service: DeadLetterService | None = None, task_manager: object | None = None):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[auth_module.require_auth] = _fake_user
    if service is not None:
        app.state.dead_letter_service = service
    app.state.task_manager = task_manager
    return TestClient(app)


class TestDeadLetterRoutes:
    def test_the_router_requires_authentication(self) -> None:
        app = FastAPI()
        app.include_router(router, prefix="/api")

        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.get("/api/dead-letters").status_code == 401
            assert client.post("/api/dead-letters/x/abandon").status_code == 401

    def test_listing_returns_the_worklist(self, service: DeadLetterService) -> None:
        stored = _park(service)
        service.abandon(_park(service, task_id="task-closed")["id"], reason="not mine")

        with _client(service) as client:
            response = client.get("/api/dead-letters")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["dead_letters"][0]["id"] == stored["id"]
        assert body["dead_letters"][0]["classification"]["recoverability"]

    def test_listing_rejects_an_unknown_state(self, service: DeadLetterService) -> None:
        with _client(service) as client:
            assert client.get("/api/dead-letters", params={"state": "nonsense"}).status_code == 400
            assert client.get("/api/dead-letters").status_code == 200

    def test_listing_can_show_every_state(self, service: DeadLetterService) -> None:
        _park(service)
        with _client(service) as client:
            every = client.get("/api/dead-letters", params={"state": "all"}).json()
        assert every["count"] == 1

    def test_inspecting_one_entry(self, service: DeadLetterService) -> None:
        stored = _park(service)
        with _client(service) as client:
            found = client.get(f"/api/dead-letters/{stored['id']}")
            missing = client.get("/api/dead-letters/does-not-exist")

        assert found.status_code == 200
        assert found.json()["dead_letter"]["id"] == stored["id"]
        assert missing.status_code == 404

    async def test_retry_reaches_the_task_manager(
        self, coordinator: RunCoordinator
    ) -> None:
        manager = FakeTaskManager()
        service = DeadLetterService(coordinator, task_manager=manager)
        stored = _park(service, error="RuntimeError")

        with _client(service, manager) as client:
            response = client.post(f"/api/dead-letters/{stored['id']}/retry")

        assert response.status_code == 200
        assert response.json()["state"] == "retrying"
        assert manager.calls == ["task-1"]

    async def test_requeue_reaches_the_task_manager(
        self, coordinator: RunCoordinator
    ) -> None:
        manager = FakeTaskManager()
        service = DeadLetterService(coordinator, task_manager=manager)
        stored = _park(service)

        with _client(service, manager) as client:
            response = client.post(f"/api/dead-letters/{stored['id']}/requeue")

        assert response.status_code == 200
        assert response.json()["state"] == "requeued"

    def test_retry_without_a_task_manager_is_a_clear_503(
        self, coordinator: RunCoordinator
    ) -> None:
        service = DeadLetterService(coordinator)
        stored = _park(service, error="RuntimeError")

        with _client(service, None) as client:
            response = client.post(f"/api/dead-letters/{stored['id']}/retry")

        assert response.status_code == 503
        assert "task manager" in response.json()["detail"]

    def test_abandon_and_escalate_record_their_reason(
        self, service: DeadLetterService
    ) -> None:
        stored = _park(service)

        with _client(service) as client:
            escalated = client.post(
                f"/api/dead-letters/{stored['id']}/escalate",
                json={"reason": "second provider failure"},
            )
            abandoned = client.post(f"/api/dead-letters/{stored['id']}/abandon")

        assert escalated.status_code == 200
        assert escalated.json()["state"] == "escalated"
        assert "second provider failure" in service.inspect(stored["id"])["note"]
        assert abandoned.status_code == 200
        assert abandoned.json()["state"] == "abandoned"

    def test_a_refused_retry_is_not_a_server_error(self, coordinator: RunCoordinator) -> None:
        manager = FakeTaskManager()
        service = DeadLetterService(coordinator, task_manager=manager)
        stored = _park(service, error="TimeoutError")  # retry_after in the future

        with _client(service, manager) as client:
            response = client.post(f"/api/dead-letters/{stored['id']}/retry")

        assert response.status_code == 409
        assert "retry_after" in response.json()["detail"]

    def test_replan_hands_the_failure_over(self, service: DeadLetterService) -> None:
        stored = _park(service)

        with _client(service) as client:
            response = client.post(
                f"/api/dead-letters/{stored['id']}/replan",
                json={"plan": "use a different provider"},
            )

        assert response.status_code == 200
        assert response.json()["state"] == "replanned"
        assert "different provider" in service.inspect(stored["id"])["note"]


def test_a_service_error_carries_the_status_a_route_should_use() -> None:
    assert DeadLetterUnavailable().http_status == 503
    assert DeadLetterNotFound("gone").http_status == 404
    assert DeadLetterRejected("too soon").http_status == 409
    assert issubclass(DeadLetterUnavailable, DeadLetterError)


def test_a_stale_retry_after_is_parsed_from_storage() -> None:
    """A row read back off disk still says when it may be retried."""
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    assert DeadLetterService._retry_due({"retry_after": past}) is True
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    assert DeadLetterService._retry_due({"retry_after": future}) is False
    assert DeadLetterService._retry_due({"retry_after": ""}) is True
    assert DeadLetterService._retry_due({"retry_after": "not-a-date"}) is True
