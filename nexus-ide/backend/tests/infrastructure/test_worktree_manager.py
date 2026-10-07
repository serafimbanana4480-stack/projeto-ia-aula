"""Tests for WorktreeManager infrastructure module.

Covers:
- Worktree creation, removal, listing
- Sync operations
- Cleanup of old worktrees
- Error handling (invalid repo, git failures)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.infrastructure.worktree_manager import (
    WorktreeError,
    WorktreeInfo,
    WorktreeManager,
    WorktreeManagerConfig,
)


class TestWorktreeManagerConfig:
    def test_default_values(self) -> None:
        config = WorktreeManagerConfig()
        assert config.worktree_dir_suffix == "_wt"
        assert config.default_max_age_hours == 24
        assert config.auto_prune is True
        assert config.git_timeout == 30

    def test_custom_values(self) -> None:
        config = WorktreeManagerConfig(
            default_max_age_hours=48,
            auto_prune=False,
            git_timeout=60,
        )
        assert config.default_max_age_hours == 48
        assert config.auto_prune is False
        assert config.git_timeout == 60


class TestWorktreeManagerInit:
    def test_init_defaults(self) -> None:
        wm = WorktreeManager()
        assert wm._config is not None
        assert wm._config.default_max_age_hours == 24

    def test_init_custom_config(self) -> None:
        config = WorktreeManagerConfig(default_max_age_hours=12)
        wm = WorktreeManager(config)
        assert wm._config.default_max_age_hours == 12


class TestWorktreeManagerCreate:
    def _make_wt_manager(self, results: list) -> WorktreeManager:
        """Helper that returns a WorktreeManager with mocked _run_git."""
        wm = WorktreeManager()
        call_idx = 0

        def fake_run_git(repo_path, args, **kwargs):
            nonlocal call_idx
            mock = MagicMock()
            mock.stdout = ""
            mock.stderr = ""
            mock.returncode = 0

            if call_idx < len(results):
                result = results[call_idx]
                mock.stdout = result.get("stdout", "")
                mock.stderr = result.get("stderr", "")
                mock.returncode = result.get("returncode", 0)
                if mock.returncode != 0 and kwargs.get("check", True):
                    raise WorktreeError(
                        f"Git failed: {' '.join(args)}",
                        {"returncode": mock.returncode, "stderr": mock.stderr},
                    )
            call_idx += 1
            return mock

        wm._run_git = fake_run_git  # type: ignore[method-assign]
        return wm

    def test_create_worktree_success(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        # branch --list returns empty => branch will be created
        # branch creation
        # worktree add
        # rev-parse HEAD
        wm = self._make_wt_manager([
            {"stdout": ""},  # branch --list
            {"stdout": ""},  # branch <branch>
            {"stdout": ""},  # worktree add
            {"stdout": "abc123def456\n"},  # rev-parse HEAD
        ])

        info = wm.create_worktree(repo, "feature/test")
        assert info.path is not None
        assert info.branch == "feature/test"
        assert info.commit == "abc123def456"

    def test_create_worktree_branch_already_exists(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        wm = self._make_wt_manager([
            {"stdout": "feature/test\n"},  # branch exists
            {"stdout": ""},  # worktree add
            {"stdout": "def789abc012\n"},  # rev-parse HEAD
        ])

        info = wm.create_worktree(repo, "feature/test")
        assert info.branch == "feature/test"
        assert info.commit == "def789abc012"

    def test_create_worktree_invalid_repo(self, tmp_path: Path) -> None:
        wm = WorktreeManager()
        with pytest.raises(WorktreeError, match="Not a git repository"):
            wm.create_worktree(tmp_path / "not-a-repo", "feature/test")

    def test_create_worktree_custom_path(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        custom = tmp_path / "custom-wt"

        wm = self._make_wt_manager([
            {"stdout": ""},
            {"stdout": ""},
            {"stdout": ""},
            {"stdout": "abc123\n"},
        ])

        info = wm.create_worktree(repo, "feature/custom", worktree_path=custom)
        assert info.path == str(custom)

    def test_create_worktree_force(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        wt = tmp_path / "repo_feature-force_wt"
        wt.mkdir()

        # Force should remove existing path before creating
        with patch.object(wm := WorktreeManager(), "_run_git") as mock_git:
            mock_git.return_value = MagicMock(stdout="", stderr="", returncode=0)
            wm.create_worktree(repo, "feature-force", force=True)
            assert not wt.exists()  # path was removed during creation


class TestWorktreeManagerRemove:
    def _make_wt_manager(self, results: list) -> WorktreeManager:
        wm = WorktreeManager()
        call_idx = 0

        def fake_run_git(repo_path, args, **kwargs):
            nonlocal call_idx
            mock = MagicMock()
            mock.stdout = ""
            mock.stderr = ""
            mock.returncode = 0

            if call_idx < len(results):
                result = results[call_idx]
                mock.stdout = result.get("stdout", "")
                mock.stderr = result.get("stderr", "")
                mock.returncode = result.get("returncode", 0)
                if mock.returncode != 0 and kwargs.get("check", True):
                    raise WorktreeError("Git failed")
            call_idx += 1
            return mock

        wm._run_git = fake_run_git  # type: ignore[method-assign]
        return wm

    def test_remove_worktree(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()

        wm = self._make_wt_manager([
            {"stdout": str(tmp_path / "repo") + "\n"},  # rev-parse --git-common-dir
            {"stdout": ""},  # worktree remove
            {"stdout": ""},  # worktree prune
        ])

        # Should not raise
        wm.remove_worktree(wt)

    def test_remove_worktree_and_branch(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()

        wm = self._make_wt_manager([
            {"stdout": str(tmp_path / "repo") + "\n"},  # git-common-dir
            {"stdout": "feature/del\n"},  # rev-parse --abbrev-ref HEAD
            {"stdout": ""},  # worktree remove
            {"stdout": ""},  # branch -D
            {"stdout": ""},  # worktree prune
        ])

        wm.remove_worktree(wt, remove_branch=True)

    def test_remove_worktree_nonexistent(self, tmp_path: Path) -> None:
        wm = WorktreeManager()
        # Should not raise
        wm.remove_worktree(tmp_path / "does-not-exist")


class TestWorktreeManagerList:
    def test_list_worktrees(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        porcelain = (
            "worktree /home/dev/repo\n"
            "HEAD abc123def456789012345678901234567890abcd\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /home/dev/repo_feature-x_wt\n"
            "HEAD def789abc0123456789012345678901234567890\n"
            "branch refs/heads/feature-x\n"
        )

        wm = WorktreeManager()
        with patch.object(wm, "_run_git") as mock_git:
            mock_git.return_value = MagicMock(stdout=porcelain, stderr="", returncode=0)
            worktrees = wm.list_worktrees(repo)

        assert len(worktrees) == 2
        assert worktrees[0].path == "/home/dev/repo"
        assert worktrees[0].branch == "main"
        assert worktrees[0].is_main is True
        assert worktrees[1].path == "/home/dev/repo_feature-x_wt"
        assert worktrees[1].branch == "feature-x"
        assert worktrees[1].is_main is False

    def test_list_worktrees_prunable(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        porcelain = (
            "worktree /home/dev/stale\n"
            "HEAD 0000000000000000000000000000000000000000\n"
            "prunable\n"
        )

        wm = WorktreeManager()
        with patch.object(wm, "_run_git") as mock_git:
            mock_git.return_value = MagicMock(stdout=porcelain, stderr="", returncode=0)
            worktrees = wm.list_worktrees(repo)

        assert len(worktrees) == 1
        assert worktrees[0].prunable is True

    def test_list_worktrees_invalid_repo(self, tmp_path: Path) -> None:
        wm = WorktreeManager()
        with pytest.raises(WorktreeError, match="Not a git repository"):
            wm.list_worktrees(tmp_path / "not-a-repo")


class TestWorktreeManagerSync:
    def test_sync_worktree(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()

        wm = WorktreeManager()
        with patch.object(wm, "_run_git") as mock_git:
            mock_git.return_value = MagicMock(stdout="", stderr="", returncode=0)
            info = wm.sync_worktree(wt)

        assert info.path == str(wt)
        assert info.commit == ""
        assert mock_git.call_count == 4  # fetch, pull, rev-parse HEAD, rev-parse --abbrev-ref HEAD

    def test_sync_worktree_rebase(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()

        calls = []

        def capture(repo_path, args, **kwargs):
            calls.append(args)
            return MagicMock(stdout="newcommit123\n" if "rev-parse" in args else "", stderr="", returncode=0)

        wm = WorktreeManager()
        with patch.object(wm, "_run_git", side_effect=capture):
            wm.sync_worktree(wt, rebase=True)

        pull_call = next(c for c in calls if c[0] == "pull")
        assert "--rebase" in pull_call

    def test_sync_worktree_not_found(self, tmp_path: Path) -> None:
        wm = WorktreeManager()
        with pytest.raises(WorktreeError, match="Worktree does not exist"):
            wm.sync_worktree(tmp_path / "missing")


class TestWorktreeManagerCleanup:
    def test_cleanup_old_worktrees(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        wt = tmp_path / "repo_feature-old_wt"
        wt.mkdir()
        # Make it look very old
        (datetime.now(UTC) - timedelta(days=2)).timestamp()
        (wt / "dummy.txt").write_text("x")
        # We can't easily set mtime in a cross-platform way in these tests,
        # so we patch the list_worktrees result instead.

        wm = WorktreeManager()
        stale_wt = WorktreeInfo(
            path=str(wt),
            branch="feature-old",
            commit="abc",
            last_modified=datetime.now(UTC) - timedelta(days=2),
        )
        main_wt = WorktreeInfo(
            path=str(repo),
            branch="main",
            commit="def",
            is_main=True,
            last_modified=datetime.now(UTC),
        )

        with patch.object(wm, "list_worktrees", return_value=[main_wt, stale_wt]):
            with patch.object(wm, "remove_worktree") as mock_remove:
                removed = wm.cleanup_old_worktrees(repo, max_age_hours=1)

        assert len(removed) == 1
        assert removed[0] == str(wt)
        mock_remove.assert_called_once_with(str(wt))

    def test_cleanup_skips_main_and_bare(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        wm = WorktreeManager()
        main_wt = WorktreeInfo(
            path=str(repo), branch="main", commit="abc", is_main=True,
            last_modified=datetime.now(UTC) - timedelta(days=5),
        )
        bare_wt = WorktreeInfo(
            path=str(tmp_path / "bare"), branch="", commit="", is_bare=True,
            last_modified=datetime.now(UTC) - timedelta(days=5),
        )

        with patch.object(wm, "list_worktrees", return_value=[main_wt, bare_wt]):
            removed = wm.cleanup_old_worktrees(repo, max_age_hours=1)

        assert removed == []

    def test_cleanup_skips_unknown_mtime(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        wm = WorktreeManager()
        no_mtime = WorktreeInfo(
            path=str(tmp_path / "no-mtime"), branch="x", commit="y",
            last_modified=None,
        )

        with patch.object(wm, "list_worktrees", return_value=[no_mtime]):
            removed = wm.cleanup_old_worktrees(repo, max_age_hours=1)

        assert removed == []

    def test_cleanup_uses_default_max_age(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        wm = WorktreeManager(WorktreeManagerConfig(default_max_age_hours=12))
        stale = WorktreeInfo(
            path=str(tmp_path / "stale"), branch="stale", commit="abc",
            last_modified=datetime.now(UTC) - timedelta(hours=13),
        )

        with patch.object(wm, "list_worktrees", return_value=[stale]):
            with patch.object(wm, "remove_worktree"):
                removed = wm.cleanup_old_worktrees(repo)

        assert len(removed) == 1


class TestWorktreeError:
    def test_error_message(self) -> None:
        err = WorktreeError("Something failed")
        assert str(err) == "Something failed"

    def test_error_with_details(self) -> None:
        err = WorktreeError("Git failed", {"returncode": 1})
        assert err.details == {"returncode": 1}
