"""Sandbox Overlay — filesystem snapshot and replay for deterministic execution.

Uses git within the sandbox container to create immutable snapshots
of the workspace state before execution, enabling replay and rollback.
"""
from __future__ import annotations

import io
import logging
import tarfile
from dataclasses import dataclass
from typing import Any

from docker.models.containers import Container

logger = logging.getLogger(__name__)


@dataclass
class SnapshotResult:
    """Result of a workspace snapshot."""

    commit_hash: str
    label: str
    files_tracked: int


@dataclass
class ReplayResult:
    """Result of a workspace replay."""

    commit_hash: str
    files_restored: int
    success: bool
    error: str | None = None


class WorkspaceOverlay:
    """Manages workspace state snapshots and replays using git.

    Since overlayfs is only available on Linux hosts, this implementation
    uses git inside the container to track workspace state. This provides:
    - Immutable snapshots before each execution
    - Deterministic replay to any prior state
    - Audit trail of all changes
    """

    def __init__(self, container: Container, workspace: str = "/workspace") -> None:
        self._container = container
        self._workspace = workspace
        self._git_initialized = False

    def _exec(self, cmd: list[str]) -> tuple[int, str, str]:
        """Execute a command in the container and return (exit_code, stdout, stderr)."""
        result = self._container.exec_run(cmd, workdir=self._workspace)
        exit_code = result.exit_code
        output = ""
        if isinstance(result.output, tuple):
            stdout_bytes, stderr_bytes = result.output
            output = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
            return exit_code, output, stderr
        elif result.output:
            output = result.output.decode("utf-8", errors="replace")
        return exit_code, output, ""

    def initialize_git(self) -> bool:
        """Initialize git tracking in the workspace."""
        if self._git_initialized:
            return True

        # Check if git exists
        exit_code, _, _ = self._exec(["which", "git"])
        if exit_code != 0:
            logger.warning("git not available in container, skipping overlay")
            return False

        # Initialize git repo
        self._exec(["git", "init"])
        self._exec(["git", "config", "user.email", "sandbox@nexus.local"])
        self._exec(["git", "config", "user.name", "Nexus Sandbox"])

        # Create .gitignore to exclude caches
        gitignore = "__pycache__/\n*.pyc\nnode_modules/\n*.log\n"
        self._write_file(".gitignore", gitignore)

        # Stage and commit initial empty state
        self._exec(["git", "add", "-A"])
        self._exec(["git", "commit", "-m", "initial", "--allow-empty"])

        self._git_initialized = True
        logger.debug("Git overlay initialized in %s", self._workspace)
        return True

    def _write_file(self, path: str, content: str) -> None:
        """Write a file to the container via tar archive."""
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            content_bytes = content.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(content_bytes)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(content_bytes))
        tar_buffer.seek(0)
        self._container.put_archive(self._workspace, tar_buffer)

    def snapshot(self, label: str = "snapshot") -> SnapshotResult | None:
        """Create a git snapshot of the current workspace state.

        Args:
            label: Descriptive label for the snapshot.

        Returns:
            SnapshotResult with commit hash, or None if git unavailable.
        """
        if not self._git_initialized and not self.initialize_git():
            return None

        # Stage all changes
        self._exec(["git", "add", "-A"])

        # Count tracked files
        _, tracked, _ = self._exec(["git", "diff", "--cached", "--name-only"])
        files_tracked = len([f for f in tracked.split("\n") if f.strip()])

        # Commit with label
        commit_msg = f"{label}"
        exit_code, _, stderr = self._exec(["git", "commit", "-m", commit_msg])

        if exit_code != 0:
            # Nothing to commit or error
            logger.debug("Snapshot commit skipped: %s", stderr)
            _, head, _ = self._exec(["git", "rev-parse", "HEAD"])
            commit_hash = head.strip()
            return SnapshotResult(
                commit_hash=commit_hash,
                label=label,
                files_tracked=0,
            )

        # Get commit hash
        _, head, _ = self._exec(["git", "rev-parse", "HEAD"])
        commit_hash = head.strip()

        logger.debug(
            "Snapshot created: %s (%d files)",
            commit_hash[:8],
            files_tracked,
        )
        return SnapshotResult(
            commit_hash=commit_hash,
            label=label,
            files_tracked=files_tracked,
        )

    def replay(self, commit_hash: str | None = None) -> ReplayResult:
        """Replay workspace to a specific snapshot.

        Args:
            commit_hash: Hash to replay to. If None, replays to initial state.

        Returns:
            ReplayResult indicating success or failure.
        """
        if not self._git_initialized and not self.initialize_git():
            return ReplayResult(
                commit_hash="",
                files_restored=0,
                success=False,
                error="git not available",
            )

        target = commit_hash or "HEAD"

        # Reset to target (hard reset removes all changes)
        self._exec(["git", "reset", "--hard", target])

        # Clean untracked files
        self._exec(["git", "clean", "-fd"])

        # Count restored files
        _, ls_files, _ = self._exec(["git", "ls-files"])
        files_restored = len([f for f in ls_files.split("\n") if f.strip()])

        logger.debug(
            "Replayed to %s (%d files)",
            target[:8] if len(target) > 8 else target,
            files_restored,
        )
        return ReplayResult(
            commit_hash=target,
            files_restored=files_restored,
            success=True,
        )

    def get_snapshots(self) -> list[dict[str, Any]]:
        """List all available snapshots."""
        if not self._git_initialized and not self.initialize_git():
            return []

        _, log_output, _ = self._exec([
            "git", "log", "--pretty=format:%H|%s|%ci", "--reverse",
        ])

        snapshots = []
        for line in log_output.split("\n"):
            line = line.strip()
            if "|" in line:
                parts = line.split("|", 2)
                if len(parts) >= 3:
                    snapshots.append({
                        "hash": parts[0],
                        "label": parts[1],
                        "timestamp": parts[2],
                    })

        return snapshots

    def diff_since_snapshot(self, commit_hash: str) -> str:
        """Show diff between current state and a snapshot."""
        if not self._git_initialized:
            return ""

        _, diff, _ = self._exec(["git", "diff", commit_hash])
        return diff
