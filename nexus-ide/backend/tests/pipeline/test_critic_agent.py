"""Tests for critic_agent.py components."""
from __future__ import annotations

from unittest.mock import Mock

from backend.pipeline.critic_agent import CriticAgent, PatchEvaluation, RegressionTester
from backend.pipeline.test_generator import CoverageReport as Cov
from backend.pipeline.test_generator import TestResult as TR
from backend.pipeline.test_generator import TestSuiteReport as TSR


class TestCriticAgent:
    """Tests for CriticAgent."""

    def test_approve_valid_patch(self) -> None:
        agent = CriticAgent()
        patch = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 def hello():
-    return "hello"
+    return "hello world"
"""
        result = agent.evaluate(patch)

        assert result.syntax_valid is True
        assert result.score >= 0.4
        assert result.approved is False  # No test report, can't get full score

    def test_reject_syntax_error(self) -> None:
        agent = CriticAgent()
        patch = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 def hello():
-    return "hello"
+    return "hello world
"""
        result = agent.evaluate(patch)

        assert result.syntax_valid is False
        assert result.score < 0.8
        assert result.approved is False
        assert any("syntax" in n.lower() for n in result.notes)

    def test_evaluate_with_passing_tests(self) -> None:
        agent = CriticAgent()
        patch = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 def hello():
-    return "hello"
+    return "hello world"
"""
        report = TSR(
            total=10,
            passed=10,
            failed=0,
            coverage=Cov(overall=90.0),
        )
        result = agent.evaluate(patch, test_report=report)

        assert result.tests_pass is True
        assert result.coverage_maintained is True
        assert result.score >= 0.8
        assert result.approved is True

    def test_evaluate_with_failing_tests(self) -> None:
        agent = CriticAgent()
        patch = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 def hello():
-    return "hello"
+    return "hello world"
"""
        report = TSR(
            total=10,
            passed=5,
            failed=5,
            coverage=Cov(overall=90.0),
        )
        result = agent.evaluate(patch, test_report=report)

        assert result.tests_pass is False
        assert result.approved is False

    def test_evaluate_coverage_drop(self) -> None:
        agent = CriticAgent()
        patch = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 def hello():
-    return "hello"
+    return "hello world"
"""
        report = TSR(
            total=10,
            passed=10,
            failed=0,
            coverage=Cov(overall=80.0),  # Below 85% threshold
        )
        result = agent.evaluate(patch, test_report=report)

        assert result.coverage_maintained is False
        assert any("coverage" in n.lower() for n in result.notes)

    def test_empty_patch_is_valid(self) -> None:
        agent = CriticAgent()
        result = agent.evaluate("")
        assert result.syntax_valid is True

    def test_patch_with_no_plus_lines(self) -> None:
        agent = CriticAgent()
        patch = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 def hello():
-    return "hello"
+    return "hello"
"""
        result = agent.evaluate(patch)
        assert result.syntax_valid is True  # Should still be valid

    def test_to_dict(self) -> None:
        result = PatchEvaluation(patch="test", approved=True, score=1.0)
        d = result.to_dict()
        assert d["approved"] is True
        assert d["score"] == 1.0


class TestRegressionTester:
    """Tests for RegressionTester."""

    def test_run_regression_no_baseline(self, monkeypatch) -> None:
        runner = Mock()
        runner.run.return_value = TSR(
            total=5,
            passed=5,
            failed=0,
            coverage=Cov(overall=90.0),
        )
        tester = RegressionTester(test_runner=runner)
        result = tester.run_regression("/project")

        assert result["tests_passed"] is True
        assert result["coverage_maintained"] is True
        assert result["new_failures"] == []

    def test_run_regression_coverage_drop(self, monkeypatch) -> None:
        runner = Mock()
        runner.run.return_value = TSR(
            total=5,
            passed=5,
            failed=0,
            coverage=Cov(overall=80.0),
        )
        tester = RegressionTester(test_runner=runner)
        baseline = TSR(
            total=5,
            passed=5,
            failed=0,
            coverage=Cov(overall=90.0),
        )
        result = tester.run_regression("/project", baseline_report=baseline)

        assert result["coverage_maintained"] is False
        assert result["coverage_drop"] == 10.0

    def test_run_regression_new_failures(self, monkeypatch) -> None:
        runner = Mock()
        fail_result = TR(
            test_name="test_new_failure",
            status="failed",
            duration=10.0,
        )
        runner.run.return_value = TSR(
            total=5,
            passed=3,
            failed=2,
            coverage=Cov(overall=90.0),
            results=[
                TR(test_name="test_pass", status="passed", duration=1.0),
                fail_result,
            ],
        )
        tester = RegressionTester(test_runner=runner)

        baseline = TSR(
            total=5,
            passed=5,
            failed=0,
            coverage=Cov(overall=90.0),
        )
        result = tester.run_regression("/project", baseline_report=baseline)

        assert "test_new_failure" in result["new_failures"]

    def test_check_side_effects_new_failure(self) -> None:
        before = TSR(
            total=3,
            passed=3,
            failed=0,
            coverage=Cov(overall=90.0),
            results=[
                TR(test_name="test_a", status="passed", duration=1.0),
                TR(test_name="test_b", status="passed", duration=1.0),
            ],
        )
        after = TSR(
            total=3,
            passed=2,
            failed=1,
            coverage=Cov(overall=90.0),
            results=[
                TR(test_name="test_a", status="passed", duration=1.0),
                TR(test_name="test_b", status="failed", duration=1.0),
            ],
        )

        tester = RegressionTester()
        effects = tester.check_side_effects(before, after)

        assert len(effects) == 1
        assert "test_b" in effects[0]

    def test_check_side_effects_coverage_drop(self) -> None:
        before = TSR(
            total=3,
            passed=3,
            failed=0,
            coverage=Cov(overall=90.0),
            results=[],
        )
        after = TSR(
            total=3,
            passed=3,
            failed=0,
            coverage=Cov(overall=80.0),  # 10% drop
            results=[],
        )

        tester = RegressionTester()
        effects = tester.check_side_effects(before, after)

        assert len(effects) == 1
        assert "10.0%" in effects[0]

    def test_check_side_effects_no_regression(self) -> None:
        before = TSR(
            total=3,
            passed=3,
            failed=0,
            coverage=Cov(overall=90.0),
            results=[],
        )
        after = TSR(
            total=3,
            passed=3,
            failed=0,
            coverage=Cov(overall=91.0),
            results=[],
        )

        tester = RegressionTester()
        effects = tester.check_side_effects(before, after)

        assert effects == []
