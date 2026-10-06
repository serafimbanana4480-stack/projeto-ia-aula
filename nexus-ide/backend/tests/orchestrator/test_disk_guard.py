from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import disk_guard
from backend.core.disk_guard import (
    DEFAULT_DISK_HEADROOM_PERCENT,
    DISK_GUARD_MIN_PERCENT_ENV,
    DiskPressure,
    DiskPressureError,
    DiskPressureManager,
    disk_headroom_threshold,
    measure_disk,
    require_disk_headroom,
)


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


def test_headroom_gate_rejects_before_provider_creation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Pin the documented production floor. The global conftest sets
    # NEXUS_DISK_GUARD_MIN_PERCENT=0 so the suite is hermetic, which would
    # otherwise mask this assertion entirely.
    monkeypatch.setenv(DISK_GUARD_MIN_PERCENT_ENV, "5")
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
    assert raised.value.threshold_percent == pytest.approx(5.0)
    assert "cleanup" in str(raised.value).lower()


def test_headroom_gate_allows_above_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DISK_GUARD_MIN_PERCENT_ENV, "5")
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 51))

    snapshot = require_disk_headroom(tmp_path)

    assert snapshot.free_percent == pytest.approx(5.1)


def test_production_default_threshold_is_5_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env override must not have moved the production default."""
    monkeypatch.delenv(DISK_GUARD_MIN_PERCENT_ENV, raising=False)

    assert DEFAULT_DISK_HEADROOM_PERCENT == 5.0
    assert disk_headroom_threshold() == pytest.approx(5.0)


def test_env_var_overrides_threshold_and_is_read_at_call_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Call-time resolution is what lets a test change the floor mid-process."""
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 49))
    monkeypatch.setenv(DISK_GUARD_MIN_PERCENT_ENV, "10")

    assert disk_headroom_threshold() == pytest.approx(10.0)
    with pytest.raises(DiskPressureError) as raised:
        require_disk_headroom(tmp_path)
    assert raised.value.threshold_percent == pytest.approx(10.0)

    # Lowering it in the same process must immediately take effect.
    monkeypatch.setenv(DISK_GUARD_MIN_PERCENT_ENV, "0")
    assert require_disk_headroom(tmp_path).free_percent == pytest.approx(4.9)


def test_explicit_argument_beats_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DISK_GUARD_MIN_PERCENT_ENV, "0")
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 49))

    with pytest.raises(DiskPressureError) as raised:
        require_disk_headroom(tmp_path, 5.0)

    assert raised.value.threshold_percent == pytest.approx(5.0)


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not-a-number", "-1", "nan", "inf-negative"],
)
def test_malformed_env_value_falls_back_to_production_default(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """A typo in a deployment variable must not take the orchestrator down."""
    monkeypatch.setenv(DISK_GUARD_MIN_PERCENT_ENV, raw)

    resolved = disk_headroom_threshold()

    assert resolved == pytest.approx(DEFAULT_DISK_HEADROOM_PERCENT)


def test_disk_pressure_status_reports_env_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 49))
    monkeypatch.setenv(DISK_GUARD_MIN_PERCENT_ENV, "25")

    payload = disk_guard.disk_pressure_status(tmp_path)

    assert payload["threshold_percent"] == pytest.approx(25.0)
    assert payload["status"] == DiskPressure.CRITICAL.value
    assert payload["write_blocked"] is True


def test_disk_pressure_manager_has_normal_warning_critical_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = DiskPressureManager(warning_percent=10, critical_percent=5)

    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 120))
    assert manager.inspect(tmp_path)["status"] == DiskPressure.NORMAL.value
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 80))
    assert manager.inspect(tmp_path)["status"] == DiskPressure.WARNING.value
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda path: _Usage(1_000, 40))
    critical = manager.inspect(tmp_path)
    assert critical["status"] == DiskPressure.CRITICAL.value
    assert critical["write_blocked"] is True


def test_candidate_inventory_is_advisory_and_does_not_delete(tmp_path: Path) -> None:
    cache = tmp_path / ".next"
    cache.mkdir()
    (cache / "bundle.js").write_text("x", encoding="utf-8")

    candidates = DiskPressureManager().candidate_inventory(tmp_path)

    assert candidates == [{"path": str(cache), "size_bytes": 1}]
    assert (cache / "bundle.js").exists()
