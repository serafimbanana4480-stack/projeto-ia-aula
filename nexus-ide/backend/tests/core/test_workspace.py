"""Tests for backend.core.workspace bug-fixes and performance improvements.

Covers:
1. Git detection via ``git rev-parse --git-dir`` (parent directories).
2. Project deduplication — descendants of identified projects are skipped.
3. Performance — os.scandir, skip lists, max_depth default 5, 5-min cache.
4. Windows python fallback (py -> python).
5. PermissionError / FileNotFoundError handling.
"""

from __future__ import annotations

import asyncio
import platform
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.core import workspace as workspace_mod
from backend.core.workspace import (
    _backup_dir_for,
    _get_dependencies,
    _windows_python_fixup,
    discover_projects,
    execute_script,
    get_project_info,
)


# ---------------------------------------------------------------------------
# 1. Git detection via subprocess
# ---------------------------------------------------------------------------

class TestGitDetection:
    async def test_is_git_repo_detects_parent_git(self, tmp_path: Path) -> None:
        """A directory inside a git repo (but without its own .git) is detected."""
        repo = tmp_path / "repo"
        repo.mkdir()
        sub = repo / "subpackage"
        sub.mkdir()

        # Initialise git at repo level
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)

        # _is_git_repo should return True for the subdirectory
        assert await workspace_mod._is_git_repo(sub) is True

    async def test_is_git_repo_false_outside_repo(self, tmp_path: Path) -> None:
        """A plain directory with no git ancestry is not a repo."""
        plain = tmp_path / "plain"
        plain.mkdir()
        assert await workspace_mod._is_git_repo(plain) is False

    async def test_backup_dir_uses_git_subprocess_not_dotgit(self, tmp_path: Path) -> None:
        """_backup_dir_for must detect git repos via subprocess, not just .git."""
        repo = tmp_path / "repo"
        repo.mkdir()
        nested = repo / "src" / "module.py"
        nested.parent.mkdir(parents=True)
        nested.write_text("x")

        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)

        # Even though nested has no .git directly, backup_dir should find repo's .nexus
        result = await _backup_dir_for(nested)
        assert result == repo / ".nexus" / "backups"


# ---------------------------------------------------------------------------
# 2. Deduplication in discover_projects
# ---------------------------------------------------------------------------

class TestDiscoverDeduplication:
    async def test_child_project_skips_descendants(self, tmp_path: Path) -> None:
        """When a directory is identified as a project its children are ignored."""
        root = tmp_path / "root"
        root.mkdir()

        parent = root / "parent_proj"
        parent.mkdir()
        (parent / "package.json").write_text('{"name":"parent"}')

        child = parent / "node_modules" / "some_pkg"
        child.mkdir(parents=True)
        (child / "package.json").write_text('{"name":"child"}')

        # node_modules is in _SKIP_DIRS, but even if it weren't, parent_proj
        # should be the only returned project.
        result = await discover_projects(str(root))
        assert result["count"] == 1
        assert result["projects"][0]["name"] == "parent_proj"

    async def test_git_root_skips_subfolders(self, tmp_path: Path) -> None:
        """A git repo root stops recursion -- subfolders are not returned."""
        root = tmp_path / "root"
        root.mkdir()

        repo = root / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        sub = repo / "sub"
        sub.mkdir()
        (sub / "package.json").write_text("{}", encoding="utf-8")

        result = await discover_projects(str(root))
        names = {p["name"] for p in result["projects"]}
        assert "myrepo" in names
        assert "sub" not in names

    async def test_root_itself_is_project(self, tmp_path: Path) -> None:
        """If root_path itself is a project it is returned immediately."""
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "pyproject.toml").write_text("[project]\nname = 'proj'\n")

        result = await discover_projects(str(proj))
        assert result["count"] == 1
        assert result["projects"][0]["path"] == str(proj)


# ---------------------------------------------------------------------------
# 3. Performance — skip dirs, max_depth, cache
# ---------------------------------------------------------------------------

class TestDiscoverPerformance:
    async def test_skip_dirs_ignored(self, tmp_path: Path) -> None:
        """node_modules, .venv, __pycache__, .git, dist, build are skipped."""
        root = tmp_path / "root"
        root.mkdir()
        container = root / "container"
        container.mkdir()
        for name in workspace_mod._SKIP_DIRS:
            (container / name).mkdir()
            (container / name / "package.json").write_text("{}")

        result = await discover_projects(str(root))
        # .git inside container makes container a git repo, so it is reported.
        # The important thing is that the SKIP_DIRS themselves are not reported
        # as separate projects.
        reported_names = {p["name"] for p in result["projects"]}
        assert not reported_names.intersection(workspace_mod._SKIP_DIRS)

    async def test_max_depth_default_is_five(self, tmp_path: Path) -> None:
        """The default max_depth parameter must be 5."""
        import inspect

        sig = inspect.signature(discover_projects)
        default = sig.parameters["max_depth"].default
        assert default == 5

    async def test_max_depth_respected(self, tmp_path: Path) -> None:
        """Directories deeper than max_depth are not scanned."""
        root = tmp_path / "root"
        root.mkdir()
        deep = root / "a" / "b" / "c" / "d" / "e" / "f"
        deep.mkdir(parents=True)
        (deep / "package.json").write_text("{}")

        # max_depth=5 means we scan root (depth 1) + 5 more levels => deepest a/b/c/d/e
        result = await discover_projects(str(root), max_depth=5)
        assert result["count"] == 0

        # max_depth=6 should find it
        result = await discover_projects(str(root), max_depth=6)
        assert result["count"] == 1

    async def test_caching(self, tmp_path: Path) -> None:
        """Results are cached for 5 minutes."""
        root = tmp_path / "root"
        root.mkdir()
        (root / "package.json").write_text("{}")

        # Clear cache
        workspace_mod._DISCOVERY_CACHE.clear()

        first = await discover_projects(str(root))
        assert first.get("cached") is False

        second = await discover_projects(str(root))
        assert second.get("cached") is True
        assert second["projects"] == first["projects"]

    async def test_cache_expires(self, tmp_path: Path) -> None:
        """Cache entries expire after the TTL."""
        root = tmp_path / "root"
        root.mkdir()
        (root / "package.json").write_text("{}")

        workspace_mod._DISCOVERY_CACHE.clear()
        first = await discover_projects(str(root))
        assert first.get("cached") is False

        # Fake an old timestamp
        cache_key = f"{root.resolve()}:5:100"
        old_time = time.monotonic() - workspace_mod._DISCOVERY_CACHE_TTL - 1
        workspace_mod._DISCOVERY_CACHE[cache_key] = (
            old_time,
            {"root": str(root), "projects": [], "count": 0},
        )

        result = await discover_projects(str(root))
        assert result.get("cached") is False
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# 4. Windows python command
# ---------------------------------------------------------------------------

class TestWindowsPythonFallback:
    def test_py_in_whitelist(self) -> None:
        assert "py" in workspace_mod._SHELL_WHITELIST

    def test_fixup_replaces_python_when_py_available(self) -> None:
        with patch("backend.core.workspace.shutil.which", return_value="/bin/py"):
            with patch("backend.core.workspace.platform.system", return_value="Windows"):
                assert _windows_python_fixup("python script.py") == "py script.py"
                assert _windows_python_fixup("python") == "py"
                assert _windows_python_fixup("  python --version") == "py --version"

    def test_fixup_keeps_python_when_py_missing(self) -> None:
        with patch("backend.core.workspace.shutil.which", return_value=None):
            with patch("backend.core.workspace.platform.system", return_value="Windows"):
                assert _windows_python_fixup("python script.py") == "python script.py"
                assert _windows_python_fixup("python") == "python"

    def test_fixup_noop_on_non_windows(self) -> None:
        with patch("backend.core.workspace.platform.system", return_value="Linux"):
            assert _windows_python_fixup("python script.py") == "python script.py"


# ---------------------------------------------------------------------------
# 5. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    async def test_get_project_info_permission_error_on_rglob(self, tmp_path: Path) -> None:
        """PermissionError during rglob should not crash get_project_info."""
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "package.json").write_text("{}")

        with patch.object(Path, "rglob", side_effect=PermissionError("denied")):
            result = await get_project_info(str(proj))

        assert "error" not in result
        assert result["language"] == "javascript"
        assert result["file_count"] == 0
        assert result["dir_count"] == 0

    async def test_get_dependencies_handles_permission_error(self, tmp_path: Path) -> None:
        """Unreadable requirements.txt should not crash dependency detection."""
        proj = tmp_path / "proj"
        proj.mkdir()
        req = proj / "requirements.txt"
        req.write_text("requests\n")

        with patch.object(
            Path, "read_text", side_effect=PermissionError("denied")
        ):
            deps = await _get_dependencies(proj, "python")
        assert deps == []

    async def test_execute_script_permission_error(self, tmp_path: Path) -> None:
        """PermissionError when reading a script returns a structured error."""
        script = tmp_path / "script"
        script.write_text("#!/bin/bash\necho hello")

        with patch.object(
            Path, "read_text", side_effect=PermissionError("denied")
        ):
            result = await execute_script(str(script))

        assert "error" in result
        assert (
            "permission" in result["error"].lower()
            or "failed to access" in result["error"].lower()
        ) or "failed" in result["error"].lower()

    async def test_discover_projects_permission_denied_root(self, tmp_path: Path) -> None:
        """A root path that raises PermissionError returns a structured error."""
        with patch(
            "backend.core.workspace._is_blocked_path", return_value=(False, "")
        ):
            with patch.object(
                Path, "resolve", side_effect=PermissionError("denied")
            ):
                result = await discover_projects("/some/path")
        assert "error" in result
        assert (
            "permission" in result["error"].lower()
            or "failed to access" in result["error"].lower()
        )

    async def test_discover_projects_not_a_directory(self, tmp_path: Path) -> None:
        """Passing a file as root_path returns a structured error."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("hello")
        result = await discover_projects(str(file_path))
        assert "error" in result
        assert "not a directory" in result["error"].lower()


# ---------------------------------------------------------------------------
# 6. get_project_info git parent detection
# ---------------------------------------------------------------------------

class TestGetProjectInfoGit:
    async def test_git_info_from_parent_directory(self, tmp_path: Path) -> None:
        """get_project_info detects git even when .git is in a parent dir."""
        repo = tmp_path / "repo"
        repo.mkdir()
        sub = repo / "src"
        sub.mkdir()
        (sub / "main.py").write_text("print(1)")

        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        result = await get_project_info(str(sub))
        assert result["git"]["is_repo"] is True

    async def test_no_git_info_outside_repo(self, tmp_path: Path) -> None:
        """A plain directory returns is_repo=False."""
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "main.py").write_text("print(1)")

        result = await get_project_info(str(plain))
        assert result["git"]["is_repo"] is False
