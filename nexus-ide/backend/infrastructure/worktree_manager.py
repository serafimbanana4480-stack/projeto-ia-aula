"""Git Worktree Isolation System — manage per-task repository copies.

Provides safe creation, removal, and synchronisation of git worktrees,
enabling parallel development branches and isolated execution environments
without the overhead of full repository clones.

Features:
- Create worktrees linked to existing branches or new branch names
- Remove stale worktrees and clean up orphaned paths
- List all active worktrees with metadata
- Sync worktrees with their upstream branches
- Automatic garbage collection of old worktrees

Architecture:
- ``WorktreeManager``: main orchestrator
- ``WorktreeInfo``: metadata dataclass for a single worktree
- ``WorktreeError``: domain-specific exception

Security:
- All git commands are logged
- Paths are validated before execution
- Shell injection is prevented by passing arguments as lists
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WorktreeError(Exception):
    """Raised when a worktree operation fails."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


@dataclass
class WorktreeInfo:
    """Metadata describing a single git worktree."""

    path: str
    branch: str
    commit: str
    is_main: bool = False
    is_bare: bool = False
    prunable: bool = False
    last_modified: datetime | None = None


@dataclass
class WorktreeManagerConfig:
    """Configuration for WorktreeManager."""

    worktree_dir_suffix: str = "_wt"
    default_max_age_hours: int = 24
    auto_prune: bool = True
    git_timeout: int = 30


class WorktreeManager:
    """Manages git worktrees for isolated repository environments.

    Each worktree is a lightweight directory linked to the same git object
    database, allowing multiple checked-out branches to coexist without
    the I/O cost of cloning.
    """

    def __init__(self, config: WorktreeManagerConfig | None = None) -> None:
        self._config = config or WorktreeManagerConfig()

    def _run_git(
        self,
        repo_path: Path | str,
        args: list[str],
        *,
        check: bool = True,
        capture: bool = True,
        cwd: Path | str | None = None,
    ) -> subprocess.CompletedProcess:
        """Execute a git command safely using a subprocess.

        Args:
            repo_path: Path to the git repository (used as cwd if ``cwd`` is omitted).
            args: Git subcommand and flags as a list.
            check: Raise :class:`WorktreeError` on non-zero exit.
            capture: Capture stdout/stderr.
            cwd: Override working directory.

        Returns:
            A :class:`subprocess.CompletedProcess` instance.

        Raises:
            WorktreeError: When ``check=True`` and the command fails.
        """
        working_dir = Path(cwd) if cwd else Path(repo_path)
        cmd = ["git", *args]
        logger.debug("Running git command in %s: %s", working_dir, " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                cwd=str(working_dir),
                capture_output=capture,
                text=True,
                timeout=self._config.git_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"Git command timed out after {self._config.git_timeout}s"
            logger.error(msg)
            raise WorktreeError(msg, {"command": cmd}) from exc
        except FileNotFoundError as exc:
            msg = "Git executable not found in PATH"
            logger.error(msg)
            raise WorktreeError(msg) from exc

        if check and result.returncode != 0:
            msg = f"Git command failed: {' '.join(cmd)}"
            logger.error("%s (stderr: %s)", msg, result.stderr)
            raise WorktreeError(
                msg,
                details={
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )

        return result

    def _validate_repo(self, repo_path: Path | str) -> Path:
        """Ensure ``repo_path`` points to a valid git repository.

        Returns:
            Absolute :class:`Path` to the repository.

        Raises:
            WorktreeError: If the path is not a git repository.
        """
        path = Path(repo_path).resolve()
        if not (path / ".git").is_dir() and not (path / ".git").is_file():
            # Also support bare repos
            git_dir = path / ".git"
            if not git_dir.exists():
                raise WorktreeError(
                    f"Not a git repository: {path}",
                    {"path": str(path)},
                )
        return path

    def create_worktree(
        self,
        repo_path: str | Path,
        branch_name: str,
        *,
        worktree_path: str | Path | None = None,
        force: bool = False,
    ) -> WorktreeInfo:
        """Create a new worktree for the given branch.

        If the branch does not exist it will be created.

        Args:
            repo_path: Path to the base git repository.
            branch_name: Name of the branch to check out in the worktree.
            worktree_path: Destination directory for the worktree. If omitted,
                           a path next to the repo root is generated.
            force: Overwrite an existing worktree path if it already exists.

        Returns:
            :class:`WorktreeInfo` describing the new worktree.

        Raises:
            WorktreeError: If the repository is invalid or the command fails.
        """
        repo = self._validate_repo(repo_path)
        branch = branch_name.strip()

        if not worktree_path:
            # Generate a sibling path: repo_root/../{repo_name}_{branch}_wt
            safe_branch = branch.replace("/", "_").replace("\\", "_")
            worktree_path = repo.parent / f"{repo.name}_{safe_branch}{self._config.worktree_dir_suffix}"
        else:
            worktree_path = Path(worktree_path).resolve()

        # Check if branch already exists; create it if not
        branch_check = self._run_git(repo, ["branch", "--list", branch], check=False)
        if branch not in branch_check.stdout:
            logger.info("Creating new branch '%s' in %s", branch, repo)
            self._run_git(repo, ["branch", branch])

        # Remove stale directory if force is set
        if force and worktree_path.exists():
            logger.warning("Force-removing existing worktree path: %s", worktree_path)
            shutil.rmtree(worktree_path, ignore_errors=True)
            # Also prune any lingering git registration
            self._run_git(repo, ["worktree", "prune"], check=False)

        logger.info(
            "Creating worktree for branch '%s' at %s (force=%s)",
            branch, worktree_path, force,
        )
        self._run_git(
            repo,
            [
                "worktree",
                "add",
                str(worktree_path),
                branch,
            ],
        )

        # Fetch commit hash
        result = self._run_git(worktree_path, ["rev-parse", "HEAD"])
        commit = result.stdout.strip()

        wt_info = WorktreeInfo(
            path=str(worktree_path),
            branch=branch,
            commit=commit,
        )
        logger.info("Worktree created: %s", wt_info)
        return wt_info

    def remove_worktree(
        self,
        worktree_path: str | Path,
        *,
        remove_branch: bool = False,
    ) -> None:
        """Remove a worktree and optionally delete its branch.

        Args:
            worktree_path: Path to the worktree directory.
            remove_branch: Also delete the branch checked out in the worktree.

        Raises:
            WorktreeError: If the worktree cannot be removed.
        """
        worktree = Path(worktree_path).resolve()
        if not worktree.exists():
            logger.warning("Worktree path does not exist: %s", worktree)
            return

        # Discover the main repo from the worktree
        result = self._run_git(worktree, ["rev-parse", "--git-common-dir"])
        repo_root = Path(result.stdout.strip()).parent

        branch = ""
        if remove_branch:
            branch_result = self._run_git(worktree, ["rev-parse", "--abbrev-ref", "HEAD"])
            branch = branch_result.stdout.strip()

        logger.info("Removing worktree %s (remove_branch=%s)", worktree, remove_branch)
        self._run_git(repo_root, ["worktree", "remove", str(worktree)])

        if remove_branch and branch:
            self._run_git(repo_root, ["branch", "-D", branch], check=False)
            logger.info("Deleted branch %s", branch)

        # Prune any stale worktree entries
        if self._config.auto_prune:
            self._run_git(repo_root, ["worktree", "prune"], check=False)

    def list_worktrees(self, repo_path: str | Path) -> list[WorktreeInfo]:
        """List all worktrees associated with a repository.

        Args:
            repo_path: Path to the base git repository.

        Returns:
            List of :class:`WorktreeInfo` entries.
        """
        repo = self._validate_repo(repo_path)
        result = self._run_git(repo, ["worktree", "list", "--porcelain"])

        worktrees: list[WorktreeInfo] = []
        current: dict[str, Any] = {}

        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current:
                    worktrees.append(self._parse_worktree_entry(current))
                current = {"path": line[9:].strip()}
            elif line.startswith("branch "):
                current["branch"] = line[7:].strip()
            elif line.startswith("head "):
                current["commit"] = line[5:].strip()
            elif line.startswith("bare"):
                current["bare"] = True
            elif line.startswith("prunable"):
                current["prunable"] = True

        if current:
            worktrees.append(self._parse_worktree_entry(current))

        return worktrees

    def _parse_worktree_entry(self, raw: dict[str, Any]) -> WorktreeInfo:
        """Convert a raw porcelain entry into a :class:`WorktreeInfo`."""
        path = raw.get("path", "")
        branch_ref = raw.get("branch", "")
        branch = branch_ref.replace("refs/heads/", "") if branch_ref.startswith("refs/heads/") else branch_ref
        commit = raw.get("commit", "")
        is_main = not branch or branch in ("main", "master")
        is_bare = raw.get("bare", False)
        prunable = raw.get("prunable", False)

        last_modified: datetime | None = None
        try:
            p = Path(path)
            if p.exists():
                mtime = p.stat().st_mtime
                last_modified = datetime.fromtimestamp(mtime, tz=UTC)
        except OSError:
            pass

        return WorktreeInfo(
            path=path,
            branch=branch,
            commit=commit,
            is_main=is_main,
            is_bare=is_bare,
            prunable=prunable,
            last_modified=last_modified,
        )

    def sync_worktree(
        self,
        worktree_path: str | Path,
        *,
        remote: str = "origin",
        pull: bool = True,
        rebase: bool = False,
    ) -> WorktreeInfo:
        """Synchronise a worktree with its upstream branch.

        Args:
            worktree_path: Path to the worktree directory.
            remote: Name of the remote to fetch from.
            pull: Run ``git pull`` after fetching.
            rebase: Use ``--rebase`` when pulling.

        Returns:
            Updated :class:`WorktreeInfo`.
        """
        worktree = Path(worktree_path).resolve()
        if not worktree.exists():
            raise WorktreeError(f"Worktree does not exist: {worktree}")

        logger.info("Syncing worktree %s (pull=%s, rebase=%s)", worktree, pull, rebase)
        self._run_git(worktree, ["fetch", remote])

        if pull:
            pull_args = ["pull", remote]
            if rebase:
                pull_args.append("--rebase")
            self._run_git(worktree, pull_args)

        # Update commit hash
        result = self._run_git(worktree, ["rev-parse", "HEAD"])
        commit = result.stdout.strip()

        branch_result = self._run_git(worktree, ["rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_result.stdout.strip()

        return WorktreeInfo(
            path=str(worktree),
            branch=branch,
            commit=commit,
        )

    def cleanup_old_worktrees(
        self,
        repo_path: str | Path,
        *,
        max_age_hours: int | None = None,
    ) -> list[str]:
        """Remove worktrees that have not been modified within the threshold.

        The main worktree (the one that contains ``.git``) is never removed.

        Args:
            repo_path: Path to the base git repository.
            max_age_hours: Age threshold in hours; defaults to config value.

        Returns:
            List of paths that were removed.
        """
        repo = self._validate_repo(repo_path)
        threshold = max_age_hours or self._config.default_max_age_hours
        cutoff = datetime.now(UTC) - timedelta(hours=threshold)
        removed: list[str] = []

        for wt in self.list_worktrees(repo):
            if wt.is_main or wt.is_bare:
                continue
            if wt.last_modified is None:
                logger.warning("Worktree %s has no modification time; skipping", wt.path)
                continue
            if wt.last_modified < cutoff:
                logger.info(
                    "Removing stale worktree %s (last modified %s, cutoff %s)",
                    wt.path, wt.last_modified, cutoff,
                )
                try:
                    self.remove_worktree(wt.path)
                    removed.append(wt.path)
                except WorktreeError as exc:
                    logger.error("Failed to remove worktree %s: %s", wt.path, exc)

        return removed
