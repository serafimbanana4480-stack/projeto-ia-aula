"""Bounded log rotation for ``logs/backend.log`` (audit P1-8).

``logs/`` held 299 files / 49 MB with no rotation handler at all, on a volume
that is at 0.7% free.  Rotation has to be bounded on **two** axes: a single
huge file exhausts the disk just as fast as thousands of small ones, and
``RotatingFileHandler`` only bounds the first.

:class:`NexusRotatingFileHandler` is a size-rotating handler that also enforces a
total-bytes cap by evicting the oldest rotated files first.  Rotation failures
are swallowed (never propagated into an application ``emit``) so a full or
read-only disk degrades to "less logging", not "the IDE crashes on every log
line".
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import os
from pathlib import Path

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
DEFAULT_MAX_TOTAL_BYTES = 100 * 1024 * 1024

_SIZE_UNITS = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}


def parse_size(raw: str | None, default: int) -> int:
    """Parse ``"25MB"`` / ``"10485760"`` / ``""`` into a byte count."""
    if raw is None:
        return default
    value = str(raw).strip().upper()
    if not value:
        return default
    for suffix, multiplier in _SIZE_UNITS.items():
        if value.endswith(suffix):
            number = value[: -len(suffix)].strip()
            try:
                return max(1, int(float(number) * multiplier))
            except ValueError:
                return default
    try:
        return max(1, int(float(value)))
    except ValueError:
        return default


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(float(raw)))
    except ValueError:
        logging.getLogger(__name__).warning("Invalid %s=%r — using %d", name, raw, default)
        return default


class NexusRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """``RotatingFileHandler`` + a total-size cap across all rotated files."""

    def __init__(
        self,
        filename: str | os.PathLike[str],
        *,
        max_bytes: int | None = None,
        backup_count: int | None = None,
        max_total_bytes: int | None = None,
        encoding: str = "utf-8",
        **kwargs: object,
    ) -> None:
        self.max_bytes = max_bytes if max_bytes is not None else parse_size(
            os.environ.get("NEXUS_LOG_MAX_BYTES"), DEFAULT_MAX_BYTES
        )
        self.backup_count = backup_count if backup_count is not None else _env_int(
            "NEXUS_LOG_BACKUP_COUNT", DEFAULT_BACKUP_COUNT
        )
        self.max_total_bytes = (
            max_total_bytes
            if max_total_bytes is not None
            else parse_size(os.environ.get("NEXUS_LOG_MAX_TOTAL_BYTES"), DEFAULT_MAX_TOTAL_BYTES)
        )
        super().__init__(
            str(filename),
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding=encoding,
            # Keep the file unopened until the first record so importing the
            # module never creates a 0-byte log on a read-only checkout.
            delay=kwargs.pop("delay", True),
            **kwargs,  # type: ignore[arg-type]
        )

    def doRollover(self) -> None:  # noqa: N802 — stdlib naming
        try:
            super().doRollover()
        except (OSError, ValueError) as exc:  # pragma: no cover - full/read-only disk
            # Never propagate out of ``emit``: a log line must not take the app
            # down.  Leaving the old file in place is the safest degradation.
            logging.getLogger(__name__).warning("Log rollover failed: %s", exc)
            return
        self.enforce_total_cap()

    def enforce_total_cap(self) -> int:
        """Delete the oldest rotated files until the total fits the cap.

        Returns the number of files removed.
        """
        if self.max_total_bytes <= 0:
            return 0
        base = Path(self.baseFilename)
        parent = base.parent
        if not parent.is_dir():
            return 0

        try:
            rotated = sorted(
                (p for p in parent.glob(f"{base.name}.*") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
            )
        except OSError:  # pragma: no cover - unreadable directory
            return 0

        total = 0
        sizes: dict[Path, int] = {}
        for path in rotated:
            try:
                size = path.stat().st_size
            except OSError:  # pragma: no cover - race with rotation
                continue
            sizes[path] = size
            total += size
        with contextlib.suppress(OSError):  # pragma: no cover
            total += base.stat().st_size

        removed = 0
        for path in rotated:
            if total <= self.max_total_bytes:
                break
            try:
                size = sizes.get(path, 0)
                path.unlink()
            except OSError:  # pragma: no cover - race / permissions
                continue
            total -= size
            removed += 1
        if removed:
            logging.getLogger(__name__).info(
                "Log rotation evicted %d old file(s); total now under %d bytes",
                removed,
                self.max_total_bytes,
            )
        return removed


def add_rotating_file_handler(
    root_logger: logging.Logger,
    log_file: str | os.PathLike[str],
    *,
    formatter: logging.Formatter | None = None,
) -> NexusRotatingFileHandler:
    """Install (and return) the rotating file handler on *root_logger*."""
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = NexusRotatingFileHandler(path, delay=True)
    if formatter is not None:
        handler.setFormatter(formatter)
    handler._nexus_owned = True  # type: ignore[attr-defined]
    root_logger.addHandler(handler)
    return handler
