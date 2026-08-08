"""Disk-pressure and process-local runtime ownership guards."""

from __future__ import annotations

import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
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
    return {
        "status": "pressure" if snapshot.free_percent < threshold_percent else "ok",
        "pressure": snapshot.free_percent < threshold_percent,
        "threshold_percent": threshold_percent,
        "snapshot": snapshot.to_dict(),
    }


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
