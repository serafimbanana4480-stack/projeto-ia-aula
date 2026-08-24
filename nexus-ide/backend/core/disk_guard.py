"""Disk-pressure and process-local runtime ownership guards."""

from __future__ import annotations

import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


_CLEANUP_CATEGORIES = (
    "data/ SQLite databases and stale -wal/-shm files",
    "logs/ rotated or oversized logs",
    ".next* and frontend/.next* build caches",
    "temporary and package-manager cache directories",
)


@dataclass(frozen=True)
class DiskSnapshot:
    path: str
    total_bytes: int
    free_bytes: int
    free_percent: float
    measured_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DiskPressure(StrEnum):
    """Operational disk states used by health, scheduling, and persistence."""

    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


class DiskPressureManager:
    """Classify disk pressure and inventory safe candidates without deleting.

    A warning is observable but permits normal work. Critical pressure blocks
    provider/model allocation and new durable artefacts. Candidate inventory is
    deliberately advisory: cleanup always remains an explicit user action.
    """

    def __init__(
        self,
        *,
        warning_percent: float = 10.0,
        critical_percent: float = 5.0,
    ) -> None:
        if critical_percent < 0 or warning_percent < critical_percent:
            raise ValueError("disk thresholds must satisfy 0 <= critical <= warning")
        self.warning_percent = float(warning_percent)
        self.critical_percent = float(critical_percent)

    def classify(self, snapshot: DiskSnapshot) -> DiskPressure:
        if snapshot.free_percent < self.critical_percent:
            return DiskPressure.CRITICAL
        if snapshot.free_percent < self.warning_percent:
            return DiskPressure.WARNING
        return DiskPressure.NORMAL

    def inspect(self, path: str | Path) -> dict[str, Any]:
        snapshot = measure_disk(path)
        state = self.classify(snapshot)
        return {
            "status": state.value,
            "pressure": state is not DiskPressure.NORMAL,
            "write_blocked": state is DiskPressure.CRITICAL,
            "warning_threshold_percent": self.warning_percent,
            "critical_threshold_percent": self.critical_percent,
            "snapshot": snapshot.to_dict(),
            "candidate_cleanup_categories": list(_CLEANUP_CATEGORIES),
        }

    def candidate_inventory(
        self, root: str | Path, *, max_candidates: int = 32
    ) -> list[dict[str, Any]]:
        """Return existing cleanup candidates and measured shallow sizes."""
        root_path = Path(root)
        names = (
            ".next",
            ".next-dev",
            "frontend/.next",
            "frontend/.next-dev",
            "logs",
            "reports",
            ".pytest_cache",
            "coverage",
        )
        candidates: list[dict[str, Any]] = []
        for relative in names[:max_candidates]:
            candidate = root_path / relative
            if not candidate.exists():
                continue
            size = 0
            try:
                if candidate.is_file():
                    size = candidate.stat().st_size
                else:
                    for item in candidate.rglob("*"):
                        if item.is_file():
                            try:
                                size += item.stat().st_size
                            except OSError:
                                continue
            except OSError:
                continue
            candidates.append({"path": str(candidate), "size_bytes": size})
        return candidates


class DiskPressureError(RuntimeError):
    """Raised when a write or run would proceed below the disk reserve."""

    def __init__(self, snapshot: DiskSnapshot, threshold_percent: float) -> None:
        self.snapshot = snapshot
        self.threshold_percent = threshold_percent
        self.candidate_cleanup_categories = _CLEANUP_CATEGORIES
        self.remediation = (
            "Free space without deleting automatically. Candidate cleanup categories: "
            + "; ".join(self.candidate_cleanup_categories)
        )
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        return (
            f"Disk headroom is below threshold for {self.snapshot.path}: "
            f"free_bytes={self.snapshot.free_bytes}, "
            f"free_percent={self.snapshot.free_percent:.2f}%, "
            f"threshold_percent={self.threshold_percent:.2f}%. "
            f"{self.remediation}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "critical",
            "pressure": True,
            "write_blocked": True,
            "path": self.snapshot.path,
            "free_bytes": self.snapshot.free_bytes,
            "free_percent": self.snapshot.free_percent,
            "threshold_percent": self.threshold_percent,
            "candidate_cleanup_categories": list(self.candidate_cleanup_categories),
            "remediation": self.remediation,
        }


def measure_disk(path: str | Path) -> DiskSnapshot:
    """Measure a volume without mutating it."""
    target = Path(path)
    usage = shutil.disk_usage(target)
    total = int(usage.total)
    free = int(usage.free)
    free_percent = (free / total * 100.0) if total else 0.0
    return DiskSnapshot(
        path=str(target),
        total_bytes=total,
        free_bytes=free,
        free_percent=free_percent,
        measured_at=datetime.now(UTC).isoformat(),
    )


def require_disk_headroom(
    path: str | Path,
    threshold_percent: float = 5.0,
) -> DiskSnapshot:
    """Return a snapshot or fail before allocating a provider or writing data."""
    if threshold_percent < 0:
        raise ValueError("threshold_percent must be non-negative")
    snapshot = measure_disk(path)
    if snapshot.free_percent < threshold_percent:
        raise DiskPressureError(snapshot, threshold_percent)
    return snapshot


def disk_pressure_status(
    path: str | Path,
    threshold_percent: float = 5.0,
) -> dict[str, Any]:
    """Return a non-raising health payload for the current volume."""
    try:
        snapshot = measure_disk(path)
    except OSError as exc:
        return {
            "status": "unknown",
            "pressure": None,
            "error": str(exc),
            "threshold_percent": threshold_percent,
        }
    manager = DiskPressureManager(critical_percent=threshold_percent)
    payload = manager.inspect(path)
    payload["threshold_percent"] = threshold_percent
    payload["legacy_status"] = "pressure" if payload["pressure"] else "ok"
    return payload


class WorkerOwnershipGuard:
    """Process-local ownership tokens shared by independently-created guards."""

    _owners: set[str] = set()
    _lock = threading.RLock()

    def acquire(self, name: str) -> bool:
        """Claim ``name`` once; duplicate claims are rejected without side effects."""
        if not name:
            raise ValueError("worker name must not be empty")
        with self._lock:
            if name in self._owners:
                return False
            self._owners.add(name)
            return True

    def release(self, name: str) -> None:
        """Release a claim; releasing an unknown name is intentionally idempotent."""
        with self._lock:
            self._owners.discard(name)

    @classmethod
    def release_all(cls) -> None:
        with cls._lock:
            cls._owners.clear()
