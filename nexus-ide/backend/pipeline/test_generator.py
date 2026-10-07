"""TestGenerator and TestRunner — automatic test generation and execution.

Generates pytest unit tests from Python source code, executes them in a
*contained* directory, and classifies failures for the repair pipeline.

Security contract (audit P0-1 — unauthenticated RCE via ``POST /api/tests/run``)
--------------------------------------------------------------------------
Running pytest is equivalent to running arbitrary Python: pytest imports
``conftest.py`` files and collects test modules, so a directory on disk is an
arbitrary-code-execution primitive.  ``TestRunner`` therefore refuses to run
unless **all** of the following hold:

1. ``project_path`` resolves (following symlinks) inside one of the allow-listed
   roots — traversal (``../``) and symlink escapes are rejected.
2. The target is an existing directory, not a symlink pointing outside.
3. Every requested dependency is an exact-pinned (``name[extras]==version``)
   package present in the allow-list.  A bare name, a version range, a VCS/URL
   reference and anything pip would read as a flag are all rejected.
4. Every subprocess runs with a mandatory ``timeout=``; the child is killed and
   the partial report returned on expiry.
5. ``requirements.txt`` is never auto-installed unless the operator explicitly
   enables it *and* the containment check above passed.

Callers must additionally require authentication plus an admin role; see
``backend/orchestrator/routes/tests.py``.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from backend.config.settings import get_settings
from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

#: Repo root — the default allow-listed root for test runs.  Any extra roots
#: come from ``NEXUS_TEST_RUN_ALLOWED_ROOTS`` (os.pathsep separated).
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Packages ``TestRunner`` will install if they are missing.  Names only — the
#: version is whatever the environment already pins, so the runner never
#: downgrades a working venv.  Every other dependency must be requested through
#: ``extra_deps`` with an exact version and must appear in the allow-list.
_RUNNER_DEPS = ("pytest", "pytest-cov", "pytest-asyncio")

#: Default per-request dependency allow-list.  Deliberately tiny: it covers the
#: libraries the IDE's own generated tests need and nothing else.  Operators add
#: more through ``NEXUS_TEST_RUN_ALLOWED_DEPS`` (comma separated package names).
_DEFAULT_ALLOWED_DEP_NAMES = (
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "pytest-mock",
    "pytest-timeout",
    "httpx",
    "anyio",
    "freezegun",
    "hypothesis",
    "responses",
)

#: Exact-pinned requirement, optionally with extras: ``name==1.2.3``,
#: ``name[extra1,extra2]==1.2.3``.  A bare name, a range (``>=``/``~=``), an
#: extras-only spec or a VCS/URL reference is deliberately NOT accepted.
_DEP_SPEC_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[A-Za-z0-9._,-]+\])?"
    r"=="
    r"(?P<version>[0-9][0-9A-Za-z.*+!-]*)$"
)

#: Names of the packages the runner is allowed to install on its own.
_BUILTIN_DEPS = frozenset(_RUNNER_DEPS)


class TestRunSecurityError(ValueError):
    """Base class for containment/allow-list rejections (HTTP 400)."""

    code = "test_run_rejected"


class PathNotAllowedError(TestRunSecurityError):
    """``project_path`` resolved outside every allow-listed root."""

    code = "path_not_allowed"


class DependencyNotAllowedError(TestRunSecurityError):
    """A requested dependency is not an exact-pinned, allow-listed package."""

    code = "dependency_not_allowed"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r — using default %d", name, raw, default)
        return default
    return max(minimum, value)


def _default_allowed_roots() -> tuple[Path, ...]:
    """Roots a test run may target.

    The repository root is always allowed (that is the project the IDE ships
    and the one its own CI-style test command targets).  Operators add more
    with ``NEXUS_TEST_RUN_ALLOWED_ROOTS``; separators follow ``os.pathsep``.
    """
    roots: list[Path] = [_REPO_ROOT]
    extra = os.environ.get("NEXUS_TEST_RUN_ALLOWED_ROOTS", "").strip()
    if extra:
        for part in extra.split(os.pathsep):
            candidate = part.strip()
            if not candidate:
                continue
            path = Path(candidate)
            try:
                roots.append(path.expanduser().resolve())
            except OSError as exc:  # pragma: no cover - unreadable operator input
                logger.warning("Ignoring unusable allowed root %s: %s", candidate, exc)
    seen: dict[str, Path] = {}
    for root in roots:
        seen.setdefault(str(root).lower() if os.name == "nt" else str(root), root)
    return tuple(seen.values())


def _default_allowed_dep_names() -> frozenset[str]:
    """Package names accepted in ``extra_deps`` (env extends the default set)."""
    names = set(_DEFAULT_ALLOWED_DEP_NAMES) | _BUILTIN_DEPS
    extra = os.environ.get("NEXUS_TEST_RUN_ALLOWED_DEPS", "").strip()
    if extra:
        for part in extra.split(","):
            candidate = part.strip()
            if candidate:
                names.add(candidate)
    return frozenset(n.lower() for n in names)


def resolve_contained_path(
    project_path: str | os.PathLike[str],
    allowed_roots: Sequence[Path] | None = None,
) -> Path:
    """Resolve *project_path* and prove it lives inside an allow-listed root.

    ``Path.resolve()`` follows symlinks, so a symlink that points outside the
    allow-list is caught by the containment check on the *resolved* path.  The
    check is ``resolved.is_relative_to(root)`` performed per root, which is
    segment-based and therefore immune to ``..`` and to prefix confusion such as
    ``/repo-secrets`` matching a ``/repo`` root.

    Raises:
        PathNotAllowedError: path escapes every root, is not a directory, or the
            caller asked for the filesystem root / a drive root.
    """
    roots = tuple(allowed_roots) if allowed_roots is not None else _default_allowed_roots()
    raw = Path(project_path).expanduser()
    try:
        resolved = raw.resolve()
    except OSError as exc:
        raise PathNotAllowedError(f"project_path could not be resolved: {exc}") from exc

    if not resolved.is_dir():
        raise PathNotAllowedError("project_path must be an existing directory")
    if resolved == Path(resolved.anchor) or resolved.parent == resolved:
        raise PathNotAllowedError("project_path must not be a filesystem root")

    for root in roots:
        try:
            root_resolved = root.resolve()
        except OSError:  # pragma: no cover - unreadable operator input
            continue
        if resolved.is_relative_to(root_resolved) and resolved != root_resolved:
            return resolved
    raise PathNotAllowedError(
        "project_path is outside every allowed test-run root. "
        f"Allowed roots: {[str(r) for r in roots]}"
    )


def validate_dependency_specs(
    specs: Iterable[str],
    allowed_names: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Validate requested packages against the exact-pin + name allow-list.

    An allow-list of *exact-pinned* names is the safe minimum here: pinning the
    version makes the install reproducible and, more importantly, removes the
    "resolve whatever is newest on PyPI" step that turns this endpoint into a
    typosquat/dependency-confusion vector.  Anything the parser cannot read as
    ``name[extras]==version`` is rejected rather than sanitised, because a
    sanitised pip argument is still attacker-influenced.
    """
    allowed = allowed_names if allowed_names is not None else _default_allowed_dep_names()
    validated: list[str] = []
    for raw in specs:
        candidate = str(raw).strip()
        if not candidate:
            continue
        match = _DEP_SPEC_RE.match(candidate)
        if not match:
            raise DependencyNotAllowedError(
                f"Dependency {candidate!r} is not an exact 'name==version' pin. "
                "Version ranges, bare names, VCS/URL references and pip flags "
                "are rejected."
            )
        name = match.group("name").lower()
        if name not in allowed:
            raise DependencyNotAllowedError(
                f"Dependency {name!r} is not in the test-run allow-list. "
                "Add it to NEXUS_TEST_RUN_ALLOWED_DEPS to permit it."
            )
        validated.append(candidate)
    return tuple(validated)


class FailureType(StrEnum):
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
            elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
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
    """Executes pytest in a contained directory and produces structured reports.

    Every instance carries its own containment/timeout policy so tests and
    operators can tighten it without touching the process environment.
    """

    def __init__(
        self,
        sandbox_work_dir: Path | None = None,
        *,
        allowed_roots: Sequence[Path] | None = None,
        allowed_dep_names: frozenset[str] | None = None,
        pytest_timeout: int | None = None,
        pip_timeout: int | None = None,
        install_requirements: bool | None = None,
        ensure_dependencies: bool | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.sandbox_work_dir = sandbox_work_dir or Path(tempfile.gettempdir()) / "nexus_tests"
        self.allowed_roots = tuple(allowed_roots) if allowed_roots is not None else _default_allowed_roots()
        self.allowed_dep_names = (
            allowed_dep_names if allowed_dep_names is not None else _default_allowed_dep_names()
        )
        self.pytest_timeout = (
            pytest_timeout
            if pytest_timeout is not None
            else _env_int("NEXUS_TEST_RUN_PYTEST_TIMEOUT_SECONDS", 600)
        )
        self.pip_timeout = (
            pip_timeout if pip_timeout is not None else _env_int("NEXUS_TEST_RUN_PIP_TIMEOUT_SECONDS", 180)
        )
        self.install_requirements = (
            install_requirements
            if install_requirements is not None
            else _env_flag("NEXUS_TEST_RUN_INSTALL_REQUIREMENTS", False)
        )
        self.ensure_dependencies = (
            ensure_dependencies
            if ensure_dependencies is not None
            else _env_flag("NEXUS_TEST_RUN_ENSURE_DEPS", True)
        )
        self._python = python_executable or sys.executable

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(
        self,
        project_path: Path,
        extra_deps: list[str] | None = None,
    ) -> TestSuiteReport:
        """Run pytest with coverage in the given project directory.

        Args:
            project_path: Directory containing the code and tests.  Must
                resolve inside ``self.allowed_roots``.
            extra_deps: Additional packages to install before testing.  Each
                entry must be an exact ``name[extras]==version`` pin whose name
                is in ``self.allowed_dep_names``.

        Returns:
            TestSuiteReport with results and coverage.  A subprocess timeout or
            a non-zero exit still returns a report (never raises), so the API
            shape stays backward compatible.

        Raises:
            PathNotAllowedError: containment check failed.
            DependencyNotAllowedError: a requested dependency was rejected.
        """
        project_path = resolve_contained_path(project_path, self.allowed_roots)
        approved_deps = validate_dependency_specs(extra_deps or (), self.allowed_dep_names)

        report = TestSuiteReport()

        # ``requirements.txt`` is attacker-reachable content whenever the
        # allow-listed project is a checkout someone else controls, so it is
        # opt-in.  Auth + containment already held at this point.
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            if self.install_requirements:
                self._pip_install(project_path, "-r", str(req_file))
            else:
                logger.info(
                    "Skipping requirements.txt install for %s "
                    "(set NEXUS_TEST_RUN_INSTALL_REQUIREMENTS=true to allow)",
                    project_path,
                )
        if approved_deps:
            self._pip_install(project_path, *approved_deps)

        if self.ensure_dependencies:
            self._ensure_runner_deps(project_path)

        # Run pytest with JUnit XML output and coverage
        junit_path = project_path / ".pytest_results.xml"
        cov_xml = project_path / ".coverage.xml"

        cmd = [
            self._python, "-m", "pytest",
            "-v",
            "--tb=long",
            f"--junitxml={junit_path}",
            "--cov=.",
            f"--cov-report=xml:{cov_xml}",
            "--cov-report=term",
        ]

        start = time.monotonic()
        timed_out = False
        result: subprocess.CompletedProcess[str] | None = None
        stdout = ""
        try:
            result = subprocess.run(  # noqa: S603 — fixed argv, no shell
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.pytest_timeout,
                env=self._subprocess_env(),
            )
            stdout = result.stdout or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = self._decode_timeout_stream(exc.stdout)
            logger.warning(
                "pytest exceeded the %ss budget in %s — process killed",
                self.pytest_timeout,
                project_path,
            )
        finally:
            report.duration = round(time.monotonic() - start, 3)

        logger.info(
            "pytest exit code: %s",
            "timeout" if timed_out or result is None else result.returncode,
        )

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
        if timed_out:
            report.summary = (
                f"pytest exceeded the {self.pytest_timeout}s budget and was killed.\n"
                f"{stdout[-1500:]}"
            )
        else:
            report.summary = stdout[-2000:]

        return report

    def _subprocess_env(self) -> dict[str, str]:
        """Environment for every child process (no surprise ambient config)."""
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env["PIP_NO_INPUT"] = "1"
        return env

    @staticmethod
    def _decode_timeout_stream(stream: Any) -> str:
        if stream is None:
            return ""
        if isinstance(stream, bytes):
            return stream.decode("utf-8", errors="replace")
        return str(stream)

    def _ensure_runner_deps(self, cwd: Path) -> None:
        """Install the runner's own dependencies, but only when missing.

        The previous implementation pip-installed pytest/pytest-cov/
        pytest-asyncio on *every* run, which meant a network round trip and a
        possible version churn of the live venv for each API call.  Checking
        ``importlib`` first keeps the guarantee ("the runner works") without
        the side effect.
        """
        import importlib.util

        missing = [name for name in _RUNNER_DEPS if importlib.util.find_spec(name) is None]
        if missing:
            logger.info("Installing missing test-runner dependencies: %s", ", ".join(missing))
            self._pip_install(cwd, *missing)

    def _pip_install(self, cwd: Path, *packages: str) -> None:
        """Install Python packages in the project environment.

        ``timeout=`` is mandatory: an unbounded pip against an attacker-chosen
        index/URL is an easy way to wedge the worker forever.
        """
        if not packages:
            return
        cmd = [
            self._python, "-m", "pip", "install",
            "--no-input",
            "--disable-pip-version-check",
            *packages,
        ]
        try:
            result = subprocess.run(  # noqa: S603 — fixed argv, no shell
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=self.pip_timeout,
                env=self._subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "pip install exceeded the %ss budget for %s — killed",
                self.pip_timeout,
                " ".join(packages),
            )
            return
        if result.returncode != 0:
            logger.warning("pip install warning: %s", (result.stderr or "")[:500])

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
