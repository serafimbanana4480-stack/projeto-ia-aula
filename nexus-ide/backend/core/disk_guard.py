"""Disk-pressure and process-local runtime ownership guards.

Configuration
-------------
``NEXUS_DISK_GUARD_MIN_PERCENT``
    Minimum free-disk percentage (0-100) required before a provider is
    allocated or a durable artefact is written. Read at *call time* -- not at
    import time -- so a test or an operator can change it for a live process
    via ``os.environ``/``monkeypatch.setenv``. An explicit ``threshold_percent``
    argument always wins over the environment. A missing, empty, malformed, or
    negative value falls back to :data:`DEFAULT_DISK_HEADROOM_PERCENT`, so the
    production default is unchanged: **5.0 percent**.

    The test suite sets this to ``0`` in ``backend/tests/conftest.py`` so the
    suite is hermetic and does not inherit the developer's free-disk state.
    Production never sets it; do not lower it outside tests.
"""

from __future__ import annotations

import math
import os
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

#: Environment variable that overrides the minimum free-disk percentage.
DISK_GUARD_MIN_PERCENT_ENV = "NEXUS_DISK_GUARD_MIN_PERCENT"

#: Production default minimum free-disk percentage. Production behaviour is
#: identical whether or not the environment variable is set.
DEFAULT_DISK_HEADROOM_PERCENT = 5.0

#: Free-disk percentage at which pressure becomes observable but non-blocking.
DEFAULT_WARNING_PERCENT = 10.0

_CLEANUP_CATEGORIES = (
    "data/ SQLite databases and stale -wal/-shm files",
    "logs/ rotated or oversized logs",
    ".next* and frontend/.next* build caches",
    "temporary and package-manager cache directories",
)


def disk_headroom_threshold() -> float:
    """Resolve the minimum free-disk percentage from the environment.

    This is the single place ``NEXUS_DISK_GUARD_MIN_PERCENT`` is read. A
    missing, blank, non-numeric, or negative value yields
    :data:`DEFAULT_DISK_HEADROOM_PERCENT` rather than raising, because a typo in
    a deployment variable must not take the orchestrator down. It deliberately
    does not ``warnings.warn``: the project runs pytest with
    ``filterwarnings = ["error", ...]``, which would turn a configuration typo
    into a hard test failure.
    """
    raw = os.environ.get(DISK_GUARD_MIN_PERCENT_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_DISK_HEADROOM_PERCENT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_DISK_HEADROOM_PERCENT
    if value < 0 or not math.isfinite(value):
        return DEFAULT_DISK_HEADROOM_PERCENT
    return value


def _resolve_threshold(threshold_percent: float | None) -> float:
    """Return the explicit threshold, or the environment-resolved default."""
    if threshold_percent is None:
        return disk_headroom_threshold()
    return float(threshold_percent)


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
        warning_percent: float = DEFAULT_WARNING_PERCENT,
        critical_percent: float = DEFAULT_DISK_HEADROOM_PERCENT,
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
    threshold_percent: float | None = None,
) -> DiskSnapshot:
    """Return a snapshot or fail before allocating a provider or writing data.

    ``threshold_percent`` defaults to :func:`disk_headroom_threshold`, i.e.
    ``NEXUS_DISK_GUARD_MIN_PERCENT`` falling back to
    :data:`DEFAULT_DISK_HEADROOM_PERCENT` (5.0). Pass a value explicitly to
    override both.
    """
    threshold = _resolve_threshold(threshold_percent)
    if threshold < 0:
        raise ValueError("threshold_percent must be non-negative")
    snapshot = measure_disk(path)
    if snapshot.free_percent < threshold:
        raise DiskPressureError(snapshot, threshold)
    return snapshot


def disk_pressure_status(
    path: str | Path,
    threshold_percent: float | None = None,
) -> dict[str, Any]:
    """Return a non-raising health payload for the current volume.

    ``threshold_percent`` defaults to :func:`disk_headroom_threshold`; see
    :func:`require_disk_headroom`.
    """
    threshold = _resolve_threshold(threshold_percent)
    try:
        measure_disk(path)
    except OSError as exc:
        return {
            "status": "unknown",
            "pressure": None,
            "error": str(exc),
            "threshold_percent": threshold,
        }
    # ``warning_percent`` must be >= ``critical_percent``. A configured floor
    # above the 10% default would otherwise raise ValueError from a *health*
    # endpoint, turning a config typo into a 500. Clamping keeps the ordering
    # invariant without silently rejecting the operator's value.
    manager = DiskPressureManager(
        warning_percent=max(DEFAULT_WARNING_PERCENT, threshold),
        critical_percent=threshold,
    )
    payload = manager.inspect(path)
    payload["threshold_percent"] = threshold
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
