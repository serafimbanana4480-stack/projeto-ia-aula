"""Safety tests for the commit-free AutoRollback.

Guarantees under test (each one was a real hazard in the previous
`git add -A` + `reset --hard` implementation):

1. A snapshot must never create commits or touch the working tree.
2. `restore` must revert ONLY files the system changed after the snapshot.
3. Pre-existing dirty files (user WIP) must survive a rollback untouched.
4. Untracked files created by the system are removed; untracked files that
   already existed are preserved.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.orchestrator.auto_rollback import AutoRollback


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        timeout=15,
    )


def _write(repo: Path, rel: str, content: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@nexus.dev")
    _git(tmp_path, "config", "user.name", "NEXUS Test")
    _write(tmp_path, "app.py", "print('v1')\n")
    _write(tmp_path, "lib.py", "X = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    return tmp_path


@pytest.fixture
def rollback(git_repo: Path) -> AutoRollback:
    return AutoRollback(repo_root=git_repo)


def test_snapshot_creates_no_commit_and_captures_pre_existing_state(
    git_repo: Path, rollback: AutoRollback
) -> None:
    # User WIP exists BEFORE the system starts.
    _write(git_repo, "app.py", "print('user WIP')\n")
    _write(git_repo, "notes.txt", "user untracked note\n")

    head_before = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    snap = rollback.snapshot(label="test")

    assert snap is not None
    assert snap.head == head_before
    assert "app.py" in snap.pre_existing_tracked
    assert "notes.txt" in snap.pre_existing_untracked
    # No new commit: HEAD unchanged.
    head_after = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert head_after == head_before


def test_restore_reverts_only_system_files_and_preserves_user_wip(
    git_repo: Path, rollback: AutoRollback
) -> None:
    _write(git_repo, "app.py", "print('user WIP')\n")
    snap = rollback.snapshot(label="cycle")

    # System changes two files: one it created, one it modified.
    _write(git_repo, "app.py", "print('system broke this')\n")
    _write(git_repo, "generated.py", "AUTO = True\n")

    result = rollback.restore(snap)

    assert result.rolled_back
    assert "generated.py" in result.restored_files
    # System's modification is gone…
    assert "system broke this" not in (git_repo / "app.py").read_text(encoding="utf-8")
    # …but the user's WIP is intact.
    assert (git_repo / "app.py").read_text(encoding="utf-8") == "print('user WIP')\n"
    # System-created untracked file removed…
    assert not (git_repo / "generated.py").exists()
    # …while the user's untracked file survives (it was pre-existing in this
    # scenario only if snapshotted; here it was not created, so untouched).


def test_restore_keeps_pre_existing_untracked_files(
    git_repo: Path, rollback: AutoRollback
) -> None:
    _write(git_repo, "user_draft.md", "draft\n")
    snap = rollback.snapshot(label="cycle")

    _write(git_repo, "system_output.log", "noise\n")

    rollback.restore(snap)

    assert (git_repo / "user_draft.md").read_text(encoding="utf-8") == "draft\n"
    assert not (git_repo / "system_output.log").exists()


def test_restore_without_snapshot_is_a_noop(rollback: AutoRollback) -> None:
    result = rollback.restore(None)
    assert not result.rolled_back
    assert result.error == "No snapshot to restore"
