"""Evidence: a planner formatting failure aborts the whole run.

The requirement is "PLANNER FAILURE NÃO PODE SIGNIFICAR SYSTEM FAILURE":
when the planner cannot produce a parseable structured plan, the primary
agent must still be able to execute the request with its tools.

Today ``execute_autonomous`` returns ``PLANNING_BLOCKED`` and no agent ever
runs, so the user's request dies on a JSON formatting difference.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from backend.orchestrator.engine import OrchestrationEngine, OrchestrationState
from backend.orchestrator.events import EventBus


class _ProseOnlyClient:
    """An LLM that answers helpfully — but in prose, not in the plan schema."""

    def __init__(self) -> None:
        self.calls = 0

    async def chat_stream(self, **kwargs: Any) -> AsyncIterator[str]:
        self.calls += 1
        for chunk in (
            "Sure! Here is how I would approach this:\n",
            "1. Read the scheduler\n2. Fix the ordering\n3. Run the tests\n",
        ):
            yield chunk

    async def chat(self, **kwargs: Any) -> str:
        return "prose"


class _RecordingAgent:
    def __init__(self, name: str, ran: list[str]) -> None:
        self.name = name
        self._ran = ran

    async def run(self, req: Any):  # noqa: ANN001, ANN201
        self._ran.append(self.name)
        yield "did the work"


@pytest.mark.asyncio
async def test_planner_failure_does_not_abort_the_run(tmp_path) -> None:
    ran: list[str] = []
    registry = {name: _RecordingAgent(name, ran) for name in ("CODER", "ANALYZER", "DEBUGGER")}
    engine = OrchestrationEngine(
        llm_client=_ProseOnlyClient(),
        registry=registry,  # type: ignore[arg-type]
        event_bus=EventBus(),
    )

    result = await engine.execute_autonomous(
        objective="corrige o erro de ordenação no scheduler",
        session_id="sess-planner-evidence",
        project_path=str(tmp_path),
    )

    assert result.state is not OrchestrationState.PLANNING_BLOCKED, (
        "an unparseable planner response terminated the entire run; the "
        "primary agent never got a chance to execute the request"
    )
    assert ran, (
        "no agent executed at all after the planner failed to emit valid "
        "JSON — planner failure is currently system failure"
    )
