"""Child activity is ordered, attributed and replayable, with bounded redaction."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from backend.agents.event_protocol import encode_event
from backend.orchestrator.routes.chat_primary import (
    _make_subagent_runner,
    runtime_event_to_stream_events,
)
from backend.runtime.events import RunEventStream, RuntimeEventType
from backend.runtime.primary import PrimaryLoop
from backend.runtime.spawn_policy import SubagentProposal


@pytest.mark.asyncio
async def test_concurrent_child_tool_events_replay_with_their_own_task(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    from backend.orchestrator import registry

    both_started = asyncio.Event()
    started: list[str] = []

    class Agent:
        def __init__(self, name: str) -> None:
            self.name = name

        async def run(self, request: Any) -> AsyncIterator[str]:
            # Deliberately split a control frame just as a real stream can.
            args = {"path": f"{self.name}.py", "api_key": "a-private-key"}
            frame = encode_event("tool_call", "read_file", json.dumps(args))
            yield frame[:17]
            yield frame[17:]
            started.append(self.name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 3)
            if self.name == "CODER":
                await asyncio.sleep(0.02)
            yield encode_event("tool_result", "read_file", json.dumps({"content": self.name}))
            yield encode_event("thinking", "PRIVATE INTERNAL THOUGHT")
            yield "<think>PRIVATE "
            yield "THOUGHT IN TAGS</think>"
            request.context["_agent_run_success"] = True
            yield f"Resultado de {self.name}"

    monkeypatch.setattr(registry, "resolve", lambda _registry, name: Agent(name))
    runner = _make_subagent_runner(
        registry=object(), llm_client=object(), session_id="test", project_path="fixture",
    )
    journal = tmp_path / "run.jsonl"
    stream = RunEventStream("child-observation", journal_path=journal)
    stream.start_journal()

    async def unused(_turn: Any) -> AsyncIterator[Any]:
        if False:
            yield None

    loop = PrimaryLoop(run_id=stream.run_id, query="test", stream=unused,
                       run_subagent_observed=runner, events=stream)
    proposals = [
        SubagentProposal(name="CODER:inspect", objective="Ler A", definition_of_done="reportar"),
        SubagentProposal(name="DEBUGGER:inspect", objective="Ler B", definition_of_done="reportar"),
    ]
    events = [event async for event in loop._delegate(proposals, stream.emit)]
    await stream.aclose()

    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    calls = [event for event in events if event.type is RuntimeEventType.TOOL_STARTED]
    results = [event for event in events if event.type is RuntimeEventType.TOOL_COMPLETED
               and event.payload.get("tool") == "read_file"]
    assert len(calls) == len(results) == 2
    assert results[0].agent_id == "DEBUGGER"  # finishes in the opposite order
    for call in calls:
        result = next(item for item in results if item.payload["call_id"] == call.payload["call_id"])
        assert (result.agent_id, result.task_id) == (call.agent_id, call.task_id)
        assert result.payload["result"]["content"] == call.agent_id
        assert call.payload["args"]["api_key"] == "***REDACTED***"
        frame = runtime_event_to_stream_events(call)[0]
        assert frame.task_id == call.task_id and frame.data["call_id"] == call.payload["call_id"]

    saved = journal.read_text(encoding="utf-8")
    assert "a-private-key" not in saved
    assert "PRIVATE INTERNAL THOUGHT" not in saved
    assert "PRIVATE THOUGHT IN TAGS" not in saved
    replayed = RunEventStream.load_journal(journal)
    assert [event.to_sse() for event in replayed] == [event.to_sse() for event in events]


@pytest.mark.asyncio
async def test_sensitive_file_results_are_not_written_to_the_journal(tmp_path: Path) -> None:
    async def runner(proposal: Any, emit: Any) -> str:
        from backend.runtime.primary import AgentSignal, AgentSignalKind

        emit(AgentSignal(AgentSignalKind.TOOL_CALL, tool_name="read_file", payload={"path": ".env"}))
        emit(AgentSignal(AgentSignalKind.TOOL_RESULT, tool_name="read_file", payload={"content": "plain-unknown-secret"}))
        return "Ficheiro consultado"

    async def unused(_turn: Any) -> AsyncIterator[Any]:
        if False:
            yield None

    stream = RunEventStream("sensitive-child", journal_path=tmp_path / "sensitive.jsonl")
    stream.start_journal()
    loop = PrimaryLoop(run_id=stream.run_id, query="test", stream=unused,
                       run_subagent_observed=runner, events=stream)
    proposal = SubagentProposal(name="CODER:secret", objective="Inspecionar", definition_of_done="reportar")
    events = [event async for event in loop._delegate([proposal], stream.emit)]
    await stream.aclose()
    result = next(event for event in events if event.type is RuntimeEventType.TOOL_COMPLETED
                  and event.payload.get("tool") == "read_file")
    assert "omitido" in result.payload["result"]["detail"]
    assert "plain-unknown-secret" not in (tmp_path / "sensitive.jsonl").read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("sensitive_path", [".env", ".git-credentials", ".envrc"])
async def test_primary_tool_details_and_approvals_do_not_journal_secrets(
    tmp_path: Path, sensitive_path: str,
) -> None:
    from backend.runtime.primary import AgentSignal, AgentSignalKind

    async def signals(_turn: Any) -> AsyncIterator[AgentSignal]:
        yield AgentSignal(AgentSignalKind.TOOL_CALL, tool_name="read_file",
                          payload={"path": sensitive_path, "content": "unknown-secret-in-args"})
        yield AgentSignal(AgentSignalKind.CONFIRMATION, tool_name="read_file", payload={
            "confirmation_id": "approval-1",
            "tool_args": {"path": sensitive_path, "content": "unknown-secret-in-approval"},
        })
        yield AgentSignal(AgentSignalKind.TOOL_RESULT, tool_name="read_file",
                          payload={"content": "unknown-secret-in-file"})
        yield AgentSignal(AgentSignalKind.TOOL_CALL, tool_name="search_in_files",
                          payload={"path": "src", "api_key": "private-api-key"})
        yield AgentSignal(AgentSignalKind.TOOL_RESULT, tool_name="search_in_files",
                          payload={"matches": [], "authorization": "private-auth"})
        yield AgentSignal(AgentSignalKind.TOKEN, text="Inspeção concluída.")

    journal = tmp_path / "primary.jsonl"
    stream = RunEventStream("sensitive-primary", journal_path=journal)
    stream.start_journal()
    loop = PrimaryLoop(run_id=stream.run_id, query="test", stream=signals,
                       events=stream, max_cycles=1)
    events = [event async for event in loop.run()]
    await stream.aclose()

    saved = journal.read_text(encoding="utf-8")
    rendered = "".join(frame.model_dump_json() for event in events
                       for frame in runtime_event_to_stream_events(event))
    for secret in ("unknown-secret-in-args", "unknown-secret-in-approval", "unknown-secret-in-file",
                   "private-api-key", "private-auth"):
        assert secret not in saved
        assert secret not in rendered
    approval = next(event for event in events if event.type is RuntimeEventType.TOOL_PROGRESS)
    assert approval.payload["confirmation"]["confirmation_id"] == "approval-1"


@pytest.mark.asyncio
async def test_unmatched_tool_result_is_not_counted_as_a_file_read() -> None:
    from backend.runtime.primary import AgentSignal, AgentSignalKind

    async def signals(_turn: Any) -> AsyncIterator[AgentSignal]:
        yield AgentSignal(AgentSignalKind.TOOL_RESULT, tool_name="read_file",
                          payload={"content": "unknown-secret"})
        yield AgentSignal(AgentSignalKind.TOKEN, text="Fim.")

    loop = PrimaryLoop(run_id="orphan-tool-result", query="test", stream=signals, max_cycles=1)
    events = [event async for event in loop.run()]
    assert not any(event.type is RuntimeEventType.FILE_READ for event in events)
    result = next(event for event in events if event.type is RuntimeEventType.TOOL_COMPLETED)
    assert "unknown-secret" not in json.dumps(result.to_sse())
