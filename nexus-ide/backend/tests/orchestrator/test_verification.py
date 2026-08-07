"""Regression tests for the autonomous verify/fix cycle.

These lock in the fixes for the failure mode where a run reported
``[CODER] Fix: Verify: Fix: Verify: Execute Objective: completed`` without
having done any real work.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode
from backend.orchestrator.engine import OrchestrationEngine
from backend.orchestrator.events import EventBus
from backend.orchestrator.types import OrchestrationResult, OrchestrationState
from backend.orchestrator.verification import (
    VerificationOutcome,
    _create_fix_tasks,
    _create_verification_tasks,
    _extract_inconclusive_verifications,
    _extract_verification_issues,
    _find_tasks_needing_verification,
    output_is_inconclusive,
    output_reports_issues,
    strip_cycle_prefixes,
)

# Verbatim tool-error text produced by ``AgentBase`` when a gated tool is
# reached in autonomous mode. Reproduced from logs/backend.log,
# session 27437d6cc61e4753, 2026-07-27T08:19:06Z.
BLOCKED_TOOL_OUTPUT = (
    "Tool error: Autonomous execution stopped before 'run_shell': this "
    "operation requires an explicit human approval because it may be "
    "irreversible or externally visible."
)

# Verbatim provider error from the same session, 08:14:53Z.
RATE_LIMITED_OUTPUT = (
    "Model kimi-k2.7-code failed for agent DEBUGGER: OpenAI API error 429: "
    "Rate limit exceeded: free-models-per-min."
)


def _result(**task_results) -> OrchestrationResult:
    return OrchestrationResult(
        run_id="r1",
        state=OrchestrationState.COMPLETED,
        task_results=dict(task_results),
    )


class TestStripCyclePrefixes:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Fix: Verify: Fix: Verify: Execute Objective", "Execute Objective"),
            ("Verify: Implement login", "Implement login"),
            ("Fix: Corrigir: Implement login", "Implement login"),
            ("Implement login", "Implement login"),
            ("", "Unknown"),
        ],
    )
    def test_prefixes_are_flattened(self, raw: str, expected: str) -> None:
        assert strip_cycle_prefixes(raw) == expected


class TestIssueDetection:
    def test_echoed_prompt_is_not_an_issue(self) -> None:
        """The old heuristic matched our own instructions and always fired."""
        output = (
            "Verify the output of task 'Execute Objective'. "
            "Check for: bugs, syntax errors, missing imports, logic errors, edge cases. "
            "Run any tests if available.\n"
            "I reviewed the code and everything is fine."
        )
        assert output_reports_issues(output, "Verify: Execute Objective") is False

    def test_task_name_containing_fix_is_not_an_issue(self) -> None:
        output = "Reviewed. Nothing to report."
        assert output_reports_issues(output, "Fix: Verify: Execute Objective") is False

    @pytest.mark.parametrize(
        "output",
        [
            "No errors found.",
            "No issues were found in the implementation.",
            "All tests passed.",
            "Nenhum erro encontrado.",
            "Sem problemas detectados.",
            "The code looks good and requires no changes.",
            "VERDICT: PASS",
            "Analysis complete.\nVERDICT: PASS",
        ],
    )
    def test_clean_outputs_report_no_issues(self, output: str) -> None:
        assert output_reports_issues(output) is False

    @pytest.mark.parametrize(
        "output",
        [
            "VERDICT: FAIL\nThe login handler swallows exceptions.",
            "There is a syntax error on line 42.",
            "The import of `os` is missing.",
            "Found 3 issues in the data layer.",
            "O teste falhou por causa de um erro de tipo.",
            "This does not compile.",
        ],
    )
    def test_real_findings_report_issues(self, output: str) -> None:
        assert output_reports_issues(output) is True

    def test_verdict_overrides_keywords(self) -> None:
        """An explicit PASS wins even when the prose mentions error handling."""
        output = "I checked the error handling and the missing-import guard.\nVERDICT: PASS"
        assert output_reports_issues(output) is False

    def test_empty_output_is_not_an_issue(self) -> None:
        assert output_reports_issues("") is False
        assert output_reports_issues("   \n ") is False

    def test_substring_false_positives_are_gone(self) -> None:
        """'prefix'/'suffix' used to match the bare 'fix' indicator."""
        output = "Renamed the prefix and suffix helpers for clarity."
        assert output_reports_issues(output) is False


class TestTaskNaming:
    def test_verify_task_does_not_nest_prefixes(self) -> None:
        tasks = _create_verification_tasks(
            [{"name": "Fix: Verify: Execute Objective", "output": "x"}],
            _result(),
            "s1",
        )
        assert tasks[0].name == "Verify: Execute Objective"

    def test_fix_task_does_not_nest_prefixes(self) -> None:
        tasks = _create_fix_tasks(
            [{"name": "Verify: Fix: Execute Objective", "output": "boom"}],
            [],
            "s1",
        )
        assert tasks[0].name == "Fix: Execute Objective"

    def test_repeated_rounds_stay_flat(self) -> None:
        """Four rounds must not produce 'Fix: Verify: Fix: Verify: ...'."""
        name = "Execute Objective"
        for _ in range(4):
            verify = _create_verification_tasks([{"name": name, "output": "o"}], _result(), "s1")[0]
            fix = _create_fix_tasks([{"name": verify.name, "output": "o"}], [], "s1")[0]
            name = fix.name
        assert name == "Fix: Execute Objective"

    def test_verify_prompt_requests_explicit_verdict(self) -> None:
        task = _create_verification_tasks([{"name": "Step", "output": ""}], _result(), "s1")[0]
        assert "VERDICT: PASS" in task.description
        assert "VERDICT: FAIL" in task.description


class TestExtraction:
    def test_only_completed_coder_tasks_are_verified(self) -> None:
        result = _result(
            t1={"agent": "CODER", "status": "completed", "name": "A", "output": "x"},
            t2={"agent": "CODER", "status": "failed", "name": "B", "output": "x"},
            t3={"agent": "ANALYZER", "status": "completed", "name": "C", "output": "x"},
            t4="not-a-dict",
        )
        found = _find_tasks_needing_verification(result)
        assert [f["task_id"] for f in found] == ["t1"]
        assert found[0]["origin"] == "A"

    def test_clean_verification_yields_no_issues(self) -> None:
        verify_result = _result(
            v1={
                "agent": "DEBUGGER",
                "name": "Verify: Execute Objective",
                "output": "Checked for bugs, syntax errors and missing imports. VERDICT: PASS",
            }
        )
        assert _extract_verification_issues(verify_result) == []

    def test_failing_verification_yields_issue_with_origin(self) -> None:
        verify_result = _result(
            v1={
                "agent": "DEBUGGER",
                "name": "Verify: Execute Objective",
                "output": "VERDICT: FAIL\nThe handler raises an unhandled exception.",
            }
        )
        issues = _extract_verification_issues(verify_result)
        assert len(issues) == 1
        assert issues[0]["origin"] == "Execute Objective"

    def test_non_debugger_output_is_ignored(self) -> None:
        verify_result = _result(
            v1={"agent": "CODER", "name": "X", "output": "VERDICT: FAIL\nbroken"}
        )
        assert _extract_verification_issues(verify_result) == []


class TestVerificationOutcome:
    def test_exhausted_is_not_resolved(self) -> None:
        outcome = VerificationOutcome(
            resolved=False,
            rounds_run=2,
            max_rounds=2,
            outstanding_issues=[{"name": "Verify: A"}],
        )
        assert outcome.exhausted is True
        assert "unresolved" in outcome.summary()

    def test_resolved_is_not_exhausted(self) -> None:
        outcome = VerificationOutcome(resolved=True, rounds_run=1, max_rounds=2)
        assert outcome.exhausted is False
        assert "passed" in outcome.summary()

    def test_never_run_is_neither(self) -> None:
        outcome = VerificationOutcome(max_rounds=0)
        assert outcome.exhausted is False
        assert outcome.summary() == "Verification did not run."


# ---------------------------------------------------------------------------
# Engine-level regressions
# ---------------------------------------------------------------------------


def _engine(executor_results: list[OrchestrationResult]) -> OrchestrationEngine:
    """Build an engine whose plan executor returns ``executor_results`` in order."""
    plan = ExecutionPlan.from_steps(
        "Primary plan",
        "desc",
        [TaskNode(name="Execute Objective", agent="CODER")],
        session_id="s1",
    )
    plan_creator = MagicMock()
    plan_creator.create = AsyncMock(return_value=plan)
    plan_executor = MagicMock()
    plan_executor.execute = AsyncMock(side_effect=[(r, MagicMock()) for r in executor_results])
    return OrchestrationEngine(
        llm_client=MagicMock(),
        registry={},
        event_bus=EventBus(),
        plan_creator=plan_creator,
        plan_executor=plan_executor,
    )


def _coder_result(run_id: str, name: str, output: str = "done") -> OrchestrationResult:
    return OrchestrationResult(
        run_id=run_id,
        state=OrchestrationState.COMPLETED,
        completed_tasks=1,
        task_results={
            run_id: {"agent": "CODER", "status": "completed", "name": name, "output": output}
        },
    )


def _debugger_result(run_id: str, name: str, output: str) -> OrchestrationResult:
    return OrchestrationResult(
        run_id=run_id,
        state=OrchestrationState.COMPLETED,
        completed_tasks=1,
        task_results={
            run_id: {"agent": "DEBUGGER", "status": "completed", "name": name, "output": output}
        },
    )


class TestAutonomousCycle:
    @pytest.mark.asyncio
    async def test_clean_verification_stops_after_one_round(self) -> None:
        """A passing DEBUGGER verdict must end the loop, not trigger a fix."""
        engine = _engine(
            [
                _coder_result("primary", "Execute Objective"),
                _debugger_result("verify1", "Verify: Execute Objective", "VERDICT: PASS"),
                # final review
                OrchestrationResult(run_id="review", state=OrchestrationState.COMPLETED),
            ]
        )

        result = await engine.execute_autonomous("objective", "s1", max_verify_iterations=2)

        assert result.state == OrchestrationState.COMPLETED
        assert result.verification.resolved is True
        assert result.verification.exhausted is False
        assert result.errors == []
        # primary + 1 verify + review == 3 executions, no fix round
        assert engine.plan_executor.execute.await_count == 3

    @pytest.mark.asyncio
    async def test_exhausted_loop_is_reported_not_silently_successful(self) -> None:
        """Running out of fix rounds must surface, not masquerade as success."""
        engine = _engine(
            [
                _coder_result("primary", "Execute Objective"),
                _debugger_result("v1", "Verify: Execute Objective", "VERDICT: FAIL\nbroken import"),
                _coder_result("f1", "Fix: Execute Objective"),
                _debugger_result("v2", "Verify: Execute Objective", "VERDICT: FAIL\nstill broken"),
                _coder_result("f2", "Fix: Execute Objective"),
                OrchestrationResult(run_id="review", state=OrchestrationState.COMPLETED),
            ]
        )

        result = await engine.execute_autonomous("objective", "s1", max_verify_iterations=2)

        assert result.verification.resolved is False
        assert result.verification.exhausted is True
        assert result.verification.rounds_run == 2
        assert any("unresolved" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_task_names_never_nest_across_rounds(self) -> None:
        """The 'Fix: Verify: Fix: Verify: ...' signature must not reappear."""
        engine = _engine(
            [
                _coder_result("primary", "Execute Objective"),
                _debugger_result("v1", "Verify: Execute Objective", "VERDICT: FAIL\nbroken"),
                _coder_result("f1", "Fix: Execute Objective"),
                _debugger_result("v2", "Verify: Execute Objective", "VERDICT: FAIL\nbroken"),
                _coder_result("f2", "Fix: Execute Objective"),
                OrchestrationResult(run_id="review", state=OrchestrationState.COMPLETED),
            ]
        )

        await engine.execute_autonomous("objective", "s1", max_verify_iterations=2)

        names = [
            step.name
            for call in engine.plan_executor.execute.await_args_list
            for step in call.args[0].steps
        ]
        assert not any(name.count(":") > 1 for name in names), names
        assert "Fix: Verify: Execute Objective" not in names

    @pytest.mark.asyncio
    async def test_primary_results_survive_fix_rounds(self) -> None:
        """The aggregate must keep the primary run, not be replaced by a fix."""
        engine = _engine(
            [
                _coder_result("primary", "Execute Objective", "the real work"),
                _debugger_result("v1", "Verify: Execute Objective", "VERDICT: FAIL\nbroken"),
                _coder_result("f1", "Fix: Execute Objective"),
                _debugger_result("v2", "Verify: Execute Objective", "VERDICT: PASS"),
                OrchestrationResult(run_id="review", state=OrchestrationState.COMPLETED),
            ]
        )

        result = await engine.execute_autonomous("objective", "s1", max_verify_iterations=2)

        assert "primary" in result.task_results
        assert result.task_results["primary"]["output"] == "the real work"
        # verification and fix artifacts are folded in too
        assert {"v1", "f1", "v2"} <= set(result.task_results)
        assert result.verification.resolved is True


class TestInfrastructureFailuresAreNotDefects:
    """A blocked tool or a 429 is our plumbing failing, not a bug in the code.

    Session 27437d6cc61e4753 is the reference failure:

        08:19:06  [DEBUGGER] Tool error | tool=run_shell | error=Autonomous
                  execution stopped before 'run_shell': ... human approval ...
        08:19:33  Autonomous: 1 issues found, creating fix tasks (round 1)
        08:19:50  Verify: Fix: Verify: Execute Objective
        08:20:04  Autonomous: 1 issues found, creating fix tasks (round 2)

    Nothing was ever inspected; the orchestrator spent two full rounds asking
    a CODER to "fix" a permission prompt.
    """

    def test_blocked_tool_is_not_an_issue(self) -> None:
        assert output_reports_issues(BLOCKED_TOOL_OUTPUT, "Verify: Execute Objective") is False

    def test_blocked_tool_is_inconclusive(self) -> None:
        assert output_is_inconclusive(BLOCKED_TOOL_OUTPUT, "Verify: Execute Objective") is True

    def test_rate_limit_is_not_an_issue(self) -> None:
        assert output_reports_issues(RATE_LIMITED_OUTPUT, "Verify: Execute Objective") is False

    def test_rate_limit_is_inconclusive(self) -> None:
        assert output_is_inconclusive(RATE_LIMITED_OUTPUT, "Verify: Execute Objective") is True

    def test_parser_rejection_is_not_an_issue(self) -> None:
        output = 'Failed to parse tool_call: <|tool_call_begin|> {"name": "search_codebase"}'
        assert output_reports_issues(output, "Verify: Execute Objective") is False

    def test_real_defect_alongside_infra_noise_still_counts(self) -> None:
        """One 429 must not launder a genuine finding into silence."""
        output = (
            f"{RATE_LIMITED_OUTPUT} Retrying. "
            "backend/agents/base.py has a broken import of `foo`."
        )
        assert output_reports_issues(output, "Verify: X") is True
        assert output_is_inconclusive(output, "Verify: X") is False

    def test_explicit_fail_verdict_beats_infra_noise(self) -> None:
        output = f"{BLOCKED_TOOL_OUTPUT}\nVERDICT: FAIL"
        assert output_reports_issues(output, "Verify: X") is True
        assert output_is_inconclusive(output, "Verify: X") is False

    def test_clean_output_is_not_inconclusive(self) -> None:
        assert output_is_inconclusive("VERDICT: PASS", "Verify: X") is False
        assert output_is_inconclusive("", "Verify: X") is False

    def test_extractor_routes_blocked_verification_to_inconclusive(self) -> None:
        result = _result(
            v1={
                "agent": "DEBUGGER",
                "status": "completed",
                "name": "Verify: Execute Objective",
                "output": BLOCKED_TOOL_OUTPUT,
            }
        )
        assert _extract_verification_issues(result) == []
        inconclusive = _extract_inconclusive_verifications(result)
        assert len(inconclusive) == 1
        assert inconclusive[0]["origin"] == "Execute Objective"


class TestBlockedVerificationDoesNotClaimSuccess:
    @pytest.mark.asyncio
    async def test_blocked_verification_stops_without_fix_rounds(self) -> None:
        """The exact 158s run: no fix tasks, and no false 'passed'."""
        engine = _engine(
            [
                _coder_result("primary", "Execute Objective", "listed the directory"),
                _debugger_result("v1", "Verify: Execute Objective", BLOCKED_TOOL_OUTPUT),
                OrchestrationResult(run_id="review", state=OrchestrationState.COMPLETED),
            ]
        )

        result = await engine.execute_autonomous("objective", "s1", max_verify_iterations=2)

        # Before the fix this produced "Fix: Verify: Execute Objective" and
        # then "Fix: Verify: Fix: Verify: Execute Objective".
        assert result.verification.resolved is False
        assert result.verification.outstanding_issues == []
        assert len(result.verification.inconclusive_verifications) == 1
        summary = result.verification.summary()
        assert "could NOT be performed" in summary
        assert "not a pass" in summary
