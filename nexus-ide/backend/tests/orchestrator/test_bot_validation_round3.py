"""Regressions for the real ERNIE validation of PR #5 at 0ad4a34.

The cases are the ones the live model actually hit: a shell command that
walked out of the bot folder, execute_code reading a host file, a run that
ended with the iteration marker and zero text tokens, consult_agent talking
to a dead local provider, todo_write rejecting ordinary item shapes, a DNS
failure with no cause, read-only commands tripping the circuit breaker, and
a group turn whose prompt never mentioned the bot's tools.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import httpcore
import pytest

from backend.agents.base import AgentAction, AgentBase, AgentRequest
from backend.agents.event_protocol import encode_event
from backend.core.workspace_security import (
    _validate_shell_command,
    command_paths_escape_root,
)
from backend.core.workspace_shell import execute_shell
from backend.llm.caller_context import bind_caller_llm
from backend.runtime.events import RuntimeEventType
from backend.runtime.group_primary import group_system_addon
from backend.runtime.primary import AgentSignal, AgentSignalKind, PrimaryLoop
from backend.tools import agent_comm as agent_comm_module
from backend.tools.code_executor import execute_code
from backend.tools.registry import (
    execute_tool,
    get_tool,
    reset_tool_failures,
    tool_failure_count,
    validate_tool_args,
)
from backend.tools.safe_http import PublicAddressNetworkBackend
from backend.tools.todo_tools import todo_write


def test_shell_tokens_cannot_walk_out_of_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "bot"
    workspace.mkdir()
    secret_dir = tmp_path / "backend" / "orchestrator" / "routes"
    secret_dir.mkdir(parents=True)
    (secret_dir / "chat_primary.py").write_text("SECRET", encoding="utf-8")

    reason = command_paths_escape_root(
        r"dir /b ..\..\..\backend\orchestrator\routes", workspace
    )
    assert reason and "escapes" in reason
    assert command_paths_escape_root("ls ..", workspace)
    assert command_paths_escape_root("ls /etc", workspace)
    assert command_paths_escape_root("ls sub/file.txt", workspace) is None
    assert command_paths_escape_root("dir /b", workspace) is None

    ok, detail = _validate_shell_command("git ls-tree -r HEAD")
    assert ok, detail
    ok, detail = _validate_shell_command("type file.txt")
    assert ok, detail
    ok, detail = _validate_shell_command(
        "powershell -NoProfile -Command Get-Content file.txt"
    )
    assert ok, detail
    ok, detail = _validate_shell_command("powershell -Command Remove-Item file.txt")
    assert not ok


async def test_execute_shell_does_not_list_the_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "bot"
    workspace.mkdir()
    (tmp_path / "outside.txt").write_text("OUTSIDE", encoding="utf-8")

    escaped = await execute_shell("ls ..", cwd=str(workspace))
    assert escaped.get("policy_denied") is True
    assert "OUTSIDE" not in str(escaped.get("stdout") or "")

    listed = await execute_shell(
        r"dir /b ..\..\..\backend\orchestrator\routes", cwd=str(workspace)
    )
    assert listed.get("policy_denied") is True
    assert "chat_primary.py" not in str(listed.get("stdout") or "")


async def test_python_inline_and_execute_code_stay_inside_the_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "bot"
    workspace.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-VALUE", encoding="utf-8")

    inline = await execute_shell('python -c "print(1 + 1)"', cwd=str(workspace))
    assert "2" in str(inline.get("stdout") or "")

    leaked = await execute_code(
        "print(open('../secret.txt', encoding='utf-8').read())",
        "python",
        project_path=str(workspace),
    )
    assert "TOP-SECRET-VALUE" not in leaked["stdout"]
    assert leaked["exit_code"] != 0

    absolute = await execute_code(
        f"print(open({str(secret)!r}, encoding='utf-8').read())",
        "python",
        project_path=str(workspace),
    )
    assert "TOP-SECRET-VALUE" not in absolute["stdout"]
    assert absolute["exit_code"] != 0

    denied = await execute_code("print('should not run')", "python")
    assert denied["exit_code"] != 0
    assert "workspace" in denied["stderr"].lower()


async def test_policy_denials_do_not_disable_the_shell(tmp_path: Path) -> None:
    import backend.tools.shell_runner  # noqa: F401

    session = "policy-denials"
    reset_tool_failures(session)
    for _ in range(3):
        result = await execute_tool(
            "run_shell",
            session,
            {"command": "ls .."},
            confirmed=True,
            autonomous=True,
            auto_accept=True,
            project_path=str(tmp_path),
        )
        assert result.get("ok") is False
        assert "disabled for this session" not in str(result.get("error") or "")
    assert tool_failure_count("run_shell", session) == 0
    again = await execute_tool(
        "run_shell",
        session,
        {"command": "ls .."},
        confirmed=True,
        autonomous=True,
        auto_accept=True,
        project_path=str(tmp_path),
    )
    assert "disabled for this session" not in str(again.get("error") or "")


async def test_todo_write_accepts_the_shapes_models_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.tools.todo_tools as todo_tools

    monkeypatch.setattr(todo_tools, "TODOS_DIR", tmp_path)
    result = await todo_write(
        operation="set_all",
        session_id="todos-round3",
        items=["um", {"title": "dois"}, {"text": "tres", "status": "done"}],
    )
    assert result["ok"] is True, result
    contents = [item["content"] for item in result["todos"]]
    assert contents == ["um", "dois", "tres"]
    assert result["todos"][2]["status"] == "completed"
    assert {item["priority"] for item in result["todos"]} == {"normal"}


def test_consult_priority_is_optional() -> None:
    spec = get_tool("consult_agent")
    assert spec is not None
    assert validate_tool_args(spec, {"agent": "ANALYZER", "question": "revê isto"}) == []
    assert (
        validate_tool_args(
            spec, {"agent": "ANALYZER", "question": "revê isto", "priority": "normal"}
        )
        == []
    )


async def test_consult_agent_uses_the_caller_provider_and_surfaces_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    class _Agent:
        async def run(self, request: AgentRequest):
            seen["client"] = request.client
            seen["model"] = request.context.get("_model_override")
            yield encode_event("error", "All connection attempts failed")

    monkeypatch.setattr(
        "backend.orchestrator.registry.build_default_registry", lambda: object()
    )
    monkeypatch.setattr("backend.orchestrator.registry.resolve", lambda *_args: _Agent())

    caller = object()
    bind_caller_llm(caller, "baidu/ernie-5.5-flash-preview:free")
    result = await agent_comm_module.consult_agent(
        agent="ANALYZER",
        question="o que falhou?",
        priority="normal",
        session_id="consult-round3",
    )
    assert seen["client"] is caller
    assert seen["model"] == "baidu/ernie-5.5-flash-preview:free"
    assert "All connection attempts failed" in str(result.get("error") or "")
    assert "returned no output" not in str(result)


async def test_dns_failure_names_the_os_error_and_falls_back() -> None:
    async def broken(_host: str, _port: int):
        raise OSError("getaddrinfo failed")

    backend = PublicAddressNetworkBackend(resolver=broken)
    with pytest.raises(httpcore.ConnectError, match="getaddrinfo failed"):
        await backend._resolve_public_addresses("example.com", 443, 1.0)


async def test_dns_uses_the_thread_resolver_when_the_loop_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def loop_fails(self, host, port, *, family=0, type=0, proto=0, flags=0):
        raise OSError("loop getaddrinfo failed")

    def thread_ok(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", loop_fails)
    monkeypatch.setattr(socket, "getaddrinfo", thread_ok)
    backend = PublicAddressNetworkBackend()
    addresses = await backend._resolve_public_addresses("example.com", 443, 2.0)
    assert addresses == ["1.1.1.1"]


async def test_duckduckgo_lite_markup_is_not_reported_as_zero_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.tools import web_search

    class _Response:
        text = '<a class="result-link" href="https://example.com/a">Example</a>'

    async def fake_request(*_args, **_kwargs):
        return _Response()

    monkeypatch.setattr(web_search, "_request_with_retry", fake_request)
    hits = await web_search._search_duckduckgo("nexus ide")
    assert [hit.url for hit in hits] == ["https://example.com/a"]


class _BudgetAgent(AgentBase):
    name = "Budget"
    model_key = "nano"
    prompt_file = "router"
    supported_actions = {AgentAction.READ_FILE}

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.attempts = 0

    async def stream_llm(self, request, **_kwargs):
        self.attempts += 1
        index = min(self.attempts - 1, len(self._responses) - 1)
        yield self._responses[index]

    async def _execute(self, request):
        yield "ok"


def _budget_request() -> AgentRequest:
    return AgentRequest(
        session_id="budget-round3",
        query="lê o ficheiro e resume",
        client=object(),
        max_iterations=1,
    )


_TOOL = '```tool\n{"name":"read_file","arguments":{"path":"notes.txt"}}\n```'


async def test_exhausted_budget_still_writes_the_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def execute(name, _session_id, args, **_kwargs):
        return {"tool": name, "result": {"content": "linha 1"}}

    monkeypatch.setattr("backend.agents.base.execute_tool", execute)
    agent = _BudgetAgent([_TOOL, "Resumo final com a evidência recolhida."])
    output = [part async for part in agent._run_react_loop(_budget_request())]
    joined = "".join(output)
    assert "Resumo final com a evidência recolhida." in joined
    assert "Evidência desta execução" in joined
    assert "read_file" in joined
    assert agent._last_run_success is False


async def test_exhausted_budget_emits_evidence_before_the_failure_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def execute(name, _session_id, args, **_kwargs):
        return {"tool": name, "error": "ficheiro em falta"}

    monkeypatch.setattr("backend.agents.base.execute_tool", execute)
    agent = _BudgetAgent([_TOOL, _TOOL])
    output = [part async for part in agent._run_react_loop(_budget_request())]
    joined = "".join(output)
    evidence_at = joined.find("Evidência desta execução")
    markers = [
        index
        for index in (
            joined.find("[TAREFA NÃO CONCLUÍDA]"),
            joined.find("[RECOLHA CONCLUÍDA — SÍNTESE INCOMPLETA]"),
        )
        if index >= 0
    ]
    assert evidence_at >= 0, joined[:2000]
    assert markers and min(markers) > evidence_at
    assert agent._last_run_success is False


async def test_incomplete_run_is_visible_as_a_message() -> None:
    async def stream(_turn):
        yield AgentSignal(
            AgentSignalKind.ERROR,
            text=(
                "[TAREFA NÃO CONCLUÍDA] O agente atingiu o limite de "
                "12 passos sem produzir uma resposta final."
            ),
            payload={"reason": "agent_incomplete"},
            ok=False,
        )

    loop = PrimaryLoop(run_id="run-incomplete-visible", query="resume", stream=stream)
    events = [event async for event in loop.run()]
    kinds = [event.type for event in events]
    assert RuntimeEventType.MESSAGE_DELTA in kinds
    assert RuntimeEventType.RUN_FAILED in kinds
    assert loop.telemetry.time_to_first_token is not None
    text = "".join(
        str(event.payload.get("text") or "")
        for event in events
        if event.type is RuntimeEventType.MESSAGE_DELTA
    )
    assert "TAREFA NÃO CONCLUÍDA" in text
    assert loop.outcome.failed is True


async def test_group_prompt_names_the_bots_tools() -> None:
    from backend.agents.nexus_primary import NexusPrimaryAgent
    from backend.orchestrator.routes.chat_primary import _bot_capability_policy

    profile = {
        "name": "Ana",
        "description": "leitora",
        "capabilities": {
            "read": True,
            "research": False,
            "tasks": False,
            "memory": False,
            "write": False,
            "shell": True,
            "browser": False,
            "mcp": False,
            "auto_accept": True,
        },
    }
    addon = group_system_addon([], profile, "lê o README")
    assert "read_file" in addon
    assert "run_shell" in addon
    assert "chama essas ferramentas" in addon
    assert "NO-TOOLS LANE" not in addon

    _capabilities, granted = _bot_capability_policy(profile)
    agent = NexusPrimaryAgent()
    agent.enable_memory = False
    request = AgentRequest(
        session_id="group-tools",
        query="lê o README",
        client=object(),
        context={
            "_system_addon": addon,
            "_allowed_tools": tuple(sorted(granted)),
            "_fast_chat_lane": True,
            "_isolated_bot_conversation": True,
        },
    )
    messages = await agent.abuild_messages(request)
    system = messages[0]["content"]
    assert "read_file" in system
    assert "NO-TOOLS LANE" not in system
    advertised = {
        schema["function"]["name"]
        for schema in agent._openai_tool_schemas(only=frozenset(granted)) or []
    }
    assert {"read_file", "run_shell"} <= advertised
