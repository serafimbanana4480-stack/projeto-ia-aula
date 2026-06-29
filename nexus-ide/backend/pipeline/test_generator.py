"""TestGenerator and TestRunner — automatic test generation and execution.

Generates pytest unit tests from source code, executes them in sandbox,
and classifies failures for the repair pipeline.
"""
from __future__ import annotations

import ast
import json
import logging
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from backend.config.settings import get_settings
from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class FailureType(str, Enum):
    """Classification of test failures."""

    SYNTAX = "syntax"  # Parse / compile errors
    LOGIC = "logic"  # Wrong implementation
    ASSERTION = "assertion"  # Test expectation mismatch
    DEPENDENCY = "dependency"  # Missing imports / packages
    TIMEOUT = "timeout"  # Test took too long
    UNKNOWN = "unknown"  # Could not classify


@dataclass
class TestResult:
    """Result of a single test execution."""

    test_name: str
    status: str  # passed, failed, error, skipped
    duration: float = 0.0
    failure_type: FailureType = FailureType.UNKNOWN
    error_message: str = ""
    traceback: str = ""
    source_context: str = ""  # Relevant source lines


@dataclass
class CoverageReport:
    """Coverage metrics for a test run."""

    overall: float = 0.0
    by_module: dict[str, float] = field(default_factory=dict)
    missing_lines: dict[str, list[int]] = field(default_factory=dict)

    def is_acceptable(self, threshold: float = 90.0) -> bool:
        return self.overall >= threshold


@dataclass
class TestSuiteReport:
    """Complete test execution report."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration: float = 0.0
    results: list[TestResult] = field(default_factory=list)
    coverage: CoverageReport = field(default_factory=CoverageReport)
    summary: str = ""

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100

    def failures(self) -> list[TestResult]:
        return [r for r in self.results if r.status in ("failed", "error")]


class TestGenerator:
    """Generates pytest unit tests from Python source code."""

    SYSTEM_PROMPT = """You are a senior QA engineer writing pytest unit tests.

RULES:
1. Every public function and method must have at least one test
2. Use pytest fixtures for shared setup
3. Mock external dependencies (HTTP, DB, filesystem)
4. Test edge cases: empty inputs, None, large values
5. Use parametrized tests for multiple similar cases
6. Follow Arrange-Act-Assert pattern
7. Include type hints in test functions

OUTPUT FORMAT — return ONLY valid JSON:
{
  "test_files": [
    {
      "path": "tests/test_module.py",
      "content": "complete test file content",
      "target_module": "module_name"
    }
  ]
}"""

    def __init__(self, ollama_client: OllamaClient | None = None) -> None:
        self._client = ollama_client or OllamaClient(get_settings().ollama_host)

    def discover_functions(self, source_code: str) -> list[dict[str, Any]]:
        """Discover public functions and classes in source code via AST.

        Args:
            source_code: Python source string.

        Returns:
            List of dicts with name, type (function/class), line number.
        """
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return []

        items: list[dict[str, Any]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip private functions
                if not node.name.startswith("_"):
                    items.append({
                        "name": node.name,
                        "type": "function",
                        "line": node.lineno,
                        "args": [arg.arg for arg in node.args.args if arg.arg != "self"],
                    })
            elif isinstance(node, ast.ClassDef):
                if not node.name.startswith("_"):
                    items.append({
                        "name": node.name,
                        "type": "class",
                        "line": node.lineno,
                        "methods": [
                            n.name for n in node.body
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and not n.name.startswith("_")
                        ],
                    })
        return items

    def generate_stub(self, module_name: str, functions: list[dict[str, Any]]) -> str:
        """Generate a basic pytest stub from discovered functions.

        Args:
            module_name: Name of the module under test.
            functions: Output from discover_functions().

        Returns:
            Python test file content.
        """
        lines = [
            f'"""Tests for {module_name}."""',
            "import pytest",
            f"from {module_name} import *\n",
        ]

        for item in functions:
            if item["type"] == "function":
                lines.append(f"def test_{item['name']}():")
                lines.append(f'    """Test {item["name"]} with basic inputs."""')
                lines.append("    # Arrange")
                lines.append("    # TODO: setup inputs based on parameter types")
                lines.append("    # Act")
                lines.append(f"    result = {item['name']}(...)")
                lines.append("    # Assert")
                lines.append("    assert result is not None")
                lines.append("")
            elif item["type"] == "class":
                class_name = item["name"]
                lines.append(f"class Test{class_name}:")
                lines.append(f'    """Tests for {class_name}."""')
                for method in item.get("methods", []):
                    lines.append(f"    def test_{method}(self):")
                    lines.append(f'        """Test {class_name}.{method}."""')
                    lines.append("        pass")
                    lines.append("")
                lines.append("")

        return "\n".join(lines)

    async def generate_with_llm(
        self,
        module_name: str,
        source_code: str,
        requirements: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Generate tests using LLM for richer test cases.

        Args:
            module_name: Module under test.
            source_code: Source to generate tests for.
            requirements: Optional acceptance criteria.

        Returns:
            List of dicts with path and content.
        """
        req_text = "\n".join(requirements) if requirements else "Cover all public functions."
        prompt = f"""Generate pytest unit tests for this module:

MODULE: {module_name}

SOURCE CODE:
```python
{source_code[:6000]}
```

ACCEPTANCE CRITERIA:
{req_text}

Return ONLY valid JSON matching the output format."""

        try:
            response = await self._client.chat(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model="llama3.2",
                temperature=0.3,
            )
            content = response.content if hasattr(response, "content") else str(response)
            return self._parse_test_response(content)
        except Exception as exc:
            logger.warning("LLM test generation failed: %s", exc)
            # Fallback to stub
            functions = self.discover_functions(source_code)
            return [{
                "path": f"tests/test_{module_name.replace('.', '_')}.py",
                "content": self.generate_stub(module_name, functions),
                "target_module": module_name,
            }]

    def _parse_test_response(self, content: str) -> list[dict[str, str]]:
        """Parse LLM JSON response into test file dicts."""
        json_str = content
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_str)
            return data.get("test_files", [])
        except json.JSONDecodeError:
            logger.warning("Failed to parse test JSON")
            return []


class TestRunner:
    """Executes pytest in sandbox and produces structured reports."""

    def __init__(self, sandbox_work_dir: Path | None = None) -> None:
        self.sandbox_work_dir = sandbox_work_dir or Path(tempfile.gettempdir()) / "nexus_tests"

    def run(
        self,
        project_path: Path,
        extra_deps: list[str] | None = None,
    ) -> TestSuiteReport:
        """Run pytest with coverage in the given project directory.

        Args:
            project_path: Directory containing the code and tests.
            extra_deps: Additional packages to install before testing.

        Returns:
            TestSuiteReport with results and coverage.
        """
        project_path = Path(project_path)
        report = TestSuiteReport()

        # Install dependencies
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            self._pip_install(project_path, "-r", str(req_file))
        if extra_deps:
            self._pip_install(project_path, *extra_deps)

        # Ensure pytest and coverage are available
        self._pip_install(project_path, "pytest", "pytest-cov", "pytest-asyncio")

        # Run pytest with JUnit XML output and coverage
        junit_path = project_path / ".pytest_results.xml"
        cov_xml = project_path / ".coverage.xml"

        cmd = [
            "python", "-m", "pytest",
            "-v",
            "--tb=long",
            f"--junitxml={junit_path}",
            "--cov=.",
            f"--cov-report=xml:{cov_xml}",
            "--cov-report=term",
        ]

        start = __import__("time").time()
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        report.duration = __import__("time").time() - start

        logger.info("pytest exit code: %d", result.returncode)

        # Parse JUnit XML for individual test results
        if junit_path.exists():
            report.results = self._parse_junit(junit_path, project_path)
            junit_path.unlink(missing_ok=True)

        # Parse coverage
        if cov_xml.exists():
            report.coverage = self._parse_coverage(cov_xml)
            cov_xml.unlink(missing_ok=True)

        # Summary stats
        report.total = len(report.results)
        report.passed = sum(1 for r in report.results if r.status == "passed")
        report.failed = sum(1 for r in report.results if r.status in ("failed", "error"))
        report.skipped = sum(1 for r in report.results if r.status == "skipped")
        report.summary = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout

        return report

    def _pip_install(self, cwd: Path, *packages: str) -> None:
        """Install Python packages in the project environment."""
        cmd = ["python", "-m", "pip", "install", *packages]
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            logger.warning("pip install warning: %s", result.stderr[:500])

    def _parse_junit(self, path: Path, project_path: Path) -> list[TestResult]:
        """Parse JUnit XML into TestResult objects."""
        results: list[TestResult] = []
        try:
            tree = ET.parse(path)
            root = tree.getroot()

            # Handle both flat and nested testcase structures
            for testcase in root.iter("testcase"):
                name = testcase.get("name", "unknown")
                classname = testcase.get("classname", "")
                duration = float(testcase.get("time", "0"))

                failure = testcase.find("failure")
                error = testcase.find("error")
                skipped = testcase.find("skipped")

                if failure is not None:
                    msg = failure.get("message", "")
                    tb = failure.text or ""
                    results.append(TestResult(
                        test_name=f"{classname}.{name}" if classname else name,
                        status="failed",
                        duration=duration,
                        failure_type=self._classify_failure(msg, tb),
                        error_message=msg,
                        traceback=tb,
                    ))
                elif error is not None:
                    msg = error.get("message", "")
                    tb = error.text or ""
                    results.append(TestResult(
                        test_name=f"{classname}.{name}" if classname else name,
                        status="error",
                        duration=duration,
                        failure_type=self._classify_failure(msg, tb),
                        error_message=msg,
                        traceback=tb,
                    ))
                elif skipped is not None:
                    results.append(TestResult(
                        test_name=f"{classname}.{name}" if classname else name,
                        status="skipped",
                        duration=duration,
                    ))
                else:
                    results.append(TestResult(
                        test_name=f"{classname}.{name}" if classname else name,
                        status="passed",
                        duration=duration,
                    ))
        except ET.ParseError as exc:
            logger.error("Failed to parse JUnit XML: %s", exc)

        return results

    def _parse_coverage(self, path: Path) -> CoverageReport:
        """Parse coverage XML report."""
        report = CoverageReport()
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            # Coverage.py XML format
            report.overall = float(root.get("line-rate", "0")) * 100

            for package in root.iter("package"):
                for cls in package.iter("class"):
                    filename = cls.get("filename", "unknown")
                    rate = float(cls.get("line-rate", "0")) * 100
                    report.by_module[filename] = rate

                    missing: list[int] = []
                    for line in cls.iter("line"):
                        if line.get("hits") == "0":
                            missing.append(int(line.get("number", 0)))
                    if missing:
                        report.missing_lines[filename] = missing

        except ET.ParseError as exc:
            logger.error("Failed to parse coverage XML: %s", exc)

        return report

    @staticmethod
    def _classify_failure(message: str, traceback: str) -> FailureType:
        """Classify a test failure by type."""
        text = (message + " " + traceback).lower()

        if "syntax" in text or "indentation" in text or "unexpected token" in text:
            return FailureType.SYNTAX
        if "modulenotfound" in text or "importerror" in text or "no module named" in text:
            return FailureType.DEPENDENCY
        if "assert" in text or "assertion" in text:
            return FailureType.ASSERTION
        if "timeout" in text or "timed out" in text:
            return FailureType.TIMEOUT
        if "error" in text and "assert" not in text:
            return FailureType.LOGIC

        return FailureType.UNKNOWN
