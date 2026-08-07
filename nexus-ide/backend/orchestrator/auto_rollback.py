"""Auto Rollback — reverts changes if quality gates fail.

Uses git to create automatic checkpoints before applying improvements,
and rolls back to the last known good state if verification fails.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RollbackResult:
    rolled_back: bool
    commit_hash: str | None = None
    error: str | None = None


class AutoRollback:
    """Automatic rollback using git."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent.parent
        self._git_available = self._check_git()

    def _check_git(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_root), "rev-parse", "--git-dir"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def create_checkpoint(self, message: str = "auto: pre-improvement checkpoint") -> str | None:
        if not self._git_available:
            logger.debug("Git not available, skipping checkpoint")
            return None
        try:
            subprocess.run(
                ["git", "-C", str(self.repo_root), "add", "-A"],
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                ["git", "-C", str(self.repo_root), "commit", "-m", message, "--no-gpg-sign"],
                capture_output=True,
                timeout=30,
            )
            result = subprocess.run(
                ["git", "-C", str(self.repo_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            commit_hash = result.stdout.strip()
            logger.info("Checkpoint created | commit=%s", commit_hash)
            return commit_hash
        except Exception as exc:
            logger.warning("Checkpoint creation failed: %s", exc)
            return None

    def rollback_to(self, commit_hash: str) -> RollbackResult:
        if not self._git_available:
            return RollbackResult(rolled_back=False, error="Git not available")
        try:
            subprocess.run(
                ["git", "-C", str(self.repo_root), "reset", "--hard", commit_hash],
                capture_output=True,
                timeout=30,
            )
            logger.info("Rollback completed | commit=%s", commit_hash)
            return RollbackResult(rolled_back=True, commit_hash=commit_hash)
        except Exception as exc:
            logger.exception("Rollback failed")
            return RollbackResult(rolled_back=False, error=str(exc))

    def rollback_last(self) -> RollbackResult:
        if not self._git_available:
            return RollbackResult(rolled_back=False, error="Git not available")
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_root), "log", "--oneline", "-2"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = result.stdout.strip().splitlines()
            if len(lines) < 2:
                return RollbackResult(rolled_back=False, error="No previous commit found")
            previous_commit = lines[1].split()[0]
            return self.rollback_to(previous_commit)
        except Exception as exc:
            return RollbackResult(rolled_back=False, error=str(exc))
