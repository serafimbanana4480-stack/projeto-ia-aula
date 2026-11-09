"""Request-scoped model selection and honest child outcomes."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from backend.agents.event_protocol import encode_event
from backend.orchestrator.routes.chat_primary import _make_subagent_runner
from backend.runtime.events import RuntimeEventType
from backend.runtime.primary import PrimaryLoop
from backend.runtime.spawn_policy import SubagentProposal


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_subagent_inherits_selected_model_on_its_own_request(monkeypatch: Any) -> None:
    from backend.orchestrator import registry

    contexts: list[dict[str, Any]] = []

    class Agent:
        async def run(self, request: Any) -> AsyncIterator[str]:
            contexts.append(request.context)
            request.context["_agent_run_success"] = True
            yield "Resultado confirmado"

    monkeypatch.setattr(registry, "resolve", lambda *_: Agent())
    runner = _make_subagent_runner(
        registry=object(), llm_client=object(), session_id="s", project_path="fixture",
        model_override="provider/model-selected", allowed_tools=("read_file",),
    )
    result = await runner(SubagentProposal(name="CODER:read", objective="Ler", definition_of_done="reportar"))
    assert result == "Resultado confirmado"
    assert contexts[0]["_model_override"] == "provider/model-selected"
    assert contexts[0]["_allowed_tools"] == ("read_file",)


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
@pytest.mark.parametrize("verdict, chunks", [  # type: ignore[untyped-decorator]
    (False, ["Resposta parcial", encode_event("error", "provider failed")]),
    (True, [encode_event("thinking", "a analisar")]),
])
async def test_subagent_failure_or_empty_output_is_not_completed(
    monkeypatch: Any, verdict: bool, chunks: list[str],
) -> None:
    from backend.orchestrator import registry

    class Agent:
        async def run(self, request: Any) -> AsyncIterator[str]:
            request.context["_agent_run_success"] = verdict
            for chunk in chunks:
                yield chunk

    monkeypatch.setattr(registry, "resolve", lambda *_: Agent())
    runner = _make_subagent_runner(registry=object(), llm_client=object(), session_id="s", project_path="fixture")
    with pytest.raises(RuntimeError, match="incompleta ou falhada|sem devolver resultado"):
        await runner(SubagentProposal(name="CODER:read", objective="Ler", definition_of_done="reportar"))


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_reused_task_name_is_not_dispatched_or_misattributed() -> None:
    dispatched: list[str] = []

    async def run_subagent(proposal: SubagentProposal) -> str:
        dispatched.append(proposal.objective)
        return "resultado"

    async def unused_stream(_turn: Any) -> AsyncIterator[Any]:
        if False:
            yield None

    loop = PrimaryLoop(run_id="duplicate-task-names", query="test", stream=unused_stream, run_subagent=run_subagent)
    first = SubagentProposal(name="CODER:read", objective="Ler o ficheiro A", definition_of_done="reportar")
    same_name = SubagentProposal(name="CODER:read", objective="Ler o ficheiro B", definition_of_done="reportar")
    events = [event async for event in loop._delegate([first, same_name], loop.events.emit)]

    assert dispatched == ["Ler o ficheiro A"]
    started = [event for event in events if event.type is RuntimeEventType.SUBAGENT_STARTED]
    assert len(started) == 1
    assert started[0].payload["objective"] == "Ler o ficheiro A"
    assert any(
        event.type is RuntimeEventType.TOOL_COMPLETED
        and event.payload.get("result", {}).get("status") == "denied"
        and "task name" in event.payload.get("result", {}).get("reason", "")
        for event in events
    )
