from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from backend.tools import git_auto_commit


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_auto_commit_only_commits_triggering_file(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
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

    monkeypatch.setattr(
        git_auto_commit,
        "_get_config",
        lambda: {"enabled": True, "strategy": "always", "model": "test"},
    )

    async def generate_commit_message(**_kwargs: Any) -> git_auto_commit.CommitAnalysis:
        return git_auto_commit.CommitAnalysis(
            commit_type="fix",
            scope="test",
            description="isola ficheiro",
            body="",
            breaking=False,
        )

    monkeypatch.setattr(git_auto_commit, "generate_commit_message", generate_commit_message)
    monkeypatch.setattr(git_auto_commit, "_record_commit", lambda **_kwargs: None)

    result = asyncio.run(
        git_auto_commit.auto_commit_after_write(
            file_path=str(target),
            project_path=str(repo),
        )
    )

    assert result["committed"] is True, result
    committed_paths = _run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
    assert committed_paths.splitlines() == ["target file.txt"]
    assert _run_git(repo, "diff", "--cached", "--name-only").splitlines() == ["unrelated.txt"]


def _create_repo_with_modified_target(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.name", "NEXUS test")
    _run_git(repo, "config", "user.email", "nexus-test@example.invalid")
    target = repo / "target.txt"
    target.write_text("before\n", encoding="utf-8")
    _run_git(repo, "add", "--all")
    _run_git(repo, "commit", "-m", "baseline")
    target.write_text("after\n", encoding="utf-8")
    return repo, target


def _install_test_commit_message(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        git_auto_commit,
        "_get_config",
        lambda: {"enabled": True, "strategy": "always", "model": "test"},
    )

    async def generate_commit_message(**_kwargs: Any) -> git_auto_commit.CommitAnalysis:
        return git_auto_commit.CommitAnalysis(
            commit_type="fix",
            scope="test",
            description="testa falhas de commit",
            body="",
            breaking=False,
        )

    monkeypatch.setattr(git_auto_commit, "generate_commit_message", generate_commit_message)
    monkeypatch.setattr(git_auto_commit, "_record_commit", lambda **_kwargs: None)


def test_auto_commit_does_not_treat_nested_error_as_success(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo, target = _create_repo_with_modified_target(tmp_path)
    _install_test_commit_message(monkeypatch)

    async def failed_commit(**_kwargs: Any) -> dict[str, Any]:
        return {"commit": {"error": "Git is not installed or not in PATH"}}

    monkeypatch.setattr(git_auto_commit, "git_commit_safe", failed_commit)
    result = asyncio.run(
        git_auto_commit.auto_commit_after_write(
            file_path=str(target),
            project_path=str(repo),
        )
    )

    assert result["committed"] is False
    assert result["status"] == "failed"
    assert "Git is not installed" in result["error"]


def test_auto_commit_keeps_success_truthful_when_hash_lookup_fails(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo, target = _create_repo_with_modified_target(tmp_path)
    _install_test_commit_message(monkeypatch)
    actual_git_operation = git_auto_commit.git_operation

    async def fail_head_lookup(command, project_path):
        if command == "git rev-parse HEAD":
            return {"error": "temporary Git failure"}
        return await actual_git_operation(command, project_path)

    monkeypatch.setattr(git_auto_commit, "git_operation", fail_head_lookup)
    result = asyncio.run(
        git_auto_commit.auto_commit_after_write(
            file_path=str(target),
            project_path=str(repo),
        )
    )

    assert result["committed"] is True
    assert result["status"] == "committed"
    assert result["hash"] is None
    assert "hash could not be retrieved" in result["warning"]
