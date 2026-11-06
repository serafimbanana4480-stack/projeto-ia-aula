"""Fase 1 — the long-autonomy mission, run for real through the engine lane.

This is the mission the whole Fase 1 exists for:

    goal -> plan -> execute -> tool failure -> provider failure ->
    kill the process -> restart -> adopt the run -> idempotent replay ->
    verify -> report -> definition of done

Everything is real: the backend is a ``uvicorn`` subprocess, the model is a
threading HTTP server speaking the Ollama protocol, the project under repair is
written into ``tmp_path``, and the kill is a ``SIGKILL`` while a task agent is
still blocked inside a model call.

The scripted model is *role-aware*: the system prompt of every request says
which agent is asking, so the script plays the planner when the planner asks
(raw JSON, as ``config/prompts/planner.md`` demands), plays ANALYZER when the
read-only agent asks, and only offers writes to the CODER the plan assigns them
to — an offer of ``write_file`` to a read-only agent is refused by the contract,
which is the behaviour the audit's honest-verification work protects.

It injects exactly the failures the mission brief demands, once each:

* a real tool failure (``list_dir`` on a directory that does not exist);
* a provider failure (a 429) held open long enough to kill the process
  mid-task — the flag is set before the sleep, so the choreography never races
  the provider client's own retry policy;
* the PROBE_OK gate: the suite stays red until a file is written, which forces
  the loop back for a second cycle — the "task that fails once and demands a
  replan" of the brief.

What the test asserts at the end is durable state, not stream chatter: one run
row (the restarted engine *adopted* it instead of forking a second), the plan,
the checkpoints, the side-effect ledger with no duplicate keys (the replayed
writes after the restart were refused re-execution by the idempotency guard),
the repaired project, the report, and the definition of done.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from backend.tests.integration.test_autonomy_helpers_mission import (
    CALC_FIX_ARGS,
    MISSION_GOAL,
    PIPELINE_FIX_ARGS,
    PROBE_ARGS,
    REPORT_NAME,
    TEST_FIX_ARGS,
    build_defective_project,
    missing_defects,
)
from backend.tests.integration.test_run_resume_e2e import (
    STARTUP_TIMEOUT_S,
    BackendUnderTest,
    _free_port,
    _phases,
    _run_rows,
    _side_effects,
)

logger = logging.getLogger(__name__)

# Assembled from parts so this file never contains the literal tool-call
# marker (indistinguishable from a real call to anything reading this file).
TOOL_TAG_OPEN = "<" + "tool_call" + ">"
TOOL_TAG_CLOSE = "</" + "tool_call" + ">"

#: How long the scripted model holds the provider failure open. It is the
#: window in which the test kills the process: the flag is set before the
#: sleep, the 429 is only returned after it, so the choreography never depends
#: on the provider client's retry timing.
INJECTED_FAILURE_WINDOW_S = 15.0

#: The plan the scripted planner emits. It follows the schema documented in
#: ``config/prompts/planner.md`` and enforced by ``plan_creator.py`` (raw JSON
#: array, ``depends_on`` are indices, the last step is a DEBUGGER verification
#: step). Dependencies are a chain: parallelism inside one plan is covered by
#: the executor's own tests, this mission needs a deterministic order.
MISSION_PLAN: list[dict[str, Any]] = [
    {
        "name": "Inspecionar o projeto e listar os defeitos",
        "description": "Ler calc.py, tests/test_calc.py e pipeline.py e registar os defeitos conhecidos.",
        "agent": "ANALYZER",
        "model_key": "reasoning",
        "depends_on": [],
        "priority": "high",
        "file_scope": ["."],
        "completion_criteria": ["os defeitos conhecidos foram identificados com ficheiro"],
        "verification_commands": [],
        "risk": "low",
        "rollback": "nenhuma alteracao e feita neste passo",
        "lock_scope": "read:.",
        "allowed_tools": ["list_dir", "read_file", "search_codebase"],
        "sandboxed": False,
    },
    {
        "name": "Corrigir calc.add",
        "description": "calc.add devolve None; corrigir para devolver a soma.",
        "agent": "CODER",
        "model_key": "coder",
        "depends_on": [0],
        "priority": "high",
        "file_scope": ["calc.py"],
        "completion_criteria": ["calc.add devolve a soma correta"],
        "verification_commands": [],
        "risk": "low",
        "rollback": "git checkout -- calc.py",
        "lock_scope": "write:calc.py",
        "allowed_tools": ["read_file", "write_file"],
        "sandboxed": False,
    },
    {
        "name": "Corrigir a assercao errada",
        "description": "tests/test_calc.py asserta 6 em vez de 5; corrigir a assercao.",
        "agent": "CODER",
        "model_key": "coder",
        "depends_on": [1],
        "priority": "high",
        "file_scope": ["tests/test_calc.py"],
        "completion_criteria": ["test_add passa com 2+3==5"],
        "verification_commands": [],
        "risk": "low",
        "rollback": "git checkout -- tests/test_calc.py",
        "lock_scope": "write:tests/test_calc.py",
        "allowed_tools": ["read_file", "write_file"],
        "sandboxed": False,
    },
    {
        "name": "Quebrar o import circular",
        "description": "pipeline importa report ao nivel do modulo; mover o import para dentro da funcao.",
        "agent": "CODER",
        "model_key": "coder",
        "depends_on": [2],
        "priority": "high",
        "file_scope": ["pipeline.py"],
        "completion_criteria": ["nao existe import ao nivel do modulo entre pipeline e report"],
        "verification_commands": [],
        "risk": "medium",
        "rollback": "git checkout -- pipeline.py",
        "lock_scope": "write:pipeline.py",
        "allowed_tools": ["read_file", "write_file"],
        "sandboxed": False,
    },
    {
        "name": "Correr a suite, libertar o gate e escrever o relatorio",
        "description": "Correr pytest no projeto; se o gate PROBE_OK faltar, escreve-o; revalidar e escrever REPORT.md.",
        "agent": "CODER",
        "model_key": "coder",
        "depends_on": [3],
        "priority": "high",
        "file_scope": ["."],
        "completion_criteria": ["a suite passa e REPORT.md existe com evidencia"],
        "verification_commands": ["python -m pytest -q"],
        "risk": "low",
        "rollback": "remover REPORT.md e PROBE_OK",
        "lock_scope": "write:.",
        "allowed_tools": ["run_tests", "read_file", "write_file"],
        "sandboxed": False,
    },
    {
        "name": "Verificar o resultado final",
        "description": "Correr a suite do projeto e confirmar que fica verde.",
        "agent": "DEBUGGER",
        "model_key": "coder",
        "depends_on": [4],
        "priority": "high",
        "file_scope": ["."],
        "completion_criteria": ["a suite do projeto passa"],
        "verification_commands": ["python -m pytest -q"],
        "risk": "low",
        "rollback": "nenhuma alteracao e feita neste passo",
        "lock_scope": "read:.",
        "allowed_tools": ["run_tests", "read_file"],
        "sandboxed": False,
    },
]


def _tool_call(name: str, arguments: dict[str, Any]) -> str:
    return (
        f"{TOOL_TAG_OPEN}"
        f"{json.dumps({'name': name, 'arguments': arguments}, sort_keys=True)}"
        f"{TOOL_TAG_CLOSE}"
    )


class _ProviderError:
    """A provider-level failure (HTTP status), not a model reply."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body


class MissionScript:
    """The role-aware scripted model of the long-autonomy mission.

    The object lives in the *test* process and therefore survives the backend
    restart — only ``resumed`` is a test-side flag; every other decision reads
    the project on disk and the role that is asking, so the script cannot drift
    from the mission state or offer a tool the active contract forbids.
    """

    def __init__(self, project: Path, *, block_timeout: float = 240.0) -> None:
        self.project = project
        self.calls: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self._lock = __import__("threading").Lock()
        self._block_timeout = block_timeout
        self._gate = __import__("threading").Event()
        self._parked = __import__("threading").Event()
        # one-shot flags (they mean "already injected", so a retry or a
        # resumed turn never injects the same failure twice):
        self.tool_failure_used = False
        self.provider_failure_used = False
        self.probe_written = False
        self.report_written = False
        self.tests_run = 0
        self.coder_tests_run = 0
        # the task the script is currently serving (continuation iterations of
        # one agent loop carry no new task, only the tool result):
        self._active_task_text = ""
        # whether the current agent loop has already produced executed
        # evidence (a tool call). A loop that ends purely in text fails the
        # autonomous evidence gate, so ``_close_with_evidence`` reads this.
        self._loop_tool_used = False
        self._loop_tools_used: set[str] = set()
        # task headers whose verification already ran the suite — one suite
        # run per verification task per round (a round is a maximal run of
        # consecutive verification calls; any other role closes it).
        self._debugger_phase: set[str] | None = None
        # set by the test once the backend has been restarted:
        self.resumed = False

    # -- introspection --------------------------------------------------
    @property
    def parked(self) -> bool:
        return self._parked.is_set()

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.calls)

    def release(self) -> None:
        self._gate.set()

    # -- project state ----------------------------------------------------
    def project_state(self) -> dict[str, bool]:
        def _read(path: Path) -> str:
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                return ""

        calc = _read(self.project / "calc.py")
        test = _read(self.project / "tests" / "test_calc.py")
        pipeline = _read(self.project / "pipeline.py")
        # The circular import is a module-level ``from report import`` before
        # ``def transform`` — the fix moves it inside the function.
        pipeline_broken = "from report import" in pipeline and (
            "def transform" not in pipeline
            or pipeline.find("from report import") < pipeline.find("def transform")
        )
        return {
            # ``multiply(2, 3) == 6`` is correct and stays in the fixed file,
            # so the broken assertion is the specific ``add`` expression.
            "calc_broken": "return None" in calc,
            "test_broken": "add(2, 3) == 6" in test,
            "pipeline_broken": pipeline_broken,
            "probe_missing": not (self.project / "PROBE_OK").exists(),
            "report_missing": not (self.project / REPORT_NAME).exists(),
        }

    # -- the model ------------------------------------------------------
    def record(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.calls.append(payload)

    @staticmethod
    def _role(payload: dict[str, Any]) -> str:
        """Which agent is asking, read from the system prompt it was built with."""
        for message in payload.get("messages") or []:
            if message.get("role") == "system":
                system = str(message.get("content") or "")
                if "You are called through a plain completion endpoint" in system:
                    return "planner"
                for marker, role in (
                    ("NEXUS-ANALYZER", "analyzer"),
                    ("NEXUS-CODER", "coder"),
                    ("NEXUS-DEBUGGER", "debugger"),
                    ("NEXUS-DOCUMENTER", "documenter"),
                    ("NEXUS-REVIEWER", "reviewer"),
                ):
                    if marker in system:
                        return role
                return "other"
        return "other"

    @staticmethod
    def _task_header(payload: dict[str, Any]) -> str:
        """The task this request is about, or ``""`` if it carries none.

        Continuation iterations (after a tool result) carry no new task: their
        user turn is the tool output. The script remembers the task it is
        serving (``_active_task_text``) so a continuation answers the same
        task instead of falling into the dynamic repair chain and finishing
        the whole mission inside another step's loop.

        The anchor is the newline-prefixed ``"\\nTASK: "`` line the executor
        writes (``plan_executor._build_task_prompt``). A case-insensitive
        search is wrong here: the prompt opens with "Execute the following
        task:", whose *lowercase* tail matches first and slicks out to the
        useless string ``"task:"`` — which is exactly how every scripted
        branch was bypassed once.
        """
        for message in payload.get("messages") or []:
            if message.get("role") == "user":
                content = str(message.get("content") or "")
                idx = content.find("\nTASK: ")
                if idx != -1:
                    return content[idx + 1 :].splitlines()[0]
        return ""

    def next_reply(self, payload: dict[str, Any]) -> str | _ProviderError | None:
        """The next reply, decided from the role asking and the task it holds."""
        role = self._role(payload)
        state = self.project_state()
        header = self._task_header(payload)
        # Any role other than the verifier closes the current verification
        # round, re-arming one suite run per task header for the next round.
        if role != "debugger":
            self._debugger_phase = None
        if header:
            # The executor re-sends the full task prompt on every iteration,
            # so the header alone does not mean a new loop: only a *change* of
            # task resets the loop's evidence state.
            if header != self._active_task_text:
                self._loop_tool_used = False
                self._loop_tools_used.clear()
            self._active_task_text = header
        task = header or getattr(self, "_active_task_text", "")
        print(
            f"[script] role={role} header={header!r} task={task!r} "
            f"state={ {k: v for k, v in state.items() if v} }",
            file=sys.stderr,
            flush=True,
        )

        if role == "planner":
            # The planner is stateless: every call for the same objective must
            # produce the same plan, including the one after a restart.
            return json.dumps(MISSION_PLAN, ensure_ascii=False)

        if role == "analyzer":
            return self._close_with_evidence(task, self._analyzer_reply())

        if role == "debugger":
            # A consultation without a task (the planner's A2A probe during
            # planning) gets a text answer: a real pytest run there would burn
            # the consultation's own timeout.
            if not header:
                self._debugger_phase = None
                return (
                    "Sem evidencia de falha nos testes ainda; o plano pode "
                    "prosseguir e a verificacao corrida no passo final."
                )
            # One suite run per verification task *per round*. The engine
            # verifies every step, acts on failures, then verifies again
            # (round 2/2 repeats the same task headers), so "one run per
            # header" starves the second round and "one run per call" is a
            # repeated call the loop breaker treats as stagnation. A round is
            # a maximal run of consecutive verification calls: any other role
            # between them closes the round and re-arms each header once.
            if self._debugger_phase is None:
                self._debugger_phase = set()
            if header in self._debugger_phase:
                return (
                    "VERDICT: PASS\n"
                    "Verificacao concluida: a suite do projeto passa e o "
                    "relatorio de evidencia existe em REPORT.md."
                )
            self._debugger_phase.add(header)
            return self._close_with_evidence(
                task,
                _tool_call(
                    "run_tests",
                    {"project_path": str(self.project), "fail_fast": True},
                ),
            )

        # CODER (and any other write-capable agent the engine spawns).
        return self._close_with_evidence(task, self._coder_reply(task, state))

    def _close_with_evidence(
        self, task: str, reply: str | _ProviderError
    ) -> str | _ProviderError:
        """Never end a task loop with nothing the runtime can verify.

        A dynamically spawned fix task whose work is *already* complete (the
        replayed repairs after a restart) has no write left to offer, so its
        only honest answer is text — and a text-only loop fails the autonomous
        evidence gate, which fails the whole run. Substituting a read of a file
        the task's own scope covers gives the loop executed evidence without
        inventing work: a read cannot be a side effect, so the property under
        test (no duplicate side effects) is untouched. The substitution only
        ever replaces *text*, and only on the loop's first reply — a loop that
        already executed a tool closes with its text answer, the way a real
        model stops calling tools once the work is confirmed.
        """
        is_call = isinstance(reply, str) and reply.startswith(TOOL_TAG_OPEN)
        if is_call:
            self._loop_tool_used = True
            encoded = reply[len(TOOL_TAG_OPEN) : reply.rfind(TOOL_TAG_CLOSE)]
            try:
                call = json.loads(encoded)
            except (TypeError, ValueError):
                call = {}
            if isinstance(call, dict) and isinstance(call.get("name"), str):
                self._loop_tools_used.add(call["name"])
            return reply
        if task and isinstance(reply, str) and not self._loop_tool_used:
            self._loop_tool_used = True
            return _tool_call("read_file", {"path": "calc.py"})
        return reply

    def _analyzer_reply(self) -> str:
        # After a restart the inspection is re-executed with the flags already
        # spent, so a text-only answer would leave the task without the
        # evidence its gate demands. Re-offering a *read of a file* is safe
        # (reads are not side effects) and keeps the evidence intact — the
        # same property the write replay proves for the coder tasks. The read
        # must be a file, not a listing: the engine's own "Final Quality
        # Review" step demands *substantive* evidence, and ``list_dir`` is
        # explicitly discovery-only (``base.py:1952-1962``). Once the loop has
        # its evidence, the answer is text: an unconditional re-read is a
        # repeated call, which the loop breaker calls stagnation.
        if self.resumed and not self._loop_tool_used:
            return _tool_call("read_file", {"path": "calc.py"})
        # One real tool failure first: a directory that does not exist. The
        # loop gets the error back and simply tries the next thing.
        if not self.tool_failure_used:
            self.tool_failure_used = True
            self.failures.append(
                {"kind": "tool", "tool": "list_dir", "args": {"path": "src"}}
            )
            return _tool_call("list_dir", {"path": "src"})
        if not getattr(self, "_analyzer_listed", False):
            self._analyzer_listed = True
            return _tool_call("list_dir", {"path": "."})
        defects = missing_defects(self.project) or ["nenhum defeito aberto"]
        return (
            "Defeitos identificados no projeto: "
            + "; ".join(defects)
            + ". Nenhuma alteracao foi feita nesta analise."
        )

    def _coder_reply(self, task: str, state: dict[str, bool]) -> str | _ProviderError:
        """Answer the task the engine assigned, in that task's own scope.

        The write is offered for the task's file while the work is open, and
        again after a restart even when the file is already repaired: the
        idempotency guard turns that repeat into an ``idempotent_replay``
        instead of a second side effect, and it keeps the task's executed
        evidence intact across the restart — which is the property under test.
        A task whose work is done mid-run (no restart) ends with the answer,
        the way a real model stops calling tools once the write is confirmed.
        """
        lowered = task.lower()
        print(f"[script] coder branch for {task!r}", file=sys.stderr, flush=True)

        def _done(flag: bool) -> bool:
            # Replay one write after restart to exercise the durable
            # idempotency guard, then let the agent close the task instead of
            # asking for the same write again on every continuation turn.
            return flag and (not self.resumed or self._loop_tool_used)

        if "calc.add" in lowered or "corrigir calc" in lowered:
            if _done(not state["calc_broken"]):
                return self.final_answer()
            return _tool_call("write_file", dict(CALC_FIX_ARGS))
        if "asser" in lowered or "test_calc" in lowered:
            if _done(not state["test_broken"]):
                return self.final_answer()
            return _tool_call("write_file", dict(TEST_FIX_ARGS))
        if "import circular" in lowered or "pipeline" in lowered:
            if _done(not state["pipeline_broken"]):
                return self.final_answer()
            # Its first attempt dies at the provider: the flag is set *before*
            # the window so the test can kill the process while the task agent
            # is still blocked inside the model call.
            if not self.provider_failure_used:
                self.provider_failure_used = True
                self.failures.append(
                    {"kind": "provider", "status": 429, "step": "import circular"}
                )
                time.sleep(INJECTED_FAILURE_WINDOW_S)
                return _ProviderError(429, '{"error": "provider throttled (1x)"}')
            return _tool_call("write_file", dict(PIPELINE_FIX_ARGS))
        if "suite" in lowered or "gate" in lowered or "relatorio" in lowered:
            # The gate no code change releases: the red suite is the feedback
            # that sends the loop back for a second cycle.
            if state["probe_missing"] and not self.probe_written:
                self.probe_written = True
                return _tool_call("write_file", dict(PROBE_ARGS))
            if self.probe_written and not self.report_written:
                if self.coder_tests_run < 2:
                    self.coder_tests_run += 1
                    return _tool_call(
                        "run_tests",
                        {"project_path": str(self.project), "fail_fast": True},
                    )
                self.report_written = True
                return _tool_call(
                    "write_file",
                    {"path": REPORT_NAME, "content": self.render_report()},
                )
            if self.report_written:
                if "run_tests" not in self._loop_tools_used:
                    return _tool_call(
                        "run_tests",
                        {"project_path": str(self.project), "fail_fast": True},
                    )
                if "write_file" not in self._loop_tools_used:
                    return _tool_call(
                        "write_file",
                        {"path": REPORT_NAME, "content": self.render_report()},
                    )
                return self.final_answer()
        # A dynamically spawned fix task: repair whatever is still open.
        if state["calc_broken"]:
            return _tool_call("write_file", dict(CALC_FIX_ARGS))
        if state["test_broken"]:
            return _tool_call("write_file", dict(TEST_FIX_ARGS))
        if state["pipeline_broken"]:
            return _tool_call("write_file", dict(PIPELINE_FIX_ARGS))
        if state["probe_missing"] and not self.probe_written:
            self.probe_written = True
            return _tool_call("write_file", dict(PROBE_ARGS))
        if state["report_missing"] and not self.report_written:
            self.report_written = True
            return _tool_call(
                "write_file",
                {"path": REPORT_NAME, "content": self.render_report()},
            )
        return self.final_answer()

    def render_report(self) -> str:
        state = self.project_state()
        lines = [
            "# Relatorio da missao autonoma",
            "",
            "## Objetivo",
            MISSION_GOAL,
            "",
            "## Defeitos corrigidos",
        ]
        if not state["calc_broken"]:
            lines.append("- calc.add devolvia None; agora devolve a soma.")
        if not state["test_broken"]:
            lines.append("- tests/test_calc.py assertava 6 em vez de 5; assercao corrigida.")
        if not state["pipeline_broken"]:
            lines.append("- import circular pipeline <-> report eliminado com import local.")
        if not state["probe_missing"]:
            lines.append("- gate PROBE_OK libertado.")
        lines += [
            "",
            "## Evidencia",
            "- suite do projeto corrida com `run_tests` (project_path),",
            "  vermelha antes da libertacao do gate e verde depois;",
            "- nenhuma escrita repetida depois do restart",
            "  (guard de idempotencia na fronteira das tools);",
            "- run retomado do ultimo checkpoint valido.",
            "",
            "## Falhas injetadas e recuperadas",
        ]
        for failure in self.failures:
            lines.append(f"- {failure['kind']}: {failure}")
        return "\n".join(lines) + "\n"

    def final_answer(self) -> str:
        return (
            "Missao concluida. Defeitos corrigidos: calc.add, assercao de "
            "tests/test_calc.py e import circular pipeline/report. A suite do "
            "projeto passa com evidencia de run_tests, o gate PROBE_OK foi "
            "libertado e o relatorio ficou em REPORT.md. Nenhuma escrita foi "
            "repetida depois do restart."
        )


class _MissionProviderHandler(BaseHTTPRequestHandler):
    """The smallest possible Ollama-compatible provider."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # keep the test output readable
        pass

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        server = self.server  # type: ignore[assignment]
        script: MissionScript = server.script  # type: ignore[attr-defined]
        script.record(payload)
        if not self.path.endswith("/api/chat"):
            self._send_json({})
            return
        reply = script.next_reply(payload)
        if isinstance(reply, _ProviderError):
            self._send_json({"error": reply.body}, status=reply.status)
            return
        if reply is None:  # pragma: no cover - park path is unused by design
            self._send_json({"error": "no scripted reply left"})
            return
        body = (
            json.dumps({"message": {"role": "assistant", "content": reply}, "done": False})
            + "\n"
            + json.dumps({"done": True, "prompt_eval_count": 9, "eval_count": 13})
            + "\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.endswith("/api/tags"):
            self._send_json({"models": [{"name": "scripted:latest"}]})
            return
        self._send_json({"object": "list", "data": [{"id": "scripted:latest"}]})


def _kill_window_reached(db: Path, script: MissionScript) -> bool:
    """The kill instant: plan persisted, two defects repaired, one still open,
    and the provider failure for the third one is being held open."""
    if not script.provider_failure_used:
        return False
    runs = _run_rows(db)
    if not runs:
        return False
    run_id = str(runs[0]["run_id"])
    if len(_side_effects(db, run_id)) < 2:
        return False
    state = script.project_state()
    return not state["calc_broken"] and not state["test_broken"] and state["pipeline_broken"]


@pytest.fixture()
def mission(tmp_path: Path) -> Any:
    """A role-aware scripted provider plus the paths one mission uses."""
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    script = MissionScript(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MissionProviderHandler)
    server.script = script  # type: ignore[attr-defined]
    server.daemon_threads = True
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield {
            "script": script,
            "db": tmp_path / "nexus.db",
            "project": project,
            "logs": tmp_path / "logs",
            "ollama": f"http://127.0.0.1:{server.server_address[1]}",
        }
    finally:
        script.release()
        server.shutdown()


@pytest.mark.timeout(1800)
def test_long_autonomy_mission_survives_kill_and_completes(mission: dict[str, Any]) -> None:
    """GOAL → PLAN → EXECUTE → RECOVER → RESTART → RESUME → VERIFY → REPORT."""
    # This fixture verifies the multi-agent planner/executor recovery path.
    # The current default is PRIMARY; opt this scenario into the legacy engine
    # explicitly so its role-aware scripted planner is actually exercised.
    legacy_engine_env = {"NEXUS_PRIMARY_ENABLED": "0"}
    script: MissionScript = mission["script"]
    db: Path = mission["db"]
    project: Path = mission["project"]
    logs: Path = mission["logs"]

    build_defective_project(project)
    assert missing_defects(project), "the mission project must start defective"

    key = f"mission-{uuid.uuid4().hex[:10]}"
    session_id = f"mission-{uuid.uuid4().hex[:8]}"

    # -- process 1: plan, repair two defects, die at the provider ----------
    first = BackendUnderTest(
        _free_port(),
        db,
        logs / "mission-first.log",
        mission["ollama"],
        env_overrides=legacy_engine_env,
    )
    first.wait_ready(STARTUP_TIMEOUT_S)
    first._script = script
    run_id = ""
    try:
        token = first.token()
        assert first.get("/api/runs/resumable", token)["runs"] == []

        with ThreadPoolExecutor(max_workers=1) as pool:
            turn = pool.submit(
                first.chat,
                token=token,
                session_id=session_id,
                message=MISSION_GOAL,
                project=project,
                key=key,
                timeout=600.0,
            )
            deadline = time.time() + 300.0
            while (
                time.time() < deadline
                and not turn.done()
                and not _kill_window_reached(db, script)
            ):
                time.sleep(0.25)
            assert _kill_window_reached(db, script), (
                "the mission never reached the kill window; log tail:\n" + first.tail()
            )
            runs = _run_rows(db)
            assert len(runs) == 1, [str(r["run_id"]) for r in runs]
            run_id = str(runs[0]["run_id"])
            assert str(runs[0]["user_id"]), "durable run must retain its authenticated owner"
            assert str(runs[0]["goal"]) == MISSION_GOAL, runs[0]["goal"]
            assert str(runs[0]["session_id"]) == session_id
            plan_before = json.loads(str(runs[0]["plan_json"]) or "null")
            assert plan_before, "the plan must be durable before the kill"
            phases_before = _phases(db, run_id)
            assert phases_before, "checkpoints must exist before the kill"
            effects_before = _side_effects(db, run_id)
            assert len(effects_before) >= 2, effects_before
            keys_before = sorted(str(e["idempotency_key"]) for e in effects_before)
            first.kill()
            with contextlib.suppress(Exception):
                turn.result(timeout=90)
    finally:
        first.kill()
    assert not first.alive(), "the killed process must not exist"
    script.resumed = True
    script.release()

    # -- process 2: same database, brand new process ----------------------
    second = BackendUnderTest(
        _free_port(),
        db,
        logs / "mission-second.log",
        mission["ollama"],
        env_overrides=legacy_engine_env,
    )
    second.wait_ready(STARTUP_TIMEOUT_S)
    second._script = script
    try:
        log = second.log_text()
        assert any(
            "incomplete run at startup" in line for line in log.splitlines()
        ), f"the restart must log the incomplete run; tail:\n{second.tail()}"

        resumable = second.get("/api/runs/resumable", token)
        listed = [str(entry["run_id"]) for entry in resumable["runs"]]
        assert run_id in listed, f"the mission must be resumable: {listed}"

        resumed = second.post(f"/api/runs/{run_id}/resume", token)
        assert str(resumed["run_id"]) == run_id
        assert str(resumed["state"]) == "recovering"

        # -- continue: same goal+key must ADOPT the run, not fork a second --
        frames = second.chat(
            token=token,
            session_id=session_id,
            message=MISSION_GOAL,
            project=project,
            key=key,
            timeout=1200.0,
        )
        assert frames, "the continuation must stream something"

        rows = [row for row in _run_rows(db) if str(row["run_id"]) == run_id]
        assert rows, f"the adopted run survived: {[r['run_id'] for r in _run_rows(db)]}"
        total_runs = len(_run_rows(db))
        assert total_runs == 1, (
            "the restarted engine must adopt the durable run instead of "
            f"creating a second one (got {total_runs})"
        )
        final = rows[0]
        assert str(final["goal"]) == MISSION_GOAL, "the goal must survive the restart"
        plan_after = json.loads(str(final["plan_json"]) or "null")
        assert plan_after, "the plan must survive the restart"
        assert str(final["state"]) == "completed", (
            f"state={final['state']} stop_reason={final.get('stop_reason')}; "
            f"log tail:\n{second.tail()}"
        )

        dod = json.loads(str(final["dod_results_json"]) or "[]")
        verdicts = {str(item["requirement"]): str(item["verdict"]) for item in dod}
        expected_step_dod = {f"step:{step['name']}" for step in MISSION_PLAN}
        assert expected_step_dod <= verdicts.keys(), dod
        assert all(verdicts[requirement] == "PASS" for requirement in expected_step_dod), dod

        # -- no duplicate side effects --------------------------------------
        effects_after = _side_effects(db, run_id)
        keys_after = sorted(str(e["idempotency_key"]) for e in effects_after)
        assert len(keys_after) == len(set(keys_after)), (
            "a replayed write must never be recorded twice: " f"{keys_after}"
        )
        assert set(keys_before) <= set(keys_after), (
            f"pre-kill effects lost: {keys_before} vs {keys_after}"
        )
        assert len(keys_after) > len(keys_before), (
            "the mission must do real work after the restart: "
            f"{keys_before} vs {keys_after}"
        )

        # -- the mission itself --------------------------------------------
        assert missing_defects(project) == [], missing_defects(project)
        assert (project / REPORT_NAME).exists(), "the mission must produce REPORT.md"
        report = (project / REPORT_NAME).read_text(encoding="utf-8")
        assert "Evidencia" in report, report[:400]
        kinds = sorted(str(item["kind"]) for item in script.failures)
        assert kinds == ["provider", "tool"], script.failures
    finally:
        second.kill()
