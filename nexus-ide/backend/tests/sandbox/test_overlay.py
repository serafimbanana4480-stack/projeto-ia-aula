"""Tests for WorkspaceOverlay snapshot and replay.

These tests mock the Docker container interface to avoid requiring Docker.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from backend.sandbox.overlay import WorkspaceOverlay


class TestWorkspaceOverlay:
    def test_initialize_git_success(self) -> None:
        container = MagicMock()
        # Mock exec_run responses
        responses = [
            # which git -> success
            MagicMock(exit_code=0, output=b"/usr/bin/git"),
            # git init
            MagicMock(exit_code=0, output=b""),
            # git config email
            MagicMock(exit_code=0, output=b""),
            # git config name
            MagicMock(exit_code=0, output=b""),
            # git add -A
            MagicMock(exit_code=0, output=b""),
            # git commit
            MagicMock(exit_code=0, output=b"[main] initial"),
            # git rev-parse HEAD
            MagicMock(exit_code=0, output=b"abc123\n"),
        ]
        container.exec_run.side_effect = responses

        overlay = WorkspaceOverlay(container)
        result = overlay.initialize_git()
        assert result is True

    def test_initialize_git_no_git_binary(self) -> None:
        container = MagicMock()
        container.exec_run.return_value = MagicMock(
            exit_code=1, output=b"",
        )

        overlay = WorkspaceOverlay(container)
        result = overlay.initialize_git()
        assert result is False

    def test_snapshot_creates_commit(self) -> None:
        container = MagicMock()
        # Pre-initialize
        overlay = WorkspaceOverlay(container)
        overlay._git_initialized = True

        # Mock snapshot responses
        container.exec_run.side_effect = [
            # git add -A
            MagicMock(exit_code=0, output=b""),
            # git diff --cached --name-only
            MagicMock(exit_code=0, output=b"main.py\nutils.py\n"),
            # git commit
            MagicMock(exit_code=0, output=b"[main] pre-test"),
            # git rev-parse HEAD
            MagicMock(exit_code=0, output=b"deadbeef1234567890\n"),
        ]

        result = overlay.snapshot(label="pre-test")
        assert result is not None
        assert result.label == "pre-test"
        assert result.commit_hash == "deadbeef1234567890"
        assert result.files_tracked == 2

    def test_replay_restores_state(self) -> None:
        container = MagicMock()
        overlay = WorkspaceOverlay(container)
        overlay._git_initialized = True

        container.exec_run.side_effect = [
            # git reset --hard
            MagicMock(exit_code=0, output=b"HEAD is now at abc123"),
            # git clean -fd
            MagicMock(exit_code=0, output=b""),
            # git ls-files
            MagicMock(exit_code=0, output=b"main.py\n"),
        ]

        result = overlay.replay(commit_hash="abc123")
        assert result.success is True
        assert result.commit_hash == "abc123"
        assert result.files_restored == 1

    def test_get_snapshots(self) -> None:
        container = MagicMock()
        overlay = WorkspaceOverlay(container)
        overlay._git_initialized = True

        log_output = (
            b"abc123|initial|2025-05-08 10:00:00 +0000\n"
            b"def456|pre-exec|2025-05-08 10:05:00 +0000\n"
        )
        container.exec_run.return_value = MagicMock(
            exit_code=0, output=log_output,
        )

        snapshots = overlay.get_snapshots()
        assert len(snapshots) == 2
        assert snapshots[0]["hash"] == "abc123"
        assert snapshots[0]["label"] == "initial"
        assert snapshots[1]["hash"] == "def456"
        assert snapshots[1]["label"] == "pre-exec"
