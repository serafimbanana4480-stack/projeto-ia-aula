from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from backend.tools import git_tools
from backend.tools.git_tools import _validate_git_command, git_commit_safe, normalize_git_path


@pytest.mark.parametrize(
    "command",
    [
        "git status --short",
        "git rev-parse HEAD",
        "git pull origin main",
        "git push --dry-run origin main",
    ],
)
def test_explicitly_supported_git_commands_remain_available(command: str) -> None:
    is_safe, reason = _validate_git_command(command)

    assert is_safe is True
    assert reason == ""


@pytest.mark.parametrize(
    "command",
    [
        "git rm important.txt",
        "git branch -D old-branch",
        "git config --global core.autocrlf false",
        "git worktree prune",
        "git arbitrary-subcommand",
    ],
)
def test_unknown_git_subcommands_fail_closed(command: str) -> None:
    is_safe, reason = _validate_git_command(command)

    assert is_safe is False
    assert reason


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_path_scoped_commit_preserves_unrelated_staged_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.name", "NEXUS test")
    _run_git(repo, "config", "user.email", "nexus-test@example.invalid")

    target = repo / "target file.txt"
    unrelated = repo / "unrelated.txt"
    target.write_text("before\n", encoding="utf-8")
    unrelated.write_text("before\n", encoding="utf-8")
    _run_git(repo, "add", "--all")
    _run_git(repo, "commit", "-m", "baseline")

    target.write_text("after target\n", encoding="utf-8")
    unrelated.write_text("after unrelated\n", encoding="utf-8")
    _run_git(repo, "add", "--", "unrelated.txt")

    result = asyncio.run(
        git_commit_safe(
            message='target "quoted" change',
            project_path=str(repo),
            paths=["target file.txt"],
        )
    )

    assert result["commit"]["exit_code"] == 0, result
    committed_paths = _run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
    assert committed_paths.splitlines() == ["target file.txt"]
    assert _run_git(repo, "log", "-1", "--pretty=%s") == 'target "quoted" change'
    assert _run_git(repo, "diff", "--cached", "--name-only").splitlines() == ["unrelated.txt"]


def test_path_scoped_commit_requires_paths_when_not_staging_all(tmp_path: Path) -> None:
    result = asyncio.run(git_commit_safe(project_path=str(tmp_path)))

    assert "Explicit paths are required" in result["error"]


def test_normalize_git_path_rejects_paths_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="inside the project"):
        normalize_git_path("../outside.txt", str(project))


@pytest.mark.parametrize("target_kind", ["directory", "missing"])
def test_normalize_git_path_rejects_non_files(tmp_path: Path, target_kind: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    directory = project / "folder"
    if target_kind == "directory":
        directory.mkdir()
        target = directory
    else:
        target = project / "missing.txt"

    with pytest.raises(ValueError, match="existing file"):
        normalize_git_path(str(target), str(project))


def test_commit_toolspec_declaration_is_truthful() -> None:
    """The ToolSpec must not claim a confirmation policy it does not enforce.

    Audit 2026-10-06 P1: ``git_commit_safe`` was declared with no
    ``risk_level`` and no ``requires_confirmation`` while its description and
    handler docstring both advertised "Requires confirmation". The description
    is now accurate AND the policy is actually enforced (high risk + listed in
    ``registry._CONFIRMATION_TOOLS``), so a reader of either surface gets the
    truth.
    """
    from backend.tools.registry import get_tool, tool_requires_confirmation

    spec = get_tool("git_commit_safe")
    assert spec is not None

    assert spec.risk_level == "high"
    assert tool_requires_confirmation(spec) is True

    description = (spec.description or "").casefold()
    # No leftover claim that only ``add_all`` (or nothing) needs approval.
    assert "requires explicit confirmation" not in description
    assert "requires confirmation" not in description.replace(
        "requires confirmation (risk_level high)", ""
    )
    assert "requires confirmation" in description

    docstring = (git_commit_safe.__doc__ or "").casefold()
    assert "add_all: whether to stage all changes before committing. requires" not in docstring
    assert "risk_level=\"high\"" in git_commit_safe.__doc__


def test_commit_error_is_propagated_to_top_level(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("changed\n", encoding="utf-8")

    async def fake_git_operation(command, project_path):
        if "add" in command:
            return {"output": "staged", "exit_code": 0}
        return {"error": "Git is not installed or not in PATH"}

    monkeypatch.setattr(git_tools, "git_operation", fake_git_operation)
    result = asyncio.run(
        git_commit_safe(project_path=str(tmp_path), paths=[str(target)])
    )

    assert result["commit"]["error"] == "Git is not installed or not in PATH"
    assert "git commit failed" in result["error"]
