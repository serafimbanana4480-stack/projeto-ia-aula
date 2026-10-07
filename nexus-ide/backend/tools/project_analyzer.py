"""Project analyzer tool — deep analysis of project structure and health.

Detects frameworks, dependencies, test coverage, and potential issues.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# --- TTL cache layer for analyze_project ---

def _cache_ttl() -> float:
    return float(os.environ.get("NEXUS_ANALYZE_CACHE_TTL", "30"))

_MAX_CACHE_ENTRIES = 8

_cache_data: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_cache_computes = 0
_cache_hits = 0
_in_flight: dict[str, asyncio.Event] = {}


def _reset_analyze_cache() -> None:
    global _cache_data, _cache_computes, _cache_hits, _in_flight
    _cache_data.clear()
    _cache_computes = 0
    _cache_hits = 0
    _in_flight.clear()


def _cache_stats() -> dict:
    return {"computes": _cache_computes, "hits": _cache_hits, "entries": len(_cache_data)}


async def _cached_analyze(project_path: str) -> dict:
    global _cache_computes, _cache_hits

    now = time.monotonic()
    ttl = _cache_ttl()

    expired = [k for k, (ts, _) in _cache_data.items() if now - ts > ttl]
    for k in expired:
        del _cache_data[k]

    if project_path in _cache_data:
        ts, result = _cache_data[project_path]
        if now - ts <= ttl:
            _cache_data.move_to_end(project_path)
            _cache_hits += 1
            return dict(result)
        del _cache_data[project_path]

    if project_path in _in_flight:
        await _in_flight[project_path].wait()
        if project_path in _cache_data:
            _cache_data.move_to_end(project_path)
            _cache_hits += 1
            return dict(_cache_data[project_path][1])

    event = asyncio.Event()
    _in_flight[project_path] = event
    try:
        result = await _analyze_uncached(project_path=project_path)
    finally:
        del _in_flight[project_path]
        event.set()

    _cache_data[project_path] = (now, result)
    _cache_data.move_to_end(project_path)
    _cache_computes += 1

    while len(_cache_data) > _MAX_CACHE_ENTRIES:
        _cache_data.popitem(last=False)

    return dict(result)

_FRAMEWORK_SIGNATURES: dict[str, list[str]] = {
    "django": ["django", "settings.py", "urls.py", "wsgi.py", "asgi.py"],
    "fastapi": ["fastapi", "uvicorn", "app = fastapi()", "from fastapi import"],
    "flask": ["flask", "app = flask(__name__)", "from flask import"],
    "react": ["react", "vite.config.", "src/app.", "index.html"],
    "vue": ["vue", "vite.config.", "app.vue", "vue-router"],
    "nextjs": ["next", "next.config.", "app/layout.", "pages/"],
    "angular": ["angular", "angular.json", "src/app/app.component."],
    "svelte": ["svelte", "svelte.config.", "src/app.svelte"],
    "rust": ["cargo.toml", "src/main.rs", "src/lib.rs"],
    "go": ["go.mod", "main.go", "internal/"],
    "flutter": ["flutter", "pubspec.yaml", "lib/main.dart"],
    "data_science": ["jupyter", "notebooks/", "pandas", "numpy", "scikit-learn"],
    "microservices": ["docker-compose.yml", "kong.yml", "services/"],
}

_DEPENDENCY_FILES = {
    "python": ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"],
    "javascript": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "go": ["go.mod", "go.sum"],
    "flutter": ["pubspec.yaml", "pubspec.lock"],
    "data_science": ["requirements.txt", "environment.yml", "pyproject.toml"],
}

_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".next",
    ".next-dev",
    ".nexus",
    ".kilo",
    ".agents",
    ".ruff_cache",
    ".tox",
    ".turbo",
    "out",
    "target",
    ".idea",
    ".vscode",
    "coverage",
    "logs",
    "reports",
    "tmp",
    "temp",
    "artifacts",
    "playwright-report",
    "test-results",
    "site-packages",
    ".gitignore",  # not a dir but safe to include
}

_MAX_PROJECT_FILES = 20_000
_MAX_SCAN_SECONDS = 8.0


def _walk_project(project: Path, *, state: dict[str, Any] | None = None):
    """Yield a bounded project file inventory, pruning generated data."""
    scan_state = state if state is not None else {}
    scan_state.setdefault("truncated", False)
    scan_state.setdefault("errors", [])
    started = time.monotonic()
    yielded = 0

    def onerror(exc: OSError) -> None:
        scan_state["errors"].append(str(exc))

    for root, dirnames, filenames in os.walk(project, onerror=onerror):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _EXCLUDED_DIRS and not name.startswith(".pytest-")
        )
        for name in sorted(filenames):
            if yielded >= _MAX_PROJECT_FILES or time.monotonic() - started > _MAX_SCAN_SECONDS:
                scan_state["truncated"] = True
                return
            path = Path(root) / name
            try:
                if not path.is_file():
                    continue
            except OSError as exc:
                scan_state["errors"].append(str(exc))
                continue
            yielded += 1
            yield path


def _detect_framework(project: Path, files: list[Path]) -> dict:
    """Detect project framework based on file names and content."""
    file_names = {f.name.lower() for f in files}
    file_paths_lower = [str(f.relative_to(project)).lower() for f in files]

    scores: dict[str, int] = {}

    for framework, signatures in _FRAMEWORK_SIGNATURES.items():
        score = 0
        for sig in signatures:
            sig_lower = sig.lower()
            if sig_lower in file_names:
                score += 2
            for fp in file_paths_lower:
                if sig_lower in fp:
                    score += 1
        if score > 0:
            scores[framework] = score

    sorted_frameworks = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_frameworks[0][0] if sorted_frameworks else "unknown"
    confidence = (
        "high"
        if (sorted_frameworks and sorted_frameworks[0][1] >= 3)
        else "medium"
        if sorted_frameworks
        else "low"
    )

    return {
        "primary": primary,
        "confidence": confidence,
        "candidates": {k: v for k, v in sorted_frameworks[:3]},
    }


def _find_dependencies(project: Path, files: list[Path]) -> dict:
    """Find dependency files and extract package lists."""
    deps: dict[str, dict] = {}

    dep_file_map: dict[str, str] = {}
    for ecosystem, filenames in _DEPENDENCY_FILES.items():
        for fname in filenames:
            dep_file_map[fname.lower()] = ecosystem

    for f in files:
        key = f.name.lower()
        if key in dep_file_map:
            ecosystem = dep_file_map[key]
            try:
                content = f.read_text(encoding="utf-8")
                packages: list[str] = []
                if key == "requirements.txt":
                    for line in content.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            pkg = line.split("==")[0].split(">=")[0].split("<")[0].strip()
                            if pkg:
                                packages.append(pkg)
                elif key == "package.json":
                    try:
                        data = json.loads(content)
                        packages.extend(data.get("dependencies", {}).keys())
                        packages.extend(data.get("devDependencies", {}).keys())
                    except json.JSONDecodeError:
                        pass
                elif key == "cargo.toml":
                    try:
                        import tomllib

                        data = tomllib.loads(content)
                        packages.extend(data.get("dependencies", {}).keys())
                        packages.extend(data.get("dev-dependencies", {}).keys())
                    except Exception:
                        pass
                elif key == "go.mod":
                    for line in content.splitlines():
                        line = line.strip()
                        if (
                            line
                            and not line.startswith("(")
                            and not line.startswith(")")
                            and not line.startswith("module")
                            and not line.startswith("go ")
                            and not line.startswith("require")
                        ):
                            parts = line.split()
                            if parts:
                                packages.append(parts[0])
                elif key == "pubspec.yaml":
                    try:
                        import yaml

                        data = yaml.safe_load(content)
                        packages.extend(data.get("dependencies", {}).keys())
                        packages.extend(data.get("dev_dependencies", {}).keys())
                    except Exception:
                        pass

                deps[str(f.relative_to(project))] = {
                    "ecosystem": ecosystem,
                    "package_count": len(packages),
                    "packages": packages[:20],
                }
            except Exception:
                deps[str(f.relative_to(project))] = {
                    "ecosystem": ecosystem,
                    "package_count": 0,
                    "packages": [],
                }

    return deps


def _count_loc(project: Path, files: list[Path]) -> dict:
    """Calculate lines of code by extension."""
    loc_by_ext: Counter = Counter()
    total_loc = 0
    total_files = 0

    for f in files:
        if f.is_file() and f.stat().st_size < 5_000_000:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                lines = len(content.splitlines())
                ext = f.suffix.lower() or "no_extension"
                loc_by_ext[ext] += lines
                total_loc += lines
                total_files += 1
            except Exception:
                continue

    return {
        "total_files": total_files,
        "total_lines_of_code": total_loc,
        "by_extension": dict(loc_by_ext.most_common()),
    }


def _find_test_coverage(project: Path, files: list[Path]) -> dict:
    """Detect test coverage if available."""
    coverage_files = [
        f
        for f in files
        if f.name.lower() in {".coverage", "coverage.xml", "coverage.json", "lcov.info"}
    ]
    test_dirs = any(
        "/test" in str(f.relative_to(project)).lower().replace("\\", "/")
        or str(f.relative_to(project)).lower().replace("\\", "/").startswith("test/")
        or str(f.relative_to(project)).lower().replace("\\", "/").startswith("tests/")
        for f in files
    )

    has_pytest_ini = any(f.name.lower() == "pytest.ini" for f in files)
    has_setup_cfg_tests = False
    for f in files:
        if f.name.lower() == "setup.cfg":
            try:
                content = f.read_text(encoding="utf-8")
                if "[tool:pytest]" in content or "pytest" in content:
                    has_setup_cfg_tests = True
            except Exception:
                pass

    return {
        "test_files_found": test_dirs,
        "coverage_files": [str(f.relative_to(project)) for f in coverage_files],
        "has_pytest_ini": has_pytest_ini,
        "has_setup_cfg_tests": has_setup_cfg_tests,
    }


def _detect_issues(project: Path, files: list[Path]) -> list[dict]:
    """Detect potential project issues."""
    issues: list[dict] = []
    file_names = {f.name.lower() for f in files}
    dir_paths = {str(f.relative_to(project)).lower() for f in files if f.is_dir()}

    if ".gitignore" not in file_names:
        issues.append(
            {
                "type": "missing_file",
                "severity": "medium",
                "message": "No .gitignore found — sensitive files may be committed",
                "recommendation": "Create a .gitignore file for your project stack",
            }
        )

    if "readme.md" not in file_names and "readme.rst" not in file_names:
        issues.append(
            {
                "type": "missing_file",
                "severity": "low",
                "message": "No README found",
                "recommendation": "Add a README.md with project description and setup instructions",
            }
        )

    has_tests = any("test" in d for d in dir_paths) or any("test_" in fn for fn in file_names)
    if not has_tests:
        issues.append(
            {
                "type": "missing_tests",
                "severity": "high",
                "message": "No test files or test directories found",
                "recommendation": "Add tests (pytest, jest, cargo test, etc.)",
            }
        )

    if "license" not in file_names and "license.md" not in file_names:
        issues.append(
            {
                "type": "missing_file",
                "severity": "low",
                "message": "No LICENSE file found",
                "recommendation": "Add a LICENSE file to clarify usage rights",
            }
        )

    large_files = []
    for f in files:
        if f.is_file() and f.stat().st_size > 1_000_000:
            large_files.append(str(f.relative_to(project)))
    if large_files:
        issues.append(
            {
                "type": "large_files",
                "severity": "medium",
                "message": f"Found {len(large_files)} file(s) larger than 1MB",
                "files": large_files[:5],
                "recommendation": "Consider adding large files to .gitignore or using Git LFS",
            }
        )

    secret_patterns = ["password=", "secret=", "api_key=", "token=", "aws_access_key_id"]
    for f in files:
        if f.name.lower() in {".env", ".env.example", ".env.local"}:
            continue
        if f.is_file() and f.stat().st_size < 500_000:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore").lower()
                for pattern in secret_patterns:
                    if pattern in content:
                        issues.append(
                            {
                                "type": "potential_secret",
                                "severity": "high",
                                "message": f"Potential secret pattern '{pattern}' found in {f.name}",
                                "file": str(f.relative_to(project)),
                                "recommendation": "Verify no secrets are committed; use environment variables",
                            }
                        )
                        break
            except Exception:
                pass

    return issues


async def _analyze_uncached(project_path: str = ".") -> dict:
    """Deep analysis of a project — uncached, used as the handler."""
    try:
        project = Path(project_path).resolve()
        if not project.exists():
            return {"error": f"Project path not found: {project_path}"}

        scan_state: dict[str, Any] = {}
        files = list(_walk_project(project, state=scan_state))

        ext_counter: Counter = Counter()
        for i, f in enumerate(files):
            if i and i % 2 == 0:
                await asyncio.sleep(0)
            ext = f.suffix.lower() or "no_extension"
            ext_counter[ext] += 1

        framework_info = _detect_framework(project, files)
        dependencies = _find_dependencies(project, files)
        loc_info = _count_loc(project, files)
        coverage_info = _find_test_coverage(project, files)
        issues = _detect_issues(project, files)

        report = {
            "project_path": str(project),
            "total_files": len(files),
            "scan_truncated": bool(scan_state.get("truncated")),
            "scan_errors": list(scan_state.get("errors", []))[:20],
            "files_by_extension": dict(ext_counter.most_common()),
            "framework": framework_info,
            "dependencies": dependencies,
            "lines_of_code": loc_info,
            "test_coverage": coverage_info,
            "issues": issues,
            "issue_count": len(issues),
            "health_score": max(
                0,
                100
                - len([i for i in issues if i["severity"] == "high"]) * 20
                - len([i for i in issues if i["severity"] == "medium"]) * 10
                - len([i for i in issues if i["severity"] == "low"]) * 5,
            ),
        }

        logger.info(
            "Analyzed project at %s: %d files, framework=%s",
            project,
            len(files),
            framework_info["primary"],
        )
        return report

    except Exception as e:
        logger.exception("Project analysis failed: %s", e)
        return {"error": f"Project analysis failed: {e}"}


register_tool(
    ToolSpec(
        name="analyze_project",
        description=(
            "Deep analysis of a project: counts files by extension, detects framework, "
            "finds dependencies, calculates lines of code, checks test coverage, "
            "and detects potential issues. Returns a structured JSON report."
        ),
        schema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Path to the project root",
                },
            },
        },
        handler=_analyze_uncached,
    )
)


async def analyze_project(project_path: str = ".") -> dict:
    """Deep analysis of a project — cached version."""
    return await _cached_analyze(project_path)
