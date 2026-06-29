"""CriticAgent and RegressionTester — evaluate repair quality.

CriticAgent validates patches before application.
RegressionTester ensures repairs don't introduce new failures.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from typing import Any

from .test_generator import TestRunner, TestSuiteReport

logger = logging.getLogger(__name__)


@dataclass
class PatchEvaluation:
    """Evaluation result for a proposed patch."""

    patch: str
    approved: bool = False
    syntax_valid: bool = False
    tests_pass: bool = False
    coverage_maintained: bool = False
    no_new_warnings: bool = False
    score: float = 0.0  # 0.0-1.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "syntax_valid": self.syntax_valid,
            "tests_pass": self.tests_pass,
            "coverage_maintained": self.coverage_maintained,
            "no_new_warnings": self.no_new_warnings,
            "score": self.score,
            "notes": self.notes,
        }


class CriticAgent:
    """Evaluates patch quality before application."""

    def evaluate(self, patch: str, source_path: str = "", test_report: TestSuiteReport | None = None) -> PatchEvaluation:
        """Evaluate a proposed patch.

        Args:
            patch: Unified diff patch.
            source_path: Path to the file being patched.
            test_report: Optional test results after applying patch.

        Returns:
            PatchEvaluation with approval status.
        """
        result = PatchEvaluation(patch=patch)

        # 1. Syntax check
        result.syntax_valid = self._check_syntax(patch)
        if not result.syntax_valid:
            result.notes.append("Patch contains syntax errors")

        # 2. Test results check
        if test_report:
            result.tests_pass = test_report.failed == 0 and test_report.success_rate >= 95
            if not result.tests_pass:
                result.notes.append(f"Tests failing: {test_report.failed} failures")

            # 3. Coverage check
            result.coverage_maintained = test_report.coverage.is_acceptable(threshold=85)
            if not result.coverage_maintained:
                result.notes.append(f"Coverage dropped to {test_report.coverage.overall:.1f}%")

        # Calculate score
        score = 0.0
        if result.syntax_valid:
            score += 0.4
        if result.tests_pass:
            score += 0.4
        if result.coverage_maintained:
            score += 0.2

        result.score = score
        result.approved = score >= 0.8 and result.syntax_valid

        return result

    @staticmethod
    def _check_syntax(patch: str) -> bool:
        """Check if patched code is syntactically valid."""
        lines = patch.split("\n")

        # Build candidate code from added lines + surrounding context.
        code_lines: list[str] = []
        for line in lines:
            if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
                continue
            if line.startswith("+"):
                code_lines.append(line[1:])
            elif not line.startswith("-") and not line.startswith("="):
                code_lines.append(line)

        if not code_lines:
            return True  # No code changes

        # Normalize indentation so the first non-empty line starts at column 0
        non_empty = [ln for ln in code_lines if ln.strip()]
        if non_empty:
            min_indent = min(len(ln) - len(ln.lstrip()) for ln in non_empty)
            normalized = [ln[min_indent:] if ln.strip() else ln for ln in code_lines]
            code = "\n".join(normalized)
        else:
            code = "\n".join(code_lines)

        try:
            ast.parse(code)
            return True
        except SyntaxError:
            # Last resort: try added lines alone with normalization
            added_only = [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]
            if not added_only:
                return True
            non_empty = [ln for ln in added_only if ln.strip()]
            if non_empty:
                min_indent = min(len(ln) - len(ln.lstrip()) for ln in non_empty)
                normalized = [ln[min_indent:] if ln.strip() else ln for ln in added_only]
                code = "\n".join(normalized)
            else:
                code = "\n".join(added_only)
            try:
                ast.parse(code)
                return True
            except SyntaxError:
                return False


class RegressionTester:
    """Runs regression tests after repairs."""

    def __init__(self, test_runner: TestRunner | None = None) -> None:
        self._runner = test_runner or TestRunner()

    def run_regression(
        self,
        project_path: str,
        baseline_report: TestSuiteReport | None = None,
    ) -> dict[str, Any]:
        """Run tests and compare against baseline.

        Args:
            project_path: Project directory.
            baseline_report: Previous test results for comparison.

        Returns:
            Dict with regression analysis.
        """
        current = self._runner.run(project_path)

        result: dict[str, Any] = {
            "tests_passed": current.success_rate >= 95,
            "coverage_maintained": True,
            "new_failures": [],
            "summary": {
                "total": current.total,
                "passed": current.passed,
                "failed": current.failed,
                "coverage": current.coverage.overall,
            },
        }

        if baseline_report:
            # Compare with baseline
            if current.coverage.overall < baseline_report.coverage.overall:
                result["coverage_maintained"] = False
                result["coverage_drop"] = baseline_report.coverage.overall - current.coverage.overall

            # Find newly failing tests
            baseline_failed = {r.test_name for r in baseline_report.failures()}
            current_failed = {r.test_name for r in current.failures()}
            result["new_failures"] = list(current_failed - baseline_failed)

        return result

    def check_side_effects(self, before: TestSuiteReport, after: TestSuiteReport) -> list[str]:
        """Check for side effects introduced by a repair.

        Args:
            before: Test report before repair.
            after: Test report after repair.

        Returns:
            List of side effect descriptions.
        """
        side_effects: list[str] = []

        # Tests that were passing before but fail after
        before_passing = {r.test_name for r in before.results if r.status == "passed"}
        after_failing = {r.test_name for r in after.results if r.status in ("failed", "error")}
        new_failures = before_passing & after_failing

        for test in new_failures:
            side_effects.append(f"Previously passing test now failing: {test}")

        # Coverage regression
        if after.coverage.overall < before.coverage.overall - 5:
            side_effects.append(
                f"Coverage dropped by {before.coverage.overall - after.coverage.overall:.1f}%"
            )

        return side_effects
