"""Real subprocess output and its passage through the chat event contract."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from backend.agents.base import AgentAction, AgentBase, AgentRequest
from backend.agents.event_protocol import encode_event
from backend.core.workspace_shell import execute_shell
from backend.orchestrator.routes.chat import _IncrementalResponseParser
from backend.orchestrator.routes.chat_primary import (
    runtime_event_to_stream_events,
    stream_events_to_signals,
)
from backend.runtime.activity_redaction import redact_activity
from backend.runtime.events import RunEventStream, RuntimeEventType
from backend.runtime.primary import AgentSignal, AgentSignalKind, PrimaryLoop
from backend.runtime.spawn_policy import SubagentProposal
from backend.tools.output_stream import observe_tool_output, shell_output_allowed
from backend.tools.shell_runner import run_shell  # noqa: F401 - registers the real tool


@pytest.mark.asyncio
async def test_real_command_streams_before_exit_and_redacts_split_secrets(tmp_path: Path) -> None:
    marker = tmp_path / "finished.txt"
    release = tmp_path / "release.txt"
    script = tmp_path / "stream_probe.py"
    script.write_text(
        "import pathlib, sys, time\n"
        "print('early stdout', flush=True)\n"
        "print('early stderr', file=sys.stderr, flush=True)\n"
        "sys.stdout.write('api_'); sys.stdout.flush(); time.sleep(.1)\n"
        "sys.stdout.write('key=sample-secret-value\\n'); sys.stdout.flush()\n"
        "print('-----BEGIN PRIVATE KEY-----', flush=True)\n"
        "print('private-material', flush=True)\n"
        "print('-----END PRIVATE KEY-----', flush=True)\n"
        f"release = pathlib.Path({str(release)!r})\n"
        "deadline = time.monotonic() + 90\n"
        "while not release.exists() and time.monotonic() < deadline: time.sleep(.02)\n"
        f"pathlib.Path({str(marker)!r}).write_text('done')\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )
    seen: list[dict[str, str]] = []
    result = None
    async for output, completed in observe_tool_output(
        lambda: execute_shell(f'"{sys.executable}" "{script}"', cwd=str(tmp_path), timeout=90),
        enabled=True,
    ):
        if output is not None:
            seen.append(output)
            if "early stdout" in output["text"]:
                assert not marker.exists(), "output arrived only after the subprocess exited"
                release.write_text("continue", encoding="utf-8")
        else:
            result = completed
    assert result and result["exit_code"] == 3
    assert marker.exists()
    text = "".join(item["text"] for item in seen)
    assert any(item["stream"] == "stdout" and "early stdout" in item["text"] for item in seen)
    assert any(item["stream"] == "stderr" and "early stderr" in item["text"] for item in seen)
    assert "sample-secret-value" not in text
    assert "private-material" not in text
    assert "REDACTED" in text and "chave privada omitida" in text


@pytest.mark.asyncio
async def test_closing_output_consumer_cancels_real_subprocess(tmp_path: Path) -> None:
    marker = tmp_path / "late.txt"
    release = tmp_path / "release-cancel.txt"
    script = tmp_path / "cancel_probe.py"
    script.write_text(
        "import pathlib, time\n"
        "print('started', flush=True)\n"
        f"release = pathlib.Path({str(release)!r})\n"
        "deadline = time.monotonic() + 90\n"
        "while not release.exists() and time.monotonic() < deadline: time.sleep(.02)\n"
        f"pathlib.Path({str(marker)!r}).write_text('too late')\n",
        encoding="utf-8",
    )
    observed = observe_tool_output(
        lambda: execute_shell(f'"{sys.executable}" "{script}"', cwd=str(tmp_path), timeout=90),
        enabled=True,
    )
    output, result = await asyncio.wait_for(anext(observed), timeout=60)
    assert output and "started" in output["text"] and result is None
    await observed.aclose()
    release.write_text("continue", encoding="utf-8")
    await asyncio.sleep(.5)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_agent_loop_streams_real_shell_result_before_it_exits(tmp_path: Path) -> None:
    marker = tmp_path / "agent-finished.txt"
    release = tmp_path / "agent-release.txt"
    script = tmp_path / "agent_probe.py"
    script.write_text(
        "import pathlib, time\n"
        "print('from real process', flush=True)\n"
        f"release = pathlib.Path({str(release)!r})\n"
        "deadline = time.monotonic() + 90\n"
        "while not release.exists() and time.monotonic() < deadline: time.sleep(.02)\n"
        f"pathlib.Path({str(marker)!r}).write_text('done')\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )

    class Agent(AgentBase):
        name = "NEXUS"
        model_key = "nano"
        prompt_file = "router"
        supported_actions = {AgentAction.RUN_SHELL}
        calls = 0

        async def stream_llm(self, _request, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                command = f'"{sys.executable}" "{script}"'
                yield "```tool\n" + json.dumps({"name": "run_shell", "arguments": {
                    "command": command, "timeout": 90,
                }}) + "\n```"
            else:
                yield "O comando terminou."

        async def _execute(self, _request):
            yield ""

        def _autonomous_call_preapproved(self, *_args):
            return True

    request = AgentRequest(
        session_id="real-shell-stream-test", query="executa o comando de verificação",
        client=object(), project_path=str(tmp_path), autonomous=True, max_iterations=2,
        context={"_allowed_tools": ("run_shell",)},
    )
    parser = _IncrementalResponseParser("NEXUS", str(tmp_path))
    frames = []
    async for chunk in Agent()._run_react_loop(request):
        for event in parser.feed(chunk):
            frames.append(event)
            if event.data.get("kind") == "command_output" and "from real process" in str(event.data.get("text")):
                assert not marker.exists()
                release.write_text("continue", encoding="utf-8")
    assert any(event.data.get("kind") == "command_output" for event in frames)
    failure = next(event for event in frames if event.type == "tool_error")
    assert failure.tool_result["exit_code"] == 3
    assert marker.exists()


@pytest.mark.asyncio
async def test_output_keeps_call_identity_through_runtime_and_replay(tmp_path: Path) -> None:
    parser = _IncrementalResponseParser("NEXUS")
    frame = encode_event("tool_output", "run_shell", {"stream": "stderr", "text": "a </event> b\n"})
    parsed = parser.feed(frame)
    assert len(parsed) == 1
    signal = stream_events_to_signals(parsed[0], str(tmp_path))
    assert signal and signal.kind is AgentSignalKind.COMMAND_OUTPUT
    assert signal.text == "a </event> b\n"

    async def stream(_turn):
        yield AgentSignal(AgentSignalKind.TOOL_CALL, tool_name="run_shell", payload={"command": "echo ok"})
        yield signal
        yield AgentSignal(AgentSignalKind.TOOL_RESULT, tool_name="run_shell", payload={"exit_code": 0})

    journal = tmp_path / "command.jsonl"
    events_stream = RunEventStream("command-stream-test", journal_path=journal)
    events_stream.start_journal()
    loop = PrimaryLoop(run_id="command-stream-test", query="executa", stream=stream, max_cycles=1,
                       project_path=str(tmp_path), events=events_stream)
    events = [event async for event in loop.run()]
    await events_stream.aclose()
    start = next(event for event in events if event.type is RuntimeEventType.TOOL_STARTED)
    output = next(event for event in events if event.type is RuntimeEventType.COMMAND_OUTPUT)
    finish = next(event for event in events if event.type is RuntimeEventType.TOOL_COMPLETED)
    assert start.seq < output.seq < finish.seq
    assert start.payload["call_id"] == output.payload["call_id"] == finish.payload["call_id"]
    public = runtime_event_to_stream_events(output)[0]
    assert public.data["kind"] == "command_output"
    assert public.data["text"] == "a </event> b\n"
    assert public.data["call_id"] == start.payload["call_id"]
    restored = RunEventStream.load_journal(journal)
    assert [event.to_sse() for event in restored] == [event.to_sse() for event in events]


@pytest.mark.asyncio
async def test_two_children_keep_their_command_output_separate_in_the_journal(tmp_path: Path) -> None:
    async def runner(proposal, emit):
        emit(AgentSignal(AgentSignalKind.TOOL_CALL, tool_name="run_shell", payload={"command": "echo ok"}))
        await asyncio.sleep(0)
        emit(AgentSignal(AgentSignalKind.COMMAND_OUTPUT, tool_name="run_shell", text=proposal.name,
                         payload={"stream": "stdout"}))
        emit(AgentSignal(AgentSignalKind.TOOL_RESULT, tool_name="run_shell", payload={"exit_code": 0}))
        return proposal.name

    async def unused(_turn):
        if False:
            yield None

    journal = tmp_path / "children.jsonl"
    event_stream = RunEventStream("child-commands", journal_path=journal)
    event_stream.start_journal()
    loop = PrimaryLoop(run_id=event_stream.run_id, query="test", stream=unused,
                       run_subagent_observed=runner, events=event_stream)
    proposals = [SubagentProposal(name=name, objective="verificar", definition_of_done="reportar")
                 for name in ("CODER:first", "DEBUGGER:second")]
    events = [event async for event in loop._delegate(proposals, event_stream.emit)]
    await event_stream.aclose()
    outputs = [event for event in events if event.type is RuntimeEventType.COMMAND_OUTPUT]
    assert len(outputs) == 2
    assert len({event.task_id for event in outputs}) == 2
    for output in outputs:
        start = next(event for event in events if event.type is RuntimeEventType.TOOL_STARTED
                     and event.payload["call_id"] == output.payload["call_id"])
        assert (start.agent_id, start.task_id) == (output.agent_id, output.task_id)
        assert output.payload["text"].startswith(output.agent_id)
    assert [event.to_sse() for event in RunEventStream.load_journal(journal)] == [
        event.to_sse() for event in events
    ]


def test_sensitive_file_commands_do_not_stream() -> None:
    assert not shell_output_allowed('type "secrets/.env"')
    assert not shell_output_allowed("cat credentials.json")
    assert shell_output_allowed("python -m pytest -q")


def test_unterminated_private_key_is_not_returned_in_final_activity() -> None:
    value = redact_activity("before\n-----BEGIN PRIVATE KEY-----\nprivate-material")
    assert "private-material" not in value
    assert "REDACTED" in value
