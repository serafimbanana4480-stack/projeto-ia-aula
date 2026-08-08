from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import disk_guard
from backend.core.disk_guard import DiskPressureError, measure_disk, require_disk_headroom


class _Usage:
    def __init__(self, total: int, free: int) -> None:
        self.total = total
        self.free = free
        self.used = total - free


def test_measure_disk_reports_utc_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 510))

    snapshot = measure_disk(tmp_path)

    assert snapshot.path == str(tmp_path)
    assert snapshot.total_bytes == 1_000
    assert snapshot.free_bytes == 510
    assert snapshot.free_percent == pytest.approx(51.0)
    assert snapshot.measured_at.endswith("+00:00")


def test_headroom_gate_rejects_before_provider_creation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 49))
    provider_calls: list[str] = []

    def provider_factory() -> object:
        provider_calls.append("created")
        return object()

    with pytest.raises(DiskPressureError) as raised:
        require_disk_headroom(tmp_path)
        provider_factory()

    assert provider_calls == []
    assert raised.value.snapshot.free_percent == pytest.approx(4.9)
    assert "cleanup" in str(raised.value).lower()


def test_headroom_gate_allows_above_threshold(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 51))

    snapshot = require_disk_headroom(tmp_path)

    assert snapshot.free_percent == pytest.approx(5.1)
