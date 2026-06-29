"""Tests for TestGenerator and TestRunner."""
from pathlib import Path

import pytest

from backend.pipeline.test_generator import (
    CoverageReport,
    FailureType,
    TestGenerator as TG,
    TestResult as TR,
    TestRunner as TRun,
    TestSuiteReport as TSR,
)


class TestTestGenerator:
    def test_discover_functions(self) -> None:
        source = '''
def public_func(x: int) -> int:
    return x * 2

class MyClass:
    def method(self):
        pass

    def _private(self):
        pass
'''
        gen = TG()
        items = gen.discover_functions(source)
        names = {i["name"] for i in items}
        assert "public_func" in names
        assert "MyClass" in names
        assert "_private" not in names

    def test_discover_functions_syntax_error(self) -> None:
        gen = TG()
        items = gen.discover_functions("def broken(")
        assert items == []

    def test_generate_stub(self) -> None:
        gen = TG()
        functions = [
            {"name": "add", "type": "function", "line": 1, "args": ["a", "b"]},
            {"name": "Calculator", "type": "class", "line": 5, "methods": ["add", "subtract"]},
        ]
        stub = gen.generate_stub("mymod", functions)
        assert "def test_add():" in stub
        assert "class TestCalculator:" in stub
        assert "def test_add(self):" in stub
        assert "import pytest" in stub

    def test_parse_test_response_valid(self) -> None:
        gen = TG()
        response = '{"test_files": [{"path": "tests/test_a.py", "content": "def test(): pass"}]}'
        files = gen._parse_test_response(response)
        assert len(files) == 1
        assert files[0]["path"] == "tests/test_a.py"

    def test_parse_test_response_invalid(self) -> None:
        gen = TG()
        files = gen._parse_test_response("not json")
        assert files == []


class TestFailureClassification:
    def test_syntax_error(self) -> None:
        runner = TRun()
        ft = runner._classify_failure("SyntaxError", "invalid syntax")
        assert ft == FailureType.SYNTAX

    def test_dependency_error(self) -> None:
        runner = TRun()
        ft = runner._classify_failure("No module named 'missing'", "ModuleNotFoundError")
        assert ft == FailureType.DEPENDENCY

    def test_assertion(self) -> None:
        runner = TRun()
        ft = runner._classify_failure("assert 1 == 2", "AssertionError")
        assert ft == FailureType.ASSERTION

    def test_logic(self) -> None:
        runner = TRun()
        ft = runner._classify_failure("RuntimeError", "some logic error")
        assert ft == FailureType.LOGIC

    def test_timeout(self) -> None:
        runner = TRun()
        ft = runner._classify_failure("timed out after 30s", "")
        assert ft == FailureType.TIMEOUT

    def test_unknown(self) -> None:
        runner = TRun()
        ft = runner._classify_failure("something weird", "")
        assert ft == FailureType.UNKNOWN


class TestCoverageReport:
    def test_is_acceptable(self) -> None:
        report = CoverageReport(overall=95.0)
        assert report.is_acceptable()
        assert report.is_acceptable(threshold=90.0)

    def test_not_acceptable(self) -> None:
        report = CoverageReport(overall=85.0)
        assert not report.is_acceptable()
        assert not report.is_acceptable(threshold=90.0)


class TestTestSuiteReport:
    def test_success_rate(self) -> None:
        report = TSR(total=10, passed=8, failed=2)
        assert report.success_rate == 80.0

    def test_success_rate_zero(self) -> None:
        report = TSR()
        assert report.success_rate == 0.0

    def test_failures_filter(self) -> None:
        results = [
            TR(test_name="t1", status="passed"),
            TR(test_name="t2", status="failed"),
            TR(test_name="t3", status="error"),
        ]
        report = TSR(results=results)
        assert len(report.failures()) == 2


class TestTestRunner:
    def test_run_on_valid_project(self, tmp_path: Path) -> None:
        # Create a minimal project with passing tests
        project = tmp_path / "proj"
        project.mkdir()
        (project / "app.py").write_text("def add(a, b): return a + b")
        (project / "tests").mkdir()
        (project / "tests" / "test_app.py").write_text('''
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from app import add

def test_add():
    assert add(2, 3) == 5
''')
        (project / "requirements.txt").write_text("pytest\npytest-cov\n")

        runner = TRun()
        report = runner.run(project)

        assert report.total > 0
        assert report.passed > 0
        assert report.success_rate == 100.0
        assert report.coverage.overall > 0

    def test_run_on_empty_project(self, tmp_path: Path) -> None:
        project = tmp_path / "empty"
        project.mkdir()
        runner = TRun()
        report = runner.run(project)
        # Should not crash, just report zero tests
        assert report.total == 0
