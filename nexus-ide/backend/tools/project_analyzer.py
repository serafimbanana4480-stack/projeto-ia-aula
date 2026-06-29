"""Project analyzer tool — deep analysis of project structure and health.

Detects frameworks, dependencies, test coverage, and potential issues.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

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
    "out",
    "target",
    ".idea",
    ".vscode",
    "coverage",
    ".gitignore",  # not a dir but safe to include
}


def _walk_project(project: Path):
    """Yield files under project, skipping excluded directories."""
    for entry in project.iterdir():
        if entry.name in _EXCLUDED_DIRS:
            continue
        if entry.is_dir():
            yield from _walk_project(entry)
        elif entry.is_file():
            yield entry


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


async def analyze_project(project_path: str = ".") -> dict:
    """Deep analysis of a project.

    Args:
        project_path: Path to the project root.

    Returns:
        Structured JSON report with project statistics, framework detection,
        dependencies, lines of code, test coverage, and issues.
    """
    try:
        project = Path(project_path).resolve()
        if not project.exists():
            return {"error": f"Project path not found: {project_path}"}

        files = list(_walk_project(project))

        ext_counter: Counter = Counter()
        for f in files:
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
        handler=analyze_project,
    )
)
