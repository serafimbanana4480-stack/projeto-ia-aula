"""Resilience tests for planner timeouts and untrusted structured output."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

import backend.orchestrator.plan_creator as plan_creator_module
from backend.orchestrator.events import EventType, OrchestratorEvent
from backend.orchestrator.plan_creator import PlanCreator


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[OrchestratorEvent] = []

    async def publish(self, event: OrchestratorEvent) -> None:
        self.events.append(event)


class HangingPlanner:
    async def chat_stream(self, **_kwargs: Any):
        await asyncio.Event().wait()
        yield "[]"  # pragma: no cover - makes this an async generator


def _creator() -> PlanCreator:
    return PlanCreator(llm_client=object(), event_bus=RecordingEventBus())


@pytest.mark.asyncio
async def test_planning_consultation_receives_project_path_and_windows_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_recall_context(**_kwargs: Any) -> dict[str, Any]:
        return {"memories": []}

    async def fake_consult_agent(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"response": "Use focused tests."}

    monkeypatch.setattr("backend.tools.memory_tools.recall_context", fake_recall_context)
    monkeypatch.setattr("backend.tools.agent_comm.consult_agent", fake_consult_agent)

    context = await PlanCreator._gather_planning_context(
        "Test a regression",
        "s1",
        "",
        r"C:\workspace\nexus-ide",
    )

    assert captured["project_path"] == r"C:\workspace\nexus-ide"
    assert captured["autonomous"] is True
    assert "Windows with PowerShell" in captured["question"]
    assert "DEBUGGER consultation" in context


def test_parse_plan_normalizes_invalid_steps_and_dependencies() -> None:
    creator = _creator()
    content = json.dumps(
        [
            None,
            {
                "name": ["not a name"],
                "description": 42,
                "agent": "unknown-agent",
                "depends_on": [],
                "sandboxed": "yes",
            },
            {"name": "Second", "description": "ok", "depends_on": [0, 0, True]},
        ]
    )

    plan = creator._parse_plan(content, "Ship it", "session_1")

    assert [step.name for step in plan.steps] == [
        "Step 1",
        "Second",
        "Verification - run relevant checks",
    ]
    assert plan.steps[0].agent == "CODER"
    assert plan.steps[0].description == ""
    assert plan.steps[0].sandboxed is False
    assert plan.steps[1].depends_on == [plan.steps[0].task_id]
    assert plan.steps[2].agent == "DEBUGGER"
    assert set(plan.steps[2].depends_on) == {plan.steps[0].task_id, plan.steps[1].task_id}
    assert plan.dependency_graph.validate() == (True, "")


def test_planning_prompt_uses_bounded_economical_step_count() -> None:
    prompt = _creator()._build_planning_prompt("Audit Nexus", "")

    assert "6-12 necessary steps" in prompt
    assert "10-25 steps" not in prompt


def test_parse_plan_repairs_cyclic_dependencies_into_an_executable_order() -> None:
    creator = _creator()
    content = json.dumps(
        [
            {"name": "Design", "depends_on": [1]},
            {"name": "Implement", "depends_on": [0]},
            {"name": "Test", "depends_on": [1]},
        ]
    )

    plan = creator._parse_plan(content, "Ship it", "session_1")

    assert plan.dependency_graph.validate() == (True, "")
    assert plan.steps[0].depends_on == []
    assert plan.steps[1].depends_on == [plan.steps[0].task_id]
    assert plan.steps[2].depends_on == [plan.steps[1].task_id]


@pytest.mark.asyncio
async def test_planner_timeout_emits_warning_and_returns_a_safe_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = RecordingEventBus()
    creator = PlanCreator(llm_client=HangingPlanner(), event_bus=bus)
    creator.PLAN_STREAM_TIMEOUT_SECONDS = 0.01
    monkeypatch.setattr(
        plan_creator_module,
        "get_model_config",
        lambda _name: {"id": "test-planner", "temperature": 0.1},
    )
    monkeypatch.setattr(plan_creator_module, "load_prompt", lambda _name: "system prompt")

    plan = await creator.create("Ship it", "session_timeout")

    # The fallback degrades into analyse -> implement -> verify rather than a
    # single opaque "Execute Objective" CODER task.  The old single-step
    # fallback let a rich objective silently collapse into one generic step
    # that reported "completed" without doing the work.
    assert len(plan.steps) == 3
    assert [s.agent for s in plan.steps] == ["ANALYZER", "CODER", "DEBUGGER"]
    assert [s.name for s in plan.steps] == [
        "Analyse: Ship it",
        "Implement: Ship it",
        "Verify: Ship it",
    ]
    # Every step must carry the full objective, not just the title.
    assert all("Ship it" in s.description for s in plan.steps)
    # And the chain must be ordered, not three parallel no-ops.
    assert plan.steps[0].depends_on == []
    assert plan.steps[1].depends_on == [plan.steps[0].task_id]
    assert plan.steps[2].depends_on == [plan.steps[1].task_id]
    assert plan.dependency_graph.validate() == (True, "")
    assert plan.session_id == "session_timeout"
    assert any(event.event_type == EventType.WARNING for event in bus.events)
    assert any(event.event_type == EventType.PLAN_CREATED for event in bus.events)


class FlakyPlanner:
    """Fails with the given errors, then serves ``payload`` on the next model."""

    def __init__(self, errors: list[Exception], payload: str = "") -> None:
        self._errors = list(errors)
        self._payload = payload
        self.models_tried: list[str] = []

    async def chat_stream(self, *, model: str, **_kwargs: Any):
        self.models_tried.append(model)
        if self._errors:
            raise self._errors.pop(0)
        for chunk in (self._payload,):
            yield chunk


RATE_LIMIT_429 = Exception(
    "OpenAI API error 429: Rate limit exceeded: free-models-per-min. "
    '{"headers":{"X-RateLimit-Limit":"20","X-RateLimit-Remaining":"0"}}'
)

_GOOD_PLAN = json.dumps(
    [
        {"name": "Phase 1: Setup - Map modules", "description": "d", "agent": "ANALYZER"},
        {"name": "Phase 2: Build - Implement", "description": "d", "agent": "CODER",
         "depends_on": [0]},
    ]
)


def _patch_planner_config(monkeypatch: pytest.MonkeyPatch) -> None:
    configs = {
        "coder": {"id": "kimi-k2.7-code", "fallback_id": "deepseek-v4-flash", "temperature": 0.5},
        "reasoning": {"id": "glm-5.2", "fallback_id": "deepseek-v4-pro"},
        "fast": {"id": "deepseek-v4-flash", "fallback_id": "minimax-m3"},
    }
    monkeypatch.setattr(plan_creator_module, "get_model_config", lambda name: configs[name])
    monkeypatch.setattr(plan_creator_module, "load_prompt", lambda _name: "system prompt")


class TestPlannerModelCascade:
    """A single 429 must not collapse a 25-step plan into the fallback.

    Reference failure, session 27437d6cc61e4753::

        08:18:55  Planner failed for session ...: OpenAI API error 429
        08:18:55  No JSON array found in plan content, creating single-step plan
        08:18:55  [CODER] TASK: Execute Objective

    Every *agent* already had a fallback cascade in ``AgentBase.stream_llm``.
    Planning did not, so the one component whose failure degrades the entire
    run was also the only one with no redundancy.
    """

    def test_chain_is_ordered_and_deduplicated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_planner_config(monkeypatch)
        chain = PlanCreator._planner_model_chain(
            {"id": "kimi-k2.7-code", "fallback_id": "deepseek-v4-flash"}
        )
        assert chain[0] == "kimi-k2.7-code"
        assert chain[1] == "deepseek-v4-flash"
        assert len(chain) == len(set(chain))

    @pytest.mark.asyncio
    async def test_rate_limited_primary_recovers_on_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_planner_config(monkeypatch)
        client = FlakyPlanner([RATE_LIMIT_429], _GOOD_PLAN)
        creator = PlanCreator(llm_client=client, event_bus=RecordingEventBus())
        creator.PLAN_RETRY_BACKOFF_SECONDS = (0.0,)

        plan = await creator.create("Audit everything", "s1")

        assert client.models_tried == ["kimi-k2.7-code", "deepseek-v4-flash"]
        # A real plan, not the three-step degraded fallback.
        assert [s.name for s in plan.steps][:2] == [
            "Phase 1: Setup - Map modules",
            "Phase 2: Build - Implement",
        ]
        assert not any(s.name.startswith("Implement: ") for s in plan.steps)

    @pytest.mark.asyncio
    async def test_empty_body_is_treated_as_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HTTP 200 with nothing in it is a dud, not a plan."""
        _patch_planner_config(monkeypatch)
        client = FlakyPlanner([], "")
        creator = PlanCreator(llm_client=client, event_bus=RecordingEventBus())
        creator.PLAN_RETRY_BACKOFF_SECONDS = (0.0,)

        await creator.create("Audit everything", "s1")

        assert len(client.models_tried) > 1, "an empty body must hand over to the next model"

    @pytest.mark.asyncio
    async def test_non_retryable_error_does_not_walk_the_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 400 will not improve on the next model; failing fast is correct."""
        _patch_planner_config(monkeypatch)
        client = FlakyPlanner([Exception("OpenAI API error 400: malformed request")], _GOOD_PLAN)
        creator = PlanCreator(llm_client=client, event_bus=RecordingEventBus())
        creator.PLAN_RETRY_BACKOFF_SECONDS = (0.0,)

        plan = await creator.create("Audit everything", "s1")

        assert client.models_tried == ["kimi-k2.7-code"]
        assert [s.agent for s in plan.steps] == ["ANALYZER", "CODER", "DEBUGGER"]

    @pytest.mark.asyncio
    async def test_all_models_rate_limited_falls_back_and_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_planner_config(monkeypatch)
        bus = RecordingEventBus()
        client = FlakyPlanner([RATE_LIMIT_429] * 6)
        creator = PlanCreator(llm_client=client, event_bus=bus)
        creator.PLAN_RETRY_BACKOFF_SECONDS = (0.0,)

        plan = await creator.create("Audit everything", "s1")

        assert len(client.models_tried) >= 3
        assert [s.agent for s in plan.steps] == ["ANALYZER", "CODER", "DEBUGGER"]
        warnings = [e for e in bus.events if e.event_type == EventType.WARNING]
        # The user must be told the plan is degraded *and* why — a silent
        # collapse into the fallback is what made the 158-second run look
        # successful.
        assert any("every available model" in e.content for e in warnings)
        assert any("kimi-k2.7-code" in e.content for e in warnings)

    @pytest.mark.asyncio
    async def test_plan_created_event_is_attributed_to_the_planner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The UI showed ARCHITECT for work the ARCHITECT never did."""
        _patch_planner_config(monkeypatch)
        bus = RecordingEventBus()
        creator = PlanCreator(llm_client=FlakyPlanner([], _GOOD_PLAN), event_bus=bus)

        await creator.create("Audit everything", "s1")

        created = [e for e in bus.events if e.event_type == EventType.PLAN_CREATED]
        assert created and created[0].source == "PLANNER"
        assert not any(e.event_type == EventType.TOKEN for e in bus.events)
