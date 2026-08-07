"""Regression tests for the bounded quality signal used by auto-correction."""

from __future__ import annotations

import pytest

from backend.core import quality_metrics as qm


@pytest.mark.asyncio
async def test_lightweight_measurement_avoids_commands_and_uses_cache(tmp_path, monkeypatch) -> None:
    """The event-path metric must not run pytest, ruff, or another subprocess."""
    (tmp_path / "sample.py").write_text(
        "def useful(value: int) -> int:\n"
        "    if value > 0:\n"
        "        return value\n"
        "    return 0\n",
        encoding="utf-8",
    )
    qm.invalidate_lightweight_cache(tmp_path)

    calls = 0
    original_measure = qm._measure_lightweight_sync

    def counted_measure(root, max_files):
        nonlocal calls
        calls += 1
        return original_measure(root, max_files)

    def unexpected_command(*args, **kwargs):
        pytest.fail("lightweight quality measurement must not spawn a command")

    monkeypatch.setattr(qm, "_measure_lightweight_sync", counted_measure)
    monkeypatch.setattr(qm, "_run_cmd", unexpected_command)

    first = await qm.measure_lightweight(tmp_path, cache_ttl_seconds=60)
    second = await qm.measure_lightweight(tmp_path, cache_ttl_seconds=60)

    assert calls == 1
    assert first is not second
    assert first.cyclomatic_complexity > 0
    assert second.cyclomatic_complexity == first.cyclomatic_complexity

    qm.invalidate_lightweight_cache(tmp_path)
    await qm.measure_lightweight(tmp_path, cache_ttl_seconds=60)
    assert calls == 2
