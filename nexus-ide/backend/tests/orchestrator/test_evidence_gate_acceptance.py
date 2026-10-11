"""Acceptance tests for the P0.1 "evidence gate" root-cause fix.

The failure this file pins
--------------------------
Every engine-created task used to be built without an allowlist, so
``TaskNode.allowed_tools`` kept its ``[]`` default (``dependency_graph.py``).
``PlanExecutor`` then injected ``"_allowed_tools": []`` into the request, and
``AgentBase`` reads that key as an *explicit* runtime contract
(``_runtime_allowed_tools``): an empty configured set does not mean "no
contract", it means "nothing is permitted". Every tool call was dropped with
``Agent contract forbids tool``, ``_has_required_tool_evidence`` stayed False,
``_last_run_success`` became False, and the executor failed the task with
"Agent execution failed its runtime/tool evidence gate". The agent had done
nothing wrong — it had been forbidden to do anything at all.

The fix under test
------------------
* ``plan_validation.default_task_tools`` derives the lawful allowlist for an
  agent (its capability contract ∩ the tools this process can run).
* ``PlanExecutor`` uses it as the default for a task that declares nothing,
  both for the injected ``_allowed_tools`` and for the contract pre-validation.
* ``verification``'s Verify/Fix/Final-Review factories declare their tools
  explicitly (defence in depth).
* Dynamic ``spawn_task`` children inherit the child agent's contract.
* The deterministic fallback plan publishes ``PLAN_CREATED`` so the mission
  tracker stops counting broad pre-flight proposals.

Everything here runs the real engine, the real agent registry, the real
``AgentBase`` ReAct loop and the real evidence gate. Only two things are
scripted: the LLM client (no provider is contacted) and the tool executor
(no sandbox/subprocess is spawned). The DB and the conversation log are
redirected away from the repository by the global ``conftest`` and this
module's fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode
from backend.orchestrator.engine import OrchestrationEngine, OrchestrationState
from backend.orchestrator.events import EventBus, EventType
from backend.orchestrator.mission_control import ContractState, start_mission
from backend.orchestrator.plan_validation import (
    PlanningResult,
    build_deterministic_plan,
    default_task_tools,
)
from backend.orchestrator.registry import build_default_registry
from backend.orchestrator.types import OrchestrationResult
from backend.orchestrator.verification import (
    _create_final_review_task,
    _create_fix_tasks,
    _create_verification_tasks,
    _find_tasks_needing_verification,
)

SESSION = "it-evidence-gate"

#: The message the executor writes when the agent's own runtime verdict is
#: "not enough evidence". A passing test must never produce it; the
#: anti-weakening tests must (see :func:`test_invalid_evidence_still_fails`).
EVIDENCE_GATE_ERROR = "evidence gate"

#: One representative tool per agent, used to find the recorded allowlist.
AGENT_TOOL = {
    "ANALYZER": "data_analysis",
    "CODER": "write_file",
    "DEBUGGER": "execute_code",
}


# ---------------------------------------------------------------------------
# Scripted doubles
# ---------------------------------------------------------------------------


class _ScriptedClient:
    """An LLM client that replays one answer per ``chat_stream`` call.

    Responses are routed by task name and every route keeps its own cursor.
    Routing matters because the executor runs a layer's tasks concurrently, so
    a single global script would be consumed in whatever order the scheduler
    interleaved them. The match is anchored on the executor's task prompt
    (``TASK: <name>``) rather than the whole message blob, because a task's
    prompt also embeds its dependencies' names as context.
    """

    provider_name = "scripted"

    def __init__(
        self,
        routes: dict[str, list[str]],
        *,
        fallback: str = "Concluído sem passos adicionais.",
    ) -> None:
        self._routes = {key: list(value) for key, value in routes.items()}
        self._fallback = fallback
        self.calls: list[dict[str, Any]] = []

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        on_final_chunk: Any = None,
        **kwargs: Any,
    ):
        blob = "\n".join(str(message.get("content", "")) for message in messages)
        self.calls.append({"model": model, "messages": messages})
        matched = False
        text = self._fallback
        for name, responses in self._routes.items():
            if f"TASK: {name}" not in blob:
                continue
            matched = True
            if responses:
                text = responses.pop(0)
            break
        assert matched or not self._routes, (
            "scripted client received a prompt no route claims: " + repr(blob[-400:])
        )
        yield text


def _tool_turn(tool: str, **args: Any) -> str:
    """One ReAct iteration that calls *tool* — the executable wrapper format."""
    payload = json.dumps({"name": tool, "arguments": args}, ensure_ascii=False)
    return f"```tool\n{payload}\n```\nVou executar {tool} agora."


def _answer(text: str) -> str:
    """One ReAct iteration that produces the final answer (no tool call)."""
    return text


class _ToolStub:
    """Replaces ``backend.agents.base.execute_tool`` with a scripted executor.

    It records the runtime allowlist the agent received, and it synthesises the
    ``evidence`` block exactly the way ``registry._typed_tool_response`` does:
    taken from the handler result when the handler supplies one, otherwise
    derived as ``verified = ok and not timed_out and exit_code in (None, 0)``.
    Reproducing that derivation is what keeps the evidence gate under test — a
    stub that always reported ``verified: True`` would make every test vacuous.
    """

    def __init__(self, results: dict[str, dict[str, Any]] | None = None) -> None:
        seeded = {"list_dir": _listing(), "read_file": _read()}
        seeded.update(results or {})
        self.results = seeded
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        name: str,
        session_id: str | None,
        args: dict,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "tool": name,
                "args": args,
                "allowed_tools": kwargs.get("allowed_tools"),
                "autonomous": kwargs.get("autonomous"),
                "project_path": kwargs.get("project_path"),
            }
        )
        response = dict(self.results.get(name) or self._unknown_tool(name))
        response["evidence"] = self._evidence_for(name, response)
        if not response.get("error"):
            # ``_typed_tool_response`` only adds the key when there is an
            # error: a present-but-None key reads as a failure downstream.
            response.pop("error", None)
        return response

    @staticmethod
    def _unknown_tool(name: str) -> dict[str, Any]:
        return {
            "tool": name,
            "ok": False,
            "result": None,
            "error": f"Tool '{name}' not found",
            "error_category": "unknown_tool",
        }

    @staticmethod
    def _evidence_for(name: str, response: dict[str, Any]) -> dict[str, Any]:
        raw = response.get("result") if isinstance(response.get("result"), dict) else {}
        declared = raw.get("evidence")
        if isinstance(declared, dict):
            return declared
        exit_code = response.get("exit_code")
        if exit_code is None and raw.get("exit_code") is not None:
            exit_code = int(raw["exit_code"])
        timed_out = bool(response.get("timed_out") or raw.get("timed_out", False))
        return {
            "kind": "tool_execution",
            "tool": name,
            "verified": bool(
                response.get("ok")
                and not timed_out
                and (exit_code is None or exit_code == 0)
            ),
            "command": raw.get("command"),
            "exit_code": exit_code,
            "duration_ms": response.get("duration_ms", 0),
            "timed_out": timed_out,
        }

    def allowlist_for(self, tool: str) -> frozenset[str] | None:
        for call in self.calls:
            if call["tool"] == tool:
                return call["allowed_tools"]
        raise AssertionError(
            f"{tool} was never executed; calls: {[c['tool'] for c in self.calls]}"
        )

    def tools_called(self) -> list[str]:
        return [call["tool"] for call in self.calls]


def _listing() -> dict[str, Any]:
    return {"ok": True, "result": {"path": ".", "entries": ["notes.py", "README.md"]}}


def _read() -> dict[str, Any]:
    return {
        "ok": True,
        "result": {"path": "notes.py", "content": "def note():\n    return 1\n"},
    }


def _verified_write(path: str) -> dict[str, Any]:
    """A successful ``write_file``: the handler states the file it changed."""
    return {
        "ok": True,
        "result": {
            "path": path,
            "written": True,
            "bytes_written": 64,
            "evidence": {
                "kind": "file_write",
                "tool": "write_file",
                "verified": True,
                "path": path,
                "command": None,
                "exit_code": None,
                "timed_out": False,
            },
        },
    }


def _executed(exit_code: int = 0, *, timed_out: bool = False) -> dict[str, Any]:
    """An ``execute_code`` result with no ``evidence`` key, as in production.

    The registry then derives the evidence itself, which is the branch the
    verification gate reads.
    """
    return {
        "ok": exit_code == 0 and not timed_out,
        "result": {
            "stdout": "1 passed" if exit_code == 0 else "1 failed",
            "stderr": "",
            "exit_code": exit_code,
            "execution_time": 0.01,
            "timed_out": timed_out,
        },
        **({} if exit_code == 0 else {"error": f"verification exited with code {exit_code}"}),
    }


def _spawned(agent: str = "CODER", task_name: str = "Sub: cover helper") -> dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "status": "spawned",
            "spawned": True,
            "background": True,
            "task_name": task_name,
            "description": "Cover the helper with unit tests.",
            "agent": agent,
        },
    }


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the JSONL audit trail out of the repository."""
    import backend.core.conversation_log as conversation_log

    root = tmp_path / "conversations"
    root.mkdir(exist_ok=True)
    # Loggers are cached per session id; drop the cache so each test's patch of
    # the log directory actually takes effect.
    conversation_log._loggers.clear()
    monkeypatch.setattr(conversation_log, "_DEFAULT_LOG_DIR", root)
    yield root
    conversation_log._loggers.clear()


@pytest.fixture
def tool_stub(monkeypatch: pytest.MonkeyPatch) -> _ToolStub:
    """Inject the scripted tool executor into ``AgentBase``."""
    stub = _ToolStub()
    monkeypatch.setattr("backend.agents.base.execute_tool", stub)
    return stub


@pytest.fixture(autouse=True)
def deterministic_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the bounded improvement audit so call counts stay predictable."""
    monkeypatch.setenv("NEXUS_AUTONOMOUS_AUDIT_PASS", "off")


def _engine(client: _ScriptedClient, registry: dict[str, Any]) -> OrchestrationEngine:
    return OrchestrationEngine(
        llm_client=client,
        registry=registry,
        event_bus=EventBus(),
    )


def _plan(*steps: TaskNode, title: str = "Acceptance plan") -> ExecutionPlan:
    return ExecutionPlan.from_steps(
        title=title,
        description="Evidence-gate acceptance",
        steps=list(steps),
        session_id=SESSION,
    )


async def _run(
    steps: list[TaskNode],
    client: _ScriptedClient,
    tool_stub: _ToolStub,
    tmp_path: Path,
    *,
    session_id: str = SESSION,
) -> OrchestrationResult:
    engine = _engine(client, dict(build_default_registry()))
    return await engine.execute_plan(
        _plan(*steps),
        session_id,
        auto_approve=True,
        project_path=str(tmp_path),
    )


def _artifact(result: OrchestrationResult, agent: str) -> dict[str, Any]:
    matches = [a for a in result.task_results.values() if a.get("agent") == agent]
    assert matches, f"no artifact for agent {agent}: {list(result.task_results)}"
    return matches[0]


# ---------------------------------------------------------------------------
# 1-3: real missions must pass their evidence gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_mission_passes_evidence_gate(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """A discovery ANALYZER step completes once it actually inspected the code."""
    (tmp_path / "notes.py").write_text("def note():\n    return 1\n", encoding="utf-8")

    client = _ScriptedClient(
        {
            "Analyse the project structure": [
                _tool_turn("list_dir", path="."),
                _tool_turn("read_file", path="notes.py"),
                _answer("Inspecionei a estrutura e li o ponto de entrada."),
            ]
        }
    )
    step = TaskNode(
        name="Analyse the project structure",
        description="List the project files and read the main entrypoint.",
        agent="ANALYZER",
    )

    result = await _run([step], client, tool_stub, tmp_path)

    assert result.state == OrchestrationState.COMPLETED
    assert result.errors == []
    assert result.failed_tasks == 0
    artifact = _artifact(result, "ANALYZER")
    assert artifact["status"] == "completed"
    # The whole point: the agent must NOT have been left with an empty toolset.
    allowlist = tool_stub.allowlist_for("list_dir")
    assert allowlist, "ANALYZER must receive a non-empty runtime allowlist"
    assert set(allowlist) == set(default_task_tools("ANALYZER"))
    assert "read_file" in tool_stub.tools_called()


@pytest.mark.asyncio
async def test_tool_mission_passes(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """A DEBUGGER verification step passes when an executable check exits 0."""
    tool_stub.results = {"execute_code": _executed(0)}

    client = _ScriptedClient(
        {
            "Verify: helper module": [
                _tool_turn("execute_code", code="print('ok')", language="python"),
                _answer("Verificação executada.\nVERDICT: PASS"),
            ]
        }
    )
    step = TaskNode(
        name="Verify: helper module",
        description="Run the verification command and report its exit status.",
        agent="DEBUGGER",
        verification_commands=["python -m pytest -q"],
    )

    result = await _run([step], client, tool_stub, tmp_path)

    assert result.state == OrchestrationState.COMPLETED
    assert result.errors == []
    artifact = _artifact(result, "DEBUGGER")
    assert artifact["status"] == "completed"
    assert "execute_code" in tool_stub.tools_called()
    # The verification gate closes on verified executable evidence only.
    evidence = artifact["evidence"]
    assert any(item.get("verified") is True for item in evidence), evidence
    assert set(tool_stub.allowlist_for("execute_code")) == set(
        default_task_tools("DEBUGGER")
    )


@pytest.mark.asyncio
async def test_file_write_mission_passes(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """A CODER step passes when it wrote and verified a real file."""
    tool_stub.results = {"write_file": _verified_write("notes.py")}

    client = _ScriptedClient(
        {
            "Implement: add notes module": [
                _tool_turn(
                    "write_file",
                    path="notes.py",
                    content="def note():\n    return 1\n",
                ),
                _answer("Criei o módulo notes.py e reli o ficheiro escrito."),
            ]
        }
    )
    step = TaskNode(
        name="Implement: add notes module",
        description="Create the notes module with the requested behaviour.",
        agent="CODER",
    )

    result = await _run([step], client, tool_stub, tmp_path)

    assert result.state == OrchestrationState.COMPLETED
    assert result.errors == []
    artifact = _artifact(result, "CODER")
    assert artifact["status"] == "completed"
    assert "write_file" in tool_stub.tools_called()
    # The changed file is recorded as verified evidence, not merely claimed.
    changed = [
        item.get("path")
        for item in artifact["evidence"]
        if isinstance(item, dict) and item.get("verified") is True and item.get("path")
    ]
    assert changed == ["notes.py"], artifact["evidence"]


# ---------------------------------------------------------------------------
# 4: dynamic spawn_task children
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_mission_passes(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """A ``spawn_task`` child inherits a lawful, non-empty allowlist."""
    tool_stub.results = {
        "spawn_task": _spawned(),
        "write_file": _verified_write("test_helper.py"),
    }

    client = _ScriptedClient(
        {
            "Implement: refactor helper": [
                _tool_turn(
                    "spawn_task",
                    name="Sub: cover helper",
                    description="Cover the helper with unit tests.",
                    agent="CODER",
                    definition_of_done="tests for the helper pass",
                ),
                _answer("Deleguei a cobertura de testes a um sub-agente."),
            ],
            "Sub: cover helper": [
                _tool_turn("write_file", path="test_helper.py", content="# tests\n"),
                _answer("Escrevi os testes do helper."),
            ],
        }
    )
    parent = TaskNode(
        name="Implement: refactor helper",
        description="Refactor the helper module and delegate the extra work.",
        agent="CODER",
    )
    plan = _plan(parent, title="Subagent acceptance")

    engine = _engine(client, dict(build_default_registry()))
    result = await engine.execute_plan(
        plan,
        SESSION,
        auto_approve=True,
        project_path=str(tmp_path),
    )

    assert result.state == OrchestrationState.COMPLETED
    assert result.errors == []

    children = [
        task
        for task in plan.dependency_graph.get_all_tasks()
        if task.task_id != parent.task_id
    ]
    assert len(children) == 1, "the spawned child must become a real task"
    child = children[0]
    assert child.agent == "CODER"
    # Direct regression on the node the executor builds from the model request.
    assert child.allowed_tools, "a spawned child must not run with an empty toolset"
    assert child.allowed_tools == default_task_tools("CODER")
    assert child.status.value == "completed"

    # …and the runtime contract the child's agent actually received.
    child_allowlist = tool_stub.allowlist_for("write_file")
    assert child_allowlist, "the child agent must receive a runtime allowlist"
    assert set(child_allowlist) == set(default_task_tools("CODER"))


# ---------------------------------------------------------------------------
# 5: the gate must NOT be weakened
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_evidence_still_fails(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """Anti-enfraquecimento: a substantive step that only listed a directory
    still fails its evidence gate."""
    client = _ScriptedClient(
        {
            "Implement: parser module": [
                _tool_turn("list_dir", path="."),
                _answer("Listei o diretório; o trabalho está feito."),
            ]
        }
    )
    step = TaskNode(
        name="Implement: parser module",
        description="Implement the parser module.",
        agent="CODER",
    )

    result = await _run([step], client, tool_stub, tmp_path)

    assert result.state == OrchestrationState.FAILED
    assert result.failed_tasks == 1
    assert result.completed_tasks == 0
    assert any(EVIDENCE_GATE_ERROR in err for err in result.errors), result.errors
    artifact = _artifact(result, "CODER")
    assert artifact["status"] == "failed"


@pytest.mark.asyncio
async def test_verification_still_requires_executable_evidence(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """Anti-enfraquecimento: ``read_file`` can never close a verification gate."""
    tool_stub.results = {"read_file": _read()}

    client = _ScriptedClient(
        {
            "Verify: parser module": [
                _tool_turn("read_file", path="parser.py"),
                _answer("Li o código e está correto.\nVERDICT: PASS"),
            ]
        }
    )
    step = TaskNode(
        name="Verify: parser module",
        description="Run the verification command and report its exit status.",
        agent="DEBUGGER",
        verification_commands=["python -m pytest -q"],
    )

    result = await _run([step], client, tool_stub, tmp_path)

    assert result.state == OrchestrationState.FAILED
    assert result.failed_tasks == 1
    assert any(EVIDENCE_GATE_ERROR in err for err in result.errors), result.errors


@pytest.mark.asyncio
async def test_failing_verification_command_still_fails(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """Anti-enfraquecimento: a verification command that exits non-zero is not
    passing evidence."""
    tool_stub.results = {"run_tests": _executed(1)}

    client = _ScriptedClient(
        {
            "Verify: parser module": [
                _tool_turn("run_tests", path="."),
                _answer("Corri os testes.\nVERDICT: FAIL"),
            ]
        }
    )
    step = TaskNode(
        name="Verify: parser module",
        description="Run the verification command and report its exit status.",
        agent="DEBUGGER",
        verification_commands=["python -m pytest -q"],
    )

    result = await _run([step], client, tool_stub, tmp_path)

    assert result.state == OrchestrationState.FAILED
    assert result.failed_tasks == 1
    assert "run_tests" in tool_stub.tools_called()
    assert any(EVIDENCE_GATE_ERROR in err for err in result.errors), result.errors


# ---------------------------------------------------------------------------
# 6: the engine's own task factories must declare their tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_created_tasks_declare_tools(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """Direct regression for ``verification.py``'s three factories.

    Before the fix every one of these tasks carried ``allowed_tools=[]``, so the
    executor injected an empty contract and the agent could not run a single
    tool — the verify/fix/review cycle existed but could never do anything.
    """
    prior = OrchestrationResult(
        run_id="prior",
        state=OrchestrationState.COMPLETED,
        task_results={
            "task-coder": {
                "name": "Implement: notes module",
                "agent": "CODER",
                "status": "completed",
                "output": "Implementei o módulo notes.py.",
                "origin": "Implement: notes module",
            }
        },
    )

    verify_tasks = _create_verification_tasks(
        _find_tasks_needing_verification(prior), prior, SESSION
    )
    fix_tasks = _create_fix_tasks(
        [{"name": "Verify: notes module", "origin": "notes module", "output": "falhou"}],
        verify_tasks,
        SESSION,
    )
    review_task = _create_final_review_task("Auditar o módulo notes", prior, SESSION)

    created = [*verify_tasks, *fix_tasks, review_task]
    assert len(created) == 3
    for task in created:
        assert task.allowed_tools, f"{task.name} ({task.agent}) declares no tools"
        assert task.allowed_tools == default_task_tools(task.agent), (
            f"{task.agent} must declare exactly its own capability contract"
        )

    named: dict[str, list[str]] = {}
    for task in created:
        tool = AGENT_TOOL[task.agent]
        named[task.name] = [
            _tool_turn(tool),
            _answer(f"Tarefa {task.name} concluída."),
        ]

    # …and the executor must hand that allowlist to the agent, not an empty set.
    tool_stub.results = {
        "execute_code": _executed(0),
        "write_file": _verified_write("notes.py"),
        "data_analysis": {"ok": True, "result": {"rows": 3}},
    }
    client = _ScriptedClient(named)
    plan = _plan(*created, title="Engine-created tasks")
    engine = _engine(client, dict(build_default_registry()))
    result = await engine.execute_plan(
        plan,
        SESSION,
        auto_approve=True,
        project_path=str(tmp_path),
    )

    assert result.state == OrchestrationState.COMPLETED
    assert result.failed_tasks == 0
    assert len(result.task_results) == 3
    for task in created:
        allowlist = tool_stub.allowlist_for(AGENT_TOOL[task.agent])
        assert allowlist, f"{task.agent} ran with an empty allowlist"
        assert set(allowlist) == set(default_task_tools(task.agent))


# ---------------------------------------------------------------------------
# 7: the deterministic fallback plan must reach the mission tracker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mission_tracker_syncs_deterministic_fallback_plan(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """A blocked planner must not leave the mission card counting air.

    The model plan publishes ``PLAN_CREATED`` and the tracker consumes it to
    replace its broad pre-flight proposals. The deterministic fallback used to
    reach ``execute_plan`` without emitting that event, so wave contracts stayed
    ``proposed``/``skipped`` and progress was measured against work that never
    existed.
    """
    tracker = start_mission(
        "Auditar o projeto", project_path=str(tmp_path), deep_scan=False
    )
    pre_sync = [
        contract.state
        for wave in tracker.mission.waves
        for contract in wave.contracts
    ]
    assert ContractState.SKIPPED in pre_sync or ContractState.PROPOSED in pre_sync

    tool_stub.results = {
        "list_dir": _listing(),
        "read_file": _read(),
        "write_file": _verified_write("notes.py"),
        "execute_code": _executed(0),
        "data_analysis": {"ok": True, "result": {"rows": 3}},
    }
    proposal = build_deterministic_plan("Auditar o projeto", {}, SESSION)
    client = _ScriptedClient(
        {
            # The deterministic plan itself declares this task's allowlist
            # (read_file/list_dir), so the scripted agent must stay inside it.
            "Analyze project scope": [
                _tool_turn("list_dir", path="."),
                _answer("Analisei o âmbito medido."),
            ],
            "Implement scoped change": [
                _tool_turn("write_file", path="notes.py", content="# change\n"),
                _answer("Implementei a alteração."),
            ],
            "Verify scoped change": [
                _tool_turn("execute_code", code="print('ok')"),
                _answer("Verificação executada.\nVERDICT: PASS"),
            ],
            # The review task declares the full ANALYZER contract, so it can
            # use a substantive (non-discovery) tool like ``data_analysis``.
            "Final Quality Review": [
                _tool_turn("data_analysis", path="notes.py"),
                _answer("Revisão final concluída."),
            ],
        }
    )

    published: list[dict[str, Any]] = []
    bus = EventBus()

    async def _record(event: Any) -> None:
        if event.event_type == EventType.PLAN_CREATED:
            published.append(event.data)

    await bus.subscribe(EventType.PLAN_CREATED.value, _record)

    class _BlockedPlanner:
        """A planner that cannot emit structured JSON — the fallback trigger."""

        async def create(
            self, objective: str, session_id: str, **_: Any
        ) -> PlanningResult:
            return PlanningResult(
                status="blocked",
                source="deterministic_fallback",
                error="planner output was not a parseable structured plan",
                deterministic_proposal=proposal,
            )

    engine = OrchestrationEngine(
        llm_client=client,
        registry=dict(build_default_registry()),
        event_bus=bus,
        plan_creator=_BlockedPlanner(),  # type: ignore[arg-type]
    )

    result = await engine.execute_autonomous(
        objective="Auditar o projeto",
        session_id=SESSION,
        project_path=str(tmp_path),
        max_verify_iterations=0,
    )

    assert result.state == OrchestrationState.COMPLETED, result.errors
    assert len(published) == 1, "the fallback plan must publish PLAN_CREATED"

    plan_data = published[0]
    assert [step["agent"] for step in plan_data["steps"]] == [
        task.agent for task in proposal.steps
    ]
    tracker.sync_execution_plan(plan_data)

    contracts = [c for wave in tracker.mission.waves for c in wave.contracts]
    assert contracts, "sync_execution_plan produced no contracts"
    assert all(c.state == ContractState.READY for c in contracts), [
        (c.name, c.state) for c in contracts
    ]
    assert tracker.mission.to_dict()["tasks_total"] == len(proposal.steps)
    assert tracker.find_contract(proposal.steps[0].task_id) is not None


# ---------------------------------------------------------------------------
# 8: a rejection must be distinguishable from the evidence gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_rejection_message_is_distinct(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """An over-broad allowlist is a contract rejection, not an evidence gap.

    The default must never *widen* what an agent may do. An explicit list is
    honoured verbatim, so a list the agent's own contract forbids is rejected
    before the agent runs — with a message that says which contract was broken
    and that is not confusable with "not enough evidence".
    """
    client = _ScriptedClient(
        {
            "Implement: parser module": [
                _tool_turn("write_file", path="parser.py", content="# new\n"),
                _answer("Escrevi o parser."),
            ]
        }
    )
    step = TaskNode(
        name="Implement: parser module",
        description="Implement the parser module.",
        agent="CODER",
        # ``web_search`` is not in CODER's capability contract.
        allowed_tools=["web_search"],
    )

    result = await _run([step], client, tool_stub, tmp_path)

    assert result.state == OrchestrationState.FAILED
    assert tool_stub.tools_called() == [], "a rejected contract must not execute"
    assert result.errors
    rejection = result.errors[0]
    assert "contract" in rejection.lower()
    assert "does not allow tool" in rejection
    assert EVIDENCE_GATE_ERROR not in rejection, (
        "a contract rejection must not be reported as an evidence failure"
    )


@pytest.mark.asyncio
async def test_explicit_allowlist_is_never_widened(
    tool_stub: _ToolStub,
    isolated_logs: Path,
    tmp_path: Path,
) -> None:
    """A task that declares its tools keeps exactly those tools."""
    tool_stub.results = {"read_file": _read()}

    client = _ScriptedClient(
        {
            "Analyse the project structure": [
                _tool_turn("read_file", path="notes.py"),
                _answer("Li o ficheiro pedido."),
            ]
        }
    )
    step = TaskNode(
        name="Analyse the project structure",
        description="List the project files and read the main entrypoint.",
        agent="ANALYZER",
        allowed_tools=["read_file"],
    )

    result = await _run([step], client, tool_stub, tmp_path)

    assert result.state == OrchestrationState.COMPLETED
    assert set(tool_stub.allowlist_for("read_file")) == {"read_file"}
    assert "list_dir" not in tool_stub.tools_called()


def test_default_task_tools_are_a_subset_of_the_live_registry() -> None:
    """The helper's own contract: capability ∩ enabled-and-available tools."""
    from backend.tools.registry import list_tools

    available = {str(spec.name) for spec in list_tools(enabled_only=True)}
    for agent in ("ANALYZER", "CODER", "DEBUGGER"):
        tools = default_task_tools(agent)
        assert tools, f"{agent} resolved to an empty allowlist"
        assert set(tools) <= available, f"{agent} advertised an unavailable tool"

    # Fail-closed rather than permissive for anything unknown.
    assert default_task_tools("NOT_AN_AGENT") == []
    assert default_task_tools("") == []
