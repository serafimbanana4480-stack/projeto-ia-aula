"""Project tools — list files, detect frameworks, find entry points, and summarize a project.

These tools wrap :mod:`backend.tools.project_analyzer` and add a lightweight
``get_project_summary`` action that returns a condensed overview suitable for
agent context.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from backend.tools.project_analyzer import analyze_project
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

_ENTRY_POINT_PATTERNS = {
    "python": ["main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "cli.py"],
    "javascript": ["index.js", "main.js", "app.js", "server.js", "cli.js"],
    "typescript": ["index.ts", "main.ts", "app.ts", "server.ts", "cli.ts"],
    "rust": ["main.rs", "lib.rs", "bin/", "src/main.rs"],
    "go": ["main.go", "cmd/"],
    "java": ["src/main/java/", "pom.xml"],
    "csharp": ["Program.cs", "Startup.cs", "Program.fs"],
}

_TEST_FILE_PATTERNS = [
    "test_",
    "_test.py",
    ".test.js",
    ".test.ts",
    ".spec.js",
    ".spec.ts",
    "/tests/",
    "/test/",
    "tests/",
    "test/",
    "__tests__/",
    "pytest.ini",
    "jest.config",
    "vitest.config",
]


def _find_entry_points(project: Path, files: list[Path]) -> list[str]:
    entry_points: list[str] = []
    rel_names = {str(f.relative_to(project)).lower(): f for f in files}
    for _language, patterns in _ENTRY_POINT_PATTERNS.items():
        for pattern in patterns:
            for rel_name, f in rel_names.items():
                if pattern in rel_name:
                    entry_points.append(str(f.relative_to(project)))
                    break
    return entry_points[:20]


def _find_test_files(project: Path, files: list[Path]) -> list[str]:
    test_files: list[str] = []
    for f in files:
        rel = str(f.relative_to(project)).lower().replace("\\", "/")
        if any(p in rel for p in _TEST_FILE_PATTERNS):
            test_files.append(str(f.relative_to(project)))
    return test_files[:50]


async def get_project_summary(project_path: str = ".") -> dict[str, Any]:
    """Return a condensed project overview.

    Includes file count, detected framework, entry points, test files, and
    top-level issues. This is a lighter alternative to ``analyze_project``
    when you only need a quick orientation.

    Args:
        project_path: Path to the project root.

    Returns:
        Dict with project path, file count, framework, entry points, test
        files, languages (by extension), and top-level issues.
    """
    try:
        project = Path(project_path).resolve()
        if not project.exists():
            return {"error": f"Project path not found: {project_path}"}
    except Exception as exc:
        return {"error": str(exc)}

    try:
        files: list[Path] = []
        for root, dirnames, filenames in os.walk(project, onerror=lambda exc: None):
            dirnames.sort()
            for name in filenames:
                files.append(Path(root) / name)
    except Exception as exc:
        return {"error": f"Failed to list project files: {exc}"}

    ext_counter: dict[str, int] = {}
    for f in files:
        ext = f.suffix.lower() or "no_extension"
        ext_counter[ext] = ext_counter.get(ext, 0) + 1

    try:
        analysis = await analyze_project(project_path)
    except Exception:
        analysis = {}

    framework = analysis.get("framework", {})
    issues = analysis.get("issues", [])[:5]

    test_files = _find_test_files(project, files)

    return {
        "ok": True,
        "project_path": str(project),
        "total_files": len(files),
        "languages_by_extension": ext_counter,
        "framework": framework.get("primary", "unknown"),
        "framework_confidence": framework.get("confidence", "low"),
        "entry_points": _find_entry_points(project, files),
        "test_files": test_files,
        "test_file_count": len(test_files),
        "issues": issues,
        "issue_count": len(analysis.get("issues", [])),
        "health_score": analysis.get("health_score"),
    }


async def list_project_files(
    project_path: str = ".",
    extensions: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """List files in a project, optionally filtered by extension.

    Args:
        project_path: Path to the project root.
        extensions: Comma-separated list of extensions to include (e.g. ``.py,.js``).
            Empty = include all files.
        limit: Maximum number of files to return.

    Returns:
        Dict with file paths and the filter applied.
    """
    try:
        project = Path(project_path).resolve()
        if not project.exists():
            return {"error": f"Project path not found: {project_path}"}
    except Exception as exc:
        return {"error": str(exc)}

    allowed_exts = {e.strip().lower() for e in extensions.split(",") if e.strip()} if extensions else set()
    result: list[str] = []
    try:
        for root, dirnames, filenames in os.walk(project, onerror=lambda exc: None):
            dirnames.sort()
            for name in sorted(filenames):
                if len(result) >= limit:
                    break
                if allowed_exts:
                    ext = Path(name).suffix.lower()
                    if ext not in allowed_exts:
                        continue
                result.append(str(Path(root) / name))
    except Exception as exc:
        return {"error": f"Failed to list files: {exc}"}

    return {
        "ok": True,
        "project_path": str(project),
        "files": result,
        "count": len(result),
        "filtered_by_extensions": sorted(allowed_exts) if allowed_exts else None,
    }


register_tool(
    ToolSpec(
        name="get_project_summary",
        description=(
            "Return a condensed project overview: file count, detected framework, "
            "entry points, test files, top-level issues, and health score."
        ),
        tags=["project", "analysis", "summary"],
        category="project",
        risk_level="low",
        when_to_use="When you need a quick orientation to a project before making changes.",
        schema={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Path to the project root.", "default": "."},
            },
        },
        handler=get_project_summary,
        timeout_seconds=30,
    )
)

register_tool(
    ToolSpec(
        name="list_project_files",
        description=(
            "List files in a project, optionally filtered by extension. "
            "Returns up to *limit* file paths relative to the project root."
        ),
        tags=["project", "files", "list"],
        category="project",
        risk_level="low",
        when_to_use="When you need to see what files exist in a project directory.",
        schema={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Path to the project root.", "default": "."},
                "extensions": {"type": "string", "description": "Comma-separated extensions (e.g. .py,.js).", "default": ""},
                "limit": {"type": "integer", "description": "Max files to return.", "default": 200, "maximum": 1000},
            },
        },
        handler=list_project_files,
        timeout_seconds=20,
    )
)
