"""Rollback — automatic revert on production degradation.

FASE 9. If a promoted champion starts failing in production (detected via
trace lake metrics or RegressionGuard violations), the Rollback manager
archives the failing version and restores the previous champion.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from backend.evolution.registry import (
    ChampionRegistry,
    ComponentStatus,
    ComponentVersion,
    _utcnow_iso,
)

logger = logging.getLogger(__name__)


# ── Snapshot exceptions ──────────────────────────────────────────────────────

class SnapshotError(Exception):
    """Base error for snapshot operations."""


class SnapshotNotFoundError(SnapshotError):
    """The requested snapshot id does not exist (active or archived)."""


class SnapshotCorruptedError(SnapshotError):
    """A snapshot failed integrity verification (hash/manifest mismatch)."""


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (temp file + os.replace).

    A crash mid-write leaves the previous file intact and, at worst, a
    stray ``*.tmp`` sibling that the next write replaces.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


@dataclass
class SnapshotManifest:
    """Metadata recorded for a single snapshot."""

    snapshot_id: str
    created_at: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)  # relpath → sha256


@dataclass
class RollbackEvent:
    """Record of a rollback action."""

    component_kind: str
    from_version: str     # version that was rolled back (the bad champion)
    to_version: str       # version restored (the previous champion)
    reason: str
    timestamp: str
    metrics_before: dict[str, Any]
    metrics_after: dict[str, Any] | None = None


class RollbackManager:
    """Monitors production health and reverts bad promotions.

    Usage:
        rollback = RollbackManager(registry)
        if rollback.should_rollback("planner", metrics):
            rollback.execute_rollback("planner", reason="...")
    """

    # Thresholds for triggering rollback
    SUCCESS_RATE_DROP_THRESHOLD: float = 0.15  # 15% drop from baseline
    REGRESSION_RATE_THRESHOLD: float = 0.10    # 10% tasks regressed
    SCORE_DROP_THRESHOLD: float = 0.20         # 20% score drop
    MIN_TASKS_FOR_ROLLBACK: int = 10           # minimum tasks to trigger

    def __init__(self, registry: ChampionRegistry) -> None:
        self._registry = registry

    def evaluate_health(
        self,
        component_kind: str,
        current_metrics: dict[str, Any],
        baseline_metrics: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Evaluate whether the current champion is healthy.

        Args:
            component_kind: The component to check.
            current_metrics: Recent metrics (last N tasks).
            baseline_metrics: Baseline metrics for comparison (champion's stored metrics or historical).

        Returns:
            (should_rollback, reason)
        """
        if not baseline_metrics:
            champion = self._registry.get_champion(component_kind)
            if champion is None:
                return False, "No champion found"
            baseline_metrics = champion.metrics

        current_success = current_metrics.get("success_rate", 0.0)
        baseline_success = baseline_metrics.get("success_rate", 0.0)
        current_score = current_metrics.get("avg_score", 0.0)
        baseline_score = baseline_metrics.get("avg_score", 0.0)
        regression_rate = current_metrics.get("regression_rate", 0.0)
        task_count = current_metrics.get("total_tasks", 0)

        if task_count < self.MIN_TASKS_FOR_ROLLBACK:
            return False, f"Insufficient data ({task_count} tasks, need {self.MIN_TASKS_FOR_ROLLBACK})"

        # Check success rate drop
        if baseline_success > 0:
            drop = (baseline_success - current_success) / baseline_success
            if drop > self.SUCCESS_RATE_DROP_THRESHOLD:
                return True, (
                    f"Success rate dropped {drop:.1%} "
                    f"(from {baseline_success:.3f} to {current_success:.3f})"
                )

        # Check regression rate
        if regression_rate > self.REGRESSION_RATE_THRESHOLD:
            return True, f"Regression rate {regression_rate:.1%} exceeds threshold {self.REGRESSION_RATE_THRESHOLD:.1%}"

        # Check score drop
        if baseline_score > 0:
            drop = (baseline_score - current_score) / baseline_score
            if drop > self.SCORE_DROP_THRESHOLD:
                return True, (
                    f"Score dropped {drop:.1%} "
                    f"(from {baseline_score:.3f} to {current_score:.3f})"
                )

        return False, "Champion healthy"

    def should_rollback(
        self,
        component_kind: str,
        current_metrics: dict[str, Any],
    ) -> tuple[bool, str]:
        """Check if the current champion should be rolled back."""
        champion = self._registry.get_champion(component_kind)
        if champion is None:
            return False, "No champion"

        previous = self._find_previous_champion(component_kind, champion.version)
        if previous is None:
            return False, "No previous champion available for rollback"

        return self.evaluate_health(component_kind, current_metrics, champion.metrics)

    def execute_rollback(
        self,
        component_kind: str,
        reason: str = "",
    ) -> RollbackEvent | None:
        """Rollback to the previous champion version.

        Archives the current champion and restores the previous one.
        """
        champion = self._registry.get_champion(component_kind)
        if champion is None:
            logger.warning(f"Cannot rollback {component_kind}: no champion found")
            return None

        previous = self._find_previous_champion(component_kind, champion.version)
        if previous is None:
            logger.warning(
                f"Cannot rollback {component_kind}: no previous champion available"
            )
            return None

        # Archive the failing champion
        self._registry.archive(component_kind, champion.version)

        # Restore previous champion
        self._registry.promote(component_kind, previous.version, changelog=f"Rollback: {reason}")

        event = RollbackEvent(
            component_kind=component_kind,
            from_version=champion.version,
            to_version=previous.version,
            reason=reason or "Unspecified degradation detected",
            timestamp=_utcnow_iso(),
            metrics_before=champion.metrics,
            metrics_after=previous.metrics,
        )

        # Log the rollback event
        import uuid

        from backend.evolution.registry import _connect
        conn = _connect(self._registry.db_path)
        try:
            conn.execute(
                "INSERT INTO evolution_log "
                "(id, experiment_id, event_type, component_kind, version, message, metrics_json, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"log-{uuid.uuid4().hex[:8]}",
                    None,
                    "rolled_back",
                    component_kind,
                    champion.version,
                    reason,
                    _utcnow_iso(),
                    _utcnow_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info(
            f"Rollback executed: {component_kind} {champion.version} -> {previous.version} "
            f"(reason: {reason})"
        )
        return event

    def _find_previous_champion(
        self,
        component_kind: str,
        current_version: str,
    ) -> ComponentVersion | None:
        """Find the champion version that was active before the current one."""
        archived = self._registry.list_versions(
            component_kind, status=ComponentStatus.ARCHIVED.value
        )

        # Sort by promoted_at descending to find most recent previous champion
        archived_with_promotions = [v for v in archived if v.promoted_at]
        if not archived_with_promotions:
            return None
        archived_with_promotions.sort(key=lambda v: v.promoted_at or "", reverse=True)
        return archived_with_promotions[0]

    def get_rollback_history(self, component_kind: str) -> list[dict[str, Any]]:
        """Get the rollback history for a component (or all if 'all')."""
        import sqlite3
        conn = sqlite3.connect(str(self._registry.db_path))
        conn.row_factory = sqlite3.Row
        try:
            if component_kind and component_kind != "all":
                rows = conn.execute(
                    "SELECT * FROM evolution_log WHERE component_kind = ? AND event_type = 'rolled_back' "
                    "ORDER BY timestamp DESC",
                    (component_kind,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evolution_log WHERE event_type = 'rolled_back' "
                    "ORDER BY timestamp DESC",
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ── SnapshotManager ──────────────────────────────────────────────────────────

class SnapshotManager:
    """Filesystem-backed safety snapshots with hash verification.

    Layout:
        <root>/<snapshot_id>/manifest.json   — SnapshotManifest JSON
        <root>/<snapshot_id>/data/<relpath>  — file contents
        <root>/archive/<snapshot_id>/…       — pruned (kept, never deleted)

    Manifests are written atomically and record the SHA-256 of every file
    so :meth:`verify_snapshot` and :meth:`restore_snapshot` can refuse
    tampered or incomplete snapshots.
    """

    DEFAULT_KEEP = 20

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.archive_dir = self.root / "archive"

    # ── Helpers ──

    @staticmethod
    def _as_bytes(content: str | bytes) -> bytes:
        return content.encode("utf-8") if isinstance(content, str) else content

    @staticmethod
    def _validate_relpath(relpath: str) -> None:
        """Reject absolute paths, ``..`` escapes and empty names."""
        pure = PurePosixPath(relpath.replace("\\", "/"))
        if not relpath or not pure.parts:
            raise ValueError(f"Unsafe snapshot path: {relpath!r}")
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Unsafe snapshot path: {relpath!r}")

    def _snapshot_dir(self, snapshot_id: str) -> Path | None:
        """Locate a snapshot dir in the active root or the archive."""
        active = self.root / snapshot_id
        if active.is_dir():
            return active
        archived = self.archive_dir / snapshot_id
        if archived.is_dir():
            return archived
        return None

    @staticmethod
    def _manifest_payload(manifest: SnapshotManifest) -> dict[str, Any]:
        return {
            "snapshot_id": manifest.snapshot_id,
            "created_at": manifest.created_at,
            "reason": manifest.reason,
            "metadata": manifest.metadata,
            "files": manifest.files,
        }

    def _read_manifest(self, snapshot_id: str) -> SnapshotManifest | None:
        """Load a manifest, or None when unreadable/missing."""
        snap_dir = self._snapshot_dir(snapshot_id)
        if snap_dir is None:
            return None
        mpath = snap_dir / "manifest.json"
        try:
            payload = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return SnapshotManifest(
            snapshot_id=payload.get("snapshot_id", snapshot_id),
            created_at=payload.get("created_at", ""),
            reason=payload.get("reason", ""),
            metadata=payload.get("metadata") or {},
            files=payload.get("files") or {},
        )

    # ── Public API ──

    def create_snapshot(
        self,
        files: dict[str, str | bytes],
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        snapshot_id: str | None = None,
    ) -> SnapshotManifest:
        """Create a new snapshot from ``files`` (relpath → str | bytes).

        Raises:
            ValueError: on an empty file set or an unsafe relative path.
            SnapshotError: on a duplicate explicit ``snapshot_id``.
        """
        if not files:
            raise ValueError("Cannot create an empty snapshot")

        for relpath in files:
            self._validate_relpath(relpath)

        sid = snapshot_id or f"snap-{uuid.uuid4().hex[:12]}"
        snap_dir = self.root / sid
        if snapshot_id is not None and snap_dir.exists():
            raise SnapshotError(f"Snapshot id already exists: {sid}")

        hashes: dict[str, str] = {}
        for relpath, content in files.items():
            data = self._as_bytes(content)
            hashes[relpath] = hashlib.sha256(data).hexdigest()
            target = snap_dir / "data" / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(target, data)

        manifest = SnapshotManifest(
            snapshot_id=sid,
            created_at=_utcnow_iso(),
            reason=reason,
            metadata=dict(metadata or {}),
            files=hashes,
        )
        manifest_path = snap_dir / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(
            manifest_path,
            json.dumps(self._manifest_payload(manifest), indent=2, sort_keys=True).encode("utf-8"),
        )
        logger.info("Created snapshot %s (%d files, reason: %s)", sid, len(files), reason)
        return manifest

    def verify_snapshot(self, snapshot_id: str) -> list[str]:
        """Return a list of integrity problems (empty list = intact)."""
        snap_dir = self._snapshot_dir(snapshot_id)
        if snap_dir is None:
            return [f"snapshot '{snapshot_id}' not found"]

        mpath = snap_dir / "manifest.json"
        try:
            payload = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [f"snapshot '{snapshot_id}': invalid manifest"]

        problems: list[str] = []
        files = payload.get("files") or {}
        for relpath in sorted(files):
            expected = files[relpath]
            fpath = snap_dir / "data" / relpath
            if not fpath.is_file():
                problems.append(f"missing file: {relpath}")
                continue
            actual = hashlib.sha256(fpath.read_bytes()).hexdigest()
            if actual != expected:
                problems.append(
                    f"hash mismatch for {relpath}: expected {expected}, got {actual}"
                )
        return problems

    def get_manifest(self, snapshot_id: str) -> SnapshotManifest:
        """Load a snapshot manifest.

        Raises:
            SnapshotNotFoundError: unknown snapshot id.
            SnapshotCorruptedError: manifest exists but is unreadable.
        """
        snap_dir = self._snapshot_dir(snapshot_id)
        if snap_dir is None:
            raise SnapshotNotFoundError(f"snapshot '{snapshot_id}' not found")
        manifest = self._read_manifest(snapshot_id)
        if manifest is None:
            raise SnapshotCorruptedError(
                f"snapshot '{snapshot_id}': invalid manifest"
            )
        return manifest

    def restore_snapshot(self, snapshot_id: str, target_dir: str | Path) -> Path:
        """Restore snapshot files into ``target_dir`` (idempotent).

        Files whose on-disk content already matches the manifest hashes are
        left untouched, so a repeated restore performs no writes at all.
        Corrupted snapshots are refused *before* anything is written.
        """
        snap_dir = self._snapshot_dir(snapshot_id)
        if snap_dir is None:
            raise SnapshotNotFoundError(f"snapshot '{snapshot_id}' not found")

        problems = self.verify_snapshot(snapshot_id)
        if problems:
            raise SnapshotCorruptedError(
                f"snapshot '{snapshot_id}' is corrupted: {problems}"
            )

        manifest = self._read_manifest(snapshot_id)
        assert manifest is not None
        target = Path(target_dir)
        for relpath in sorted(manifest.files):
            source = snap_dir / "data" / relpath
            dest = target / relpath
            if dest.is_file() and (
                hashlib.sha256(dest.read_bytes()).hexdigest()
                == manifest.files[relpath]
            ):
                continue  # already correct: pure no-op
            dest.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(dest, source.read_bytes())
        logger.info("Restored snapshot %s into %s", snapshot_id, target)
        return target

    def list_snapshots(self, include_archived: bool = False) -> list[SnapshotManifest]:
        """List manifests ordered by ``created_at`` (oldest first)."""
        manifests: list[SnapshotManifest] = []

        def _collect(base: Path) -> None:
            if not base.is_dir():
                return
            for entry in base.iterdir():
                if not entry.is_dir() or entry.name == "archive":
                    continue
                manifest = self._read_manifest(entry.name)
                if manifest is not None:
                    manifests.append(manifest)

        _collect(self.root)
        if include_archived:
            _collect(self.archive_dir)
        manifests.sort(key=lambda m: (m.created_at, m.snapshot_id))
        return manifests

    def prune_snapshots(self, keep: int = DEFAULT_KEEP) -> list[str]:
        """Archive the oldest snapshots beyond ``keep``. Never deletes.

        Returns the snapshot ids that were moved to the archive, oldest first.
        """
        manifests = self.list_snapshots()
        if len(manifests) <= keep:
            return []

        to_archive = manifests[: len(manifests) - keep]
        archived_ids: list[str] = []
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        for manifest in to_archive:
            src = self.root / manifest.snapshot_id
            dest = self.archive_dir / manifest.snapshot_id
            if src.is_dir() and not dest.exists():
                shutil.move(str(src), str(dest))
                archived_ids.append(manifest.snapshot_id)
        if archived_ids:
            logger.info(
                "Pruned %d snapshots to archive (keep=%d)", len(archived_ids), keep
            )
        return archived_ids
