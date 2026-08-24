"""Auto Rollback — surgical, commit-free revert for autonomous improvements.

The previous implementation ran ``git add -A`` + ``git commit`` before every
cycle and rolled back with ``git reset --hard``. On a shared working tree
that is destructive in two ways:

1. ``git add -A`` swept *unrelated in-progress work* (the developer's edits,
   other agents' outputs, potential secrets) into ``auto: ...`` commits —
   observed live when the cycle committed changes it did not make.
2. ``git reset --hard`` erased everything committed after the checkpoint,
   including work that had nothing to do with the failed improvement.

The new model never creates commits and never moves branches:

- :meth:`AutoRollback.snapshot` records the current ``HEAD`` plus the set of
  paths that were *already* dirty before the system touched anything.
- :meth:`AutoRollback.restore` reverts only paths that are dirty *now* and
  were *not* pre-existing — user work is untouchable by construction.
  Untracked files created by the system are removed; pre-existing untracked
  files are left alone.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RollbackResult:
    rolled_back: bool
    commit_hash: str | None = None
    error: str | None = None
    restored_files: list[str] = field(default_factory=list)


@dataclass
class TreeSnapshot:
    """Everything needed to surgically undo the system's own changes.

    ``pre_existing_content`` keeps the in-memory content of dirty tracked
    files captured at snapshot time. A file can be user WIP *and* later
    modified by the system; restoring to HEAD alone would wipe the user's
    edits, so the saved content is written back after the checkout. Content
    is capped per file and in total so a pathological tree cannot blow up
    memory.
    """

    MAX_FILE_BYTES = 512 * 1024
    MAX_TOTAL_BYTES = 5 * 1024 * 1024

    head: str
    pre_existing_tracked: frozenset[str]
    pre_existing_untracked: frozenset[str]
    pre_existing_content: dict[str, str] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "pre_existing_tracked": sorted(self.pre_existing_tracked),
            "pre_existing_untracked": sorted(self.pre_existing_untracked),
            "saved_content_files": sorted(self.pre_existing_content),
            "created_at": self.created_at,
            "label": self.label,
        }


class AutoRollback:
    """Snapshot/restore helper for the autonomous improvement loop."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent.parent
        self._git_available = self._check_git()

    # -- low-level git helpers ----------------------------------------------

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

    def _git(self, *args: str, timeout: int = 20) -> tuple[int, str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_root), *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, (result.stdout or result.stderr or "")
        except Exception as exc:
            return 1, str(exc)

    # -- snapshot / restore ---------------------------------------------------

    def working_tree_changes(self) -> tuple[frozenset[str], frozenset[str]]:
        """Return (dirty tracked paths, untracked paths) relative to the root."""
        code, out = self._git("status", "--porcelain")
        tracked: set[str] = set()
        untracked: set[str] = set()
        if code != 0:
            return frozenset(), frozenset()
        for line in out.splitlines():
            if len(line) < 4:
                continue
            status, path = line[:2], line[3:].strip().strip('"')
            if status.startswith("?"):
                untracked.add(path)
            else:
                tracked.add(path)
        return frozenset(tracked), frozenset(untracked)

    def snapshot(self, label: str = "") -> TreeSnapshot | None:
        """Capture HEAD + the pre-existing dirty set. Never writes anything."""
        if not self._git_available:
            logger.debug("Git not available; snapshot unavailable")
            return None
        code, out = self._git("rev-parse", "HEAD", timeout=5)
        if code != 0:
            logger.warning("Cannot resolve HEAD for snapshot: %s", out.strip()[:120])
            return None
        tracked, untracked = self.working_tree_changes()

        # Keep the user's in-progress content so a rollback can restore it
        # even when the system later edits the same files.
        saved_content: dict[str, str] = {}
        total = 0
        for path in sorted(tracked):
            try:
                raw = (self.repo_root / path).read_bytes()
            except Exception:
                continue
            if len(raw) > TreeSnapshot.MAX_FILE_BYTES:
                continue
            if total + len(raw) > TreeSnapshot.MAX_TOTAL_BYTES:
                logger.warning(
                    "Snapshot content budget reached; %d of %d WIP files saved",
                    len(saved_content),
                    len(tracked),
                )
                break
            total += len(raw)
            saved_content[path] = raw.decode("utf-8", errors="replace")

        snap = TreeSnapshot(
            head=out.strip(),
            pre_existing_tracked=tracked,
            pre_existing_untracked=untracked,
            pre_existing_content=saved_content,
            label=label,
        )
        logger.info(
            "Tree snapshot taken | head=%s | pre_existing=%d tracked (%d saved), %d untracked | label=%s",
            snap.head[:12],
            len(snap.pre_existing_tracked),
            len(saved_content),
            len(snap.pre_existing_untracked),
            label,
        )
        return snap

    def restore(self, snapshot: TreeSnapshot | None) -> RollbackResult:
        """Undo only what the system changed after ``snapshot`` was taken.

        Files dirty before the snapshot are never touched, so concurrent work
        survives a rollback. Returns a RollbackResult with the restored list.
        """
        if not self._git_available:
            return RollbackResult(rolled_back=False, error="Git not available")
        if snapshot is None:
            return RollbackResult(rolled_back=False, error="No snapshot to restore")

        tracked, untracked = self.working_tree_changes()
        system_tracked = tracked - snapshot.pre_existing_tracked
        system_untracked = untracked - snapshot.pre_existing_untracked
        # Pre-existing WIP the system ALSO touched must be reverted to HEAD
        # first (the system's edits ride on top of the user's), then the
        # saved user content is written back over it.
        overlapped = tracked & snapshot.pre_existing_tracked

        restored: list[str] = []
        errors: list[str] = []

        for path in sorted(system_tracked | overlapped):
            code, out = self._git("checkout", "--", path)
            if code != 0:
                errors.append(f"{path}: {out.strip()[:80]}")

        for path, content in snapshot.pre_existing_content.items():
            try:
                target = self.repo_root / path
                if target.exists() or path in overlapped:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # write_bytes, not write_text: the saved content already
                    # carries the file's original line endings and Windows
                    # text mode would translate its \n into a second \r.
                    target.write_bytes(content.encode("utf-8"))
                    restored.append(path)
            except Exception as exc:
                errors.append(f"{path}: {exc}")

        for path in sorted(system_untracked):
            target = self.repo_root / path
            try:
                if target.is_file():
                    target.unlink()
                    restored.append(path)
            except Exception as exc:
                errors.append(f"{path}: {exc}")

        rolled = bool(restored) and not errors
        result = RollbackResult(
            rolled_back=rolled or bool(restored),
            commit_hash=snapshot.head,
            error="; ".join(errors) if errors else None,
            restored_files=restored,
        )
        if restored:
            logger.warning(
                "Rollback restored %d file(s) (incl. %d pre-existing WIP) | label=%s | head=%s",
                len(restored),
                len(snapshot.pre_existing_content),
                snapshot.label,
                snapshot.head[:12],
            )
        if errors:
            logger.error("Rollback partial failures: %s", result.error)
        return result
