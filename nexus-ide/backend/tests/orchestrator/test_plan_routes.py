"""Safety and transcript tests for the plan creation API."""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode, TaskStatus
from backend.orchestrator.engine import OrchestrationEngine, OrchestrationState
from backend.orchestrator.routes import plan as plan_routes


def test_plan_creation_defaults_to_explicit_approval() -> None:
    request = plan_routes.PlanCreateRequest(objective="Review this change")

    assert request.auto_approve is False
    assert request.persist_conversation is False


def test_default_plan_session_is_created_under_the_authenticated_user(
    monkeypatch: Any,
) -> None:
    owners: dict[str, str] = {}
    monkeypatch.setattr(
        plan_routes,
        "get_session_for_user",
        lambda session_id, user_id: (
            {"id": session_id, "user_id": user_id}
            if owners.get(session_id) == user_id
            else None
        ),
    )

    def create_owned_session(*, session_id: str, user_id: str, **_kwargs: Any) -> None:
        owners[session_id] = user_id

    monkeypatch.setattr(plan_routes, "create_session", create_owned_session)
    resolved = plan_routes._resolve_owned_session("default", "user-1", create_default=True)

    expected_suffix = hashlib.sha256(b"user-1").hexdigest()[:24]
    assert resolved == f"default-{expected_suffix}"
    assert owners[resolved] == "user-1"


def test_plan_session_resolution_rejects_foreign_session(monkeypatch: Any) -> None:
    monkeypatch.setattr(plan_routes, "get_session_for_user", lambda _session_id, _user_id: None)

    with pytest.raises(HTTPException) as exc_info:
        plan_routes._resolve_owned_session("private-session", "user-attacker")

    assert exc_info.value.status_code == 404


def test_engine_lists_the_plans_in_its_runtime_store() -> None:
    plan = ExecutionPlan.from_steps(title="Review", description="Review changes", steps=[])
    engine = OrchestrationEngine.__new__(OrchestrationEngine)
    engine._plans = {plan.plan_id: plan}

    assert engine.list_plans() == [plan]


def test_chat_plan_persists_prompt_and_plan_without_auto_approval(monkeypatch: Any) -> None:
    step = SimpleNamespace(
        name="Inspect the diff",
        agent="REVIEWER",
        description="Check the changed files",
        depends_on=[],
    )
    execution_plan = SimpleNamespace(
        plan_id="plan-1",
        title="Review change",
        steps=[step],
    )

    class FakePlanning:
        status = "ready"
        plan = execution_plan
        deterministic_proposal = None
        error = None

        @staticmethod
        def to_dict() -> dict[str, Any]:
            return {
                "status": "ready",
                "source": "planner",
                "error": None,
                "plan": {"plan_id": "plan-1", "steps": []},
                "deterministic_proposal": None,
            }

    class FakeEngine:
        create_plan_kwargs: dict[str, Any] = {}

        @staticmethod
        def get_plan_by_session(_session_id: str) -> None:
            return None

        @staticmethod
        def get_state(_session_id: str) -> OrchestrationState:
            return OrchestrationState.IDLE

        async def create_plan(self, **kwargs: Any) -> FakePlanning:
            self.create_plan_kwargs = kwargs
            return FakePlanning()

        @staticmethod
        def request_approval(_plan_id: str) -> Any:
            return SimpleNamespace(to_dict=lambda: {"plan_id": "plan-1"})

    engine = FakeEngine()
    stored_messages: list[tuple[Any, ...]] = []
    monkeypatch.setattr(plan_routes, "_get_engine", lambda _request: engine)
    monkeypatch.setattr(
        plan_routes,
        "get_session_for_user",
        lambda _session_id, _user_id: {"id": "session-1", "user_id": "user-1"},
    )
    monkeypatch.setattr(
        plan_routes,
        "add_message",
        lambda *args, **_kwargs: stored_messages.append(args),
    )

    result = asyncio.run(
        plan_routes.create_plan(
            plan_routes.PlanCreateRequest(
                objective="Review this change",
                session_id="session-1",
                persist_conversation=True,
            ),
            SimpleNamespace(),
            {"user_id": "user-1"},
        )
    )

    assert engine.create_plan_kwargs["auto_approve"] is False
    assert result["approval"] == {"plan_id": "plan-1"}
    assert stored_messages[0] == ("session-1", "user", "Review this change")
    assert stored_messages[1][0:2] == ("session-1", "assistant")
    assert "Inspect the diff" in stored_messages[1][2]


def test_status_for_an_older_plan_uses_its_own_step_state(monkeypatch: Any) -> None:
    old_plan = ExecutionPlan.from_steps(
        title="Old plan",
        description="Already completed",
        steps=[TaskNode(name="Finished step", status=TaskStatus.COMPLETED)],
        session_id="session-1",
    )
    old_plan.plan_id = "old-plan"
    current_plan = ExecutionPlan.from_steps(
        title="Current plan",
        description="Waiting for approval",
        steps=[TaskNode(name="Current step")],
        session_id="session-1",
    )
    current_plan.plan_id = "current-plan"

    class FakeEngine:
        def get_plan(self, plan_id: str) -> ExecutionPlan | None:
            return old_plan if plan_id == old_plan.plan_id else None

        @staticmethod
        def get_plan_by_session(_session_id: str) -> ExecutionPlan:
            return current_plan

        @staticmethod
        def get_state(_session_id: str) -> OrchestrationState:
            return OrchestrationState.AWAITING_APPROVAL

        @staticmethod
        def request_approval(_plan_id: str) -> None:
            return None

    monkeypatch.setattr(plan_routes, "_get_engine", lambda _request: FakeEngine())
    monkeypatch.setattr(
        plan_routes,
        "get_session_for_user",
        lambda _session_id, _user_id: {"id": "session-1", "user_id": "user-1"},
    )

    result = asyncio.run(
        plan_routes.get_plan_status("old-plan", SimpleNamespace(), {"user_id": "user-1"})
    )

    assert result["status"] == "completed"
    assert result["steps"][0]["status"] == "completed"


def test_status_for_unknown_plan_raises_http_404(monkeypatch: Any) -> None:
    class FakeEngine:
        @staticmethod
        def get_plan(_plan_id: str) -> None:
            return None

    monkeypatch.setattr(plan_routes, "_get_engine", lambda _request: FakeEngine())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            plan_routes.get_plan_status("missing", SimpleNamespace(), {"user_id": "user-1"})
        )

    assert exc_info.value.status_code == 404
    assert "não foi encontrado" in exc_info.value.detail


def test_execute_unknown_plan_does_not_fall_back_to_another_session_plan(
    monkeypatch: Any,
) -> None:
    fallback_plan = ExecutionPlan.from_steps(
        title="Different plan",
        description="Must not be executed for the requested ID",
        steps=[],
        session_id="session-1",
    )

    class FakeEngine:
        fallback_lookups = 0

        @staticmethod
        def get_plan(_plan_id: str) -> None:
            return None

        def get_plan_by_session(self, _session_id: str) -> ExecutionPlan:
            self.fallback_lookups += 1
            return fallback_plan

    engine = FakeEngine()
    monkeypatch.setattr(plan_routes, "_get_engine", lambda _request: engine)
    monkeypatch.setattr(
        plan_routes,
        "get_session_for_user",
        lambda _session_id, _user_id: {"id": "session-1", "user_id": "user-1"},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            plan_routes.execute_plan(
                plan_routes.PlanExecuteRequest(plan_id="missing", session_id="session-1"),
                SimpleNamespace(),
                {"user_id": "user-1"},
            )
        )

    assert exc_info.value.status_code == 404
    assert "não foi encontrado" in exc_info.value.detail
    assert engine.fallback_lookups == 0


def test_execute_unapproved_plan_raises_http_409(monkeypatch: Any) -> None:
    plan = ExecutionPlan.from_steps(
        title="Needs approval",
        description="Must not run without approval",
        steps=[],
        session_id="session-1",
    )
    plan.plan_id = "plan-1"

    class FakeEngine:
        @staticmethod
        def get_plan(_plan_id: str) -> ExecutionPlan:
            return plan

        @staticmethod
        async def execute_plan(**_kwargs: Any) -> None:
            raise AssertionError("unapproved plan must not execute")

    monkeypatch.setattr(plan_routes, "_get_engine", lambda _request: FakeEngine())
    monkeypatch.setattr(
        plan_routes,
        "get_session_for_user",
        lambda _session_id, _user_id: {"id": "session-1", "user_id": "user-1"},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            plan_routes.execute_plan(
                plan_routes.PlanExecuteRequest(plan_id="plan-1", session_id="session-1"),
                SimpleNamespace(),
                {"user_id": "user-1"},
            )
        )

    assert exc_info.value.status_code == 409
    assert "aprovação explícita" in exc_info.value.detail


def test_continue_without_blocked_proposal_raises_http_409(monkeypatch: Any) -> None:
    class FakeEngine:
        @staticmethod
        async def continue_planning(_session_id: str) -> None:
            return None

    monkeypatch.setattr(plan_routes, "_get_engine", lambda _request: FakeEngine())
    monkeypatch.setattr(
        plan_routes,
        "get_session_for_user",
        lambda _session_id, _user_id: {"id": "session-1", "user_id": "user-1"},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            plan_routes.continue_plan(
                plan_routes.PlanContinueRequest(session_id="session-1"),
                SimpleNamespace(),
                {"user_id": "user-1"},
            )
        )

    assert exc_info.value.status_code == 409
    assert "proposta segura" in exc_info.value.detail


def test_legacy_approval_in_the_wrong_state_raises_http_409(monkeypatch: Any) -> None:
    plan = ExecutionPlan.from_steps(
        title="Completed plan",
        description="No longer awaiting approval",
        steps=[],
        session_id="session-1",
    )
    plan.plan_id = "plan-1"

    class FakeEngine:
        approve_called = False

        @staticmethod
        def get_plan(_plan_id: str) -> ExecutionPlan:
            return plan

        @staticmethod
        def get_state(_session_id: str) -> OrchestrationState:
            return OrchestrationState.COMPLETED

        @staticmethod
        def get_plan_by_session(_session_id: str) -> ExecutionPlan:
            return plan

        @staticmethod
        def request_approval(_plan_id: str) -> object:
            return object()

        def approve_plan(self, _plan_id: str, _user_id: str) -> None:
            self.approve_called = True
            return None

    engine = FakeEngine()
    monkeypatch.setattr(plan_routes, "_get_engine", lambda _request: engine)
    monkeypatch.setattr(
        plan_routes,
        "get_session_for_user",
        lambda _session_id, _user_id: {"id": "session-1", "user_id": "user-1"},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            plan_routes.approve_plan_legacy(
                plan_routes.PlanApproveRequest(plan_id="plan-1", session_id="session-1"),
                SimpleNamespace(),
                {"user_id": "user-1"},
            )
        )

    assert exc_info.value.status_code == 409
    assert "aprovar" in exc_info.value.detail
    assert engine.approve_called is False


def test_plan_lookup_hides_plans_owned_by_another_user(monkeypatch: Any) -> None:
    plan = ExecutionPlan.from_steps(
        title="Private plan",
        description="Belongs to another user",
        steps=[],
        session_id="session-private",
    )

    class FakeEngine:
        @staticmethod
        def get_plan(_plan_id: str) -> ExecutionPlan:
            return plan

    monkeypatch.setattr(plan_routes, "_get_engine", lambda _request: FakeEngine())
    monkeypatch.setattr(plan_routes, "get_session_for_user", lambda _session_id, _user_id: None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            plan_routes.get_plan_by_id(
                plan.plan_id,
                SimpleNamespace(),
                {"user_id": "user-attacker"},
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Plano não encontrado"


def test_approval_rejects_a_plan_that_is_not_the_session_current_plan(
    monkeypatch: Any,
) -> None:
    plan = ExecutionPlan.from_steps(
        title="Stale plan",
        description="Must not be approved",
        steps=[],
        session_id="session-1",
    )
    current_plan = ExecutionPlan.from_steps(
        title="Current plan",
        description="The current session plan",
        steps=[],
        session_id="session-1",
    )

    class FakeEngine:
        approve_called = False

        @staticmethod
        def get_plan(_plan_id: str) -> ExecutionPlan:
            return plan

        @staticmethod
        def get_plan_by_session(_session_id: str) -> ExecutionPlan:
            return current_plan

        @staticmethod
        def request_approval(_plan_id: str) -> object:
            return object()

        @staticmethod
        def get_state(_session_id: str) -> OrchestrationState:
            return OrchestrationState.AWAITING_APPROVAL

        async def approve_plan(self, _plan_id: str, _user_id: str) -> None:
            self.approve_called = True
            return None

    engine = FakeEngine()
    monkeypatch.setattr(plan_routes, "_get_engine", lambda _request: engine)
    monkeypatch.setattr(
        plan_routes,
        "get_session_for_user",
        lambda _session_id, _user_id: {"id": "session-1", "user_id": "user-1"},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            plan_routes.approve_plan_by_id(
                plan.plan_id,
                SimpleNamespace(),
                {"user_id": "user-1"},
            )
        )

    assert exc_info.value.status_code == 409
    assert engine.approve_called is False
