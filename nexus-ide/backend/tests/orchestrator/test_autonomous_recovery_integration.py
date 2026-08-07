"""End-to-end test of the dashboard's automatic (autonomous) mode.

Reproduces the 2026-08-01 incident: during an autonomous run a CODER agent
read a hallucinated path (``backend/app/main.py``) and the run was reported
as "Execução Autónoma Falhou" even though the agent recovered. The engine
must now treat an error followed by successful tool work as *recovered* and
complete the run, while an error with no later success must still fail it.

The LLM is scripted — no provider, local or remote, is contacted.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode
from backend.orchestrator.engine import OrchestrationEngine, OrchestrationState
from backend.orchestrator.events import EventBus

SESSION = "it-autonomous-recovery"


class _ScriptedAgent:
    """Minimal agent: ``run`` replays a scripted ReAct output stream."""

    def __init__(self, name: str, script: str) -> None:
        self.name = name
        self._script = script

    async def run(self, request: Any):  # noqa: ANN001 — matches AgentBase duck type
        for token in self._script.split("\n"):
            yield token + "\n"


class _FixedPlanCreator:
    """Plan creator that returns a pre-built plan (no LLM involved)."""

    def __init__(self, steps: list[TaskNode]) -> None:
        self._steps = steps

    async def create(self, objective: str, session_id: str, **_: Any) -> ExecutionPlan:
        return ExecutionPlan.from_steps(
            title="Auto-test plan",
            description=objective,
            steps=self._steps,
            session_id=session_id,
        )


# The original failure: hallucinated path, error, then the agent corrects
# itself (list_dir + read succeed) and finishes with a real answer.
_RECOVERED_CODER_OUTPUT = """<event>tool_call|read_file_absolute|{"path": "C:\\\\proj\\\\backend\\\\app\\\\main.py"}</event>
<event>tool_error|read_file_absolute|File not found: C:\\proj\\backend\\app\\main.py</event>
<event>tool_call|list_dir_absolute|{"path": "C:\\\\proj\\\\backend"}</event>
<event>tool_result|list_dir_absolute|["orchestrator/", "main.py"]</event>
<event>tool_result|read_file_absolute|# real entrypoint</event>
<event>answer</event>
Implementação concluída após corrigir o caminho para orchestrator/main.py.
"""

_FATAL_CODER_OUTPUT = """<event>tool_call|read_file_absolute|{"path": "C:\\\\proj\\\\backend\\\\app\\\\main.py"}</event>
<event>tool_error|read_file_absolute|File not found: C:\\proj\\backend\\app\\main.py</event>
<event>answer</event>
Não consegui localizar o ficheiro.
"""

_CLEAN_REVIEW_OUTPUT = """Revisão final: tudo verificado.
VERDICT: PASS
"""


def _engine(steps: list[TaskNode], agents: dict[str, Any]) -> OrchestrationEngine:
    return OrchestrationEngine(
        llm_client=object(),
        registry=agents,
        event_bus=EventBus(),
        plan_creator=_FixedPlanCreator(steps),
    )


@pytest.mark.asyncio
async def test_autonomous_run_survives_recovered_tool_error() -> None:
    """The exact incident scenario must now complete, not fail."""
    steps = [
        TaskNode(
            name="Implement: autoauditoria",
            description="Implement the audit module",
            agent="CODER",
        ),
    ]
    engine = _engine(
        steps,
        {
            "CODER": _ScriptedAgent("CODER", _RECOVERED_CODER_OUTPUT),
            "DEBUGGER": _ScriptedAgent("DEBUGGER", _CLEAN_REVIEW_OUTPUT),
            "ANALYZER": _ScriptedAgent("ANALYZER", _CLEAN_REVIEW_OUTPUT),
        },
    )

    result = await engine.execute_autonomous(
        objective="Autoauditoria profunda",
        session_id=SESSION,
        project_path=".",
        max_verify_iterations=0,
    )

    assert result.state == OrchestrationState.COMPLETED
    assert result.failed_tasks == 0
    assert result.completed_tasks >= 1

    coder_artifact = next(
        a for a in result.task_results.values() if a.get("agent") == "CODER"
    )
    assert coder_artifact["status"] == "completed"
    assert coder_artifact["recovered_tool_errors"], (
        "the recovered 'File not found' must be recorded for visibility"
    )
    assert not result.errors, f"recovered errors must not surface as run errors: {result.errors}"


@pytest.mark.asyncio
async def test_autonomous_run_still_fails_on_unrecovered_tool_error() -> None:
    """An error the agent never recovered from must remain a failed run."""
    steps = [
        TaskNode(
            name="Implement: autoauditoria",
            description="Implement the audit module",
            agent="CODER",
        ),
    ]
    engine = _engine(
        steps,
        {
            "CODER": _ScriptedAgent("CODER", _FATAL_CODER_OUTPUT),
            "DEBUGGER": _ScriptedAgent("DEBUGGER", _CLEAN_REVIEW_OUTPUT),
            "ANALYZER": _ScriptedAgent("ANALYZER", _CLEAN_REVIEW_OUTPUT),
        },
    )

    result = await engine.execute_autonomous(
        objective="Autoauditoria profunda",
        session_id=f"{SESSION}-fatal",
        project_path=".",
        max_verify_iterations=0,
    )

    assert result.state == OrchestrationState.FAILED
    assert result.failed_tasks == 1
    assert any("File not found" in err for err in result.errors)


_INCOMPLETE_CODER_OUTPUT = """<event>tool_result|list_dir_absolute|["backend/"]</event>
<event>warning|Reached maximum iterations (10) — task NOT completed</event>
<event>answer</event>
[TAREFA NÃO CONCLUÍDA] O agente atingiu o limite de 10 passos sem produzir uma resposta final.
"""


@pytest.mark.asyncio
async def test_autonomous_run_fails_when_agent_reports_incompletion() -> None:
    """An agent that ends with "[TAREFA NÃO CONCLUÍDA]" must NOT be reported
    as a completed task — the dashboard used to print "Tarefa concluída"
    directly under the "task NOT completed" warning."""
    steps = [
        TaskNode(
            name="Analyse: ambiente",
            description="Analyse the environment deeply",
            agent="ANALYZER",
        ),
    ]
    engine = _engine(
        steps,
        {
            "ANALYZER": _ScriptedAgent("ANALYZER", _INCOMPLETE_CODER_OUTPUT),
            "CODER": _ScriptedAgent("CODER", _RECOVERED_CODER_OUTPUT),
            "DEBUGGER": _ScriptedAgent("DEBUGGER", _CLEAN_REVIEW_OUTPUT),
        },
    )

    result = await engine.execute_autonomous(
        objective="Analisa profundamente o ambiente",
        session_id=f"{SESSION}-incomplete",
        project_path=".",
        max_verify_iterations=0,
    )

    assert result.state == OrchestrationState.FAILED
    assert result.failed_tasks == 1
    assert result.completed_tasks == 0
    artifact = next(iter(result.task_results.values()))
    assert artifact["status"] == "failed"
    assert artifact["incomplete"] is True
    assert any("not completed" in err for err in result.errors)


@pytest.mark.asyncio
async def test_executor_honours_agent_runtime_evidence_verdict() -> None:
    steps = [
        TaskNode(
            name="Analyse: environment",
            description="Inspect substantive code",
            agent="ANALYZER",
        ),
    ]
    shallow_agent = _ScriptedAgent(
        "ANALYZER",
        '<event>tool_result|list_dir|["backend/"]</event>\nLooks complete.',
    )
    shallow_agent._last_run_success = False
    engine = _engine(
        steps,
        {
            "ANALYZER": shallow_agent,
            "CODER": _ScriptedAgent("CODER", _RECOVERED_CODER_OUTPUT),
            "DEBUGGER": _ScriptedAgent("DEBUGGER", _CLEAN_REVIEW_OUTPUT),
        },
    )

    result = await engine.execute_autonomous(
        objective="Analyse the environment",
        session_id=f"{SESSION}-evidence-verdict",
        project_path=".",
        max_verify_iterations=0,
    )

    assert result.state == OrchestrationState.FAILED
    assert result.completed_tasks == 0
    assert any("evidence gate" in error for error in result.errors)


_FAILING_VERIFICATION_OUTPUT = """Verifiquei o código e encontrei problemas reais.
VERDICT: FAIL
- erro de lógica no parser
"""


@pytest.mark.asyncio
async def test_exhausted_verification_marks_run_failed() -> None:
    """Running out of fix rounds with unresolved issues is "gave up", not
    success. The summary must say the run FAILED, not ✅ Concluída."""
    steps = [
        TaskNode(
            name="Implement: parser",
            description="Implement the parser",
            agent="CODER",
        ),
    ]
    engine = _engine(
        steps,
        {
            "CODER": _ScriptedAgent("CODER", _RECOVERED_CODER_OUTPUT),
            "DEBUGGER": _ScriptedAgent("DEBUGGER", _FAILING_VERIFICATION_OUTPUT),
            "ANALYZER": _ScriptedAgent("ANALYZER", _CLEAN_REVIEW_OUTPUT),
        },
    )

    result = await engine.execute_autonomous(
        objective="Implementa e verifica o parser",
        session_id=f"{SESSION}-exhausted",
        project_path=".",
        max_verify_iterations=1,
    )

    assert result.state == OrchestrationState.FAILED
    assert any("Verification exhausted" in err for err in result.errors)


class TestOutputReportsIncompletion:
    def test_detects_tarefa_nao_concluida(self) -> None:
        from backend.orchestrator.plan_executor import output_reports_incompletion

        assert output_reports_incompletion("[TAREFA NÃO CONCLUÍDA] limite atingido")
        assert output_reports_incompletion("Reached maximum iterations (10) — task NOT completed")

    def test_clean_output_is_complete(self) -> None:
        from backend.orchestrator.plan_executor import output_reports_incompletion

        assert output_reports_incompletion("Tarefa concluída com sucesso.") is None
        assert output_reports_incompletion("") is None
