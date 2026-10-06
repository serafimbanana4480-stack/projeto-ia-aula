"""Performance/behaviour tests for the non-blocking project analyzer.

Covers: event-loop responsiveness under heavy analysis, TTL cache hits,
TTL expiry, single-flight concurrency and deterministic stress stability.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from backend.tools.project_analyzer import (
    _cache_stats,
    _reset_analyze_cache,
    analyze_project,
)


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    monkeypatch.setenv("NEXUS_ANALYZE_CACHE_TTL", "30")
    _reset_analyze_cache()
    yield
    _reset_analyze_cache()


def _build_tree(root: Path, n_dirs: int, n_files_per_dir: int) -> None:
    for d in range(n_dirs):
        pkg = root / f"pkg_{d}"
        pkg.mkdir(exist_ok=True)
        for f in range(n_files_per_dir):
            (pkg / f"mod_{f}.py").write_text("value = 1\n", encoding="utf-8")


async def test_event_loop_responsive_during_large_analysis(tmp_path):
    _build_tree(tmp_path, n_dirs=40, n_files_per_dir=50)

    analysis = asyncio.create_task(analyze_project(project_path=str(tmp_path)))
    ticks = 0
    while not analysis.done():
        await asyncio.sleep(0)
        ticks += 1
    result = await analysis

    assert "error" not in result
    assert result["total_files"] >= 2000
    assert ticks > 500


async def test_cache_hit_identical_and_faster(tmp_path):
    _build_tree(tmp_path, n_dirs=16, n_files_per_dir=50)

    start = time.perf_counter()
    first = await analyze_project(project_path=str(tmp_path))
    cold_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    second = await analyze_project(project_path=str(tmp_path))
    warm_ms = (time.perf_counter() - start) * 1000

    assert "error" not in first
    assert second == first
    stats = _cache_stats()
    assert stats["computes"] == 1
    assert stats["hits"] == 1
    assert warm_ms < cold_ms / 4


async def test_ttl_expiry_recomputes(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_ANALYZE_CACHE_TTL", "0.05")
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")

    first = await analyze_project(project_path=str(tmp_path))
    assert _cache_stats()["computes"] == 1

    await asyncio.sleep(0.15)
    second = await analyze_project(project_path=str(tmp_path))

    assert first == second
    assert "error" not in second
    assert _cache_stats()["computes"] == 2


async def test_concurrent_calls_compute_once(tmp_path):
    _build_tree(tmp_path, n_dirs=4, n_files_per_dir=10)

    results = await asyncio.gather(
        *(analyze_project(project_path=str(tmp_path)) for _ in range(50))
    )

    assert len(results) == 50
    assert all(result == results[0] for result in results)
    assert "error" not in results[0]
    stats = _cache_stats()
    assert stats["computes"] == 1
    assert len({id(r) for r in results}) == 50


async def test_stress_repeated_small_analysis_stable(tmp_path):
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# stress\n", encoding="utf-8")

    baseline = await analyze_project(project_path=str(tmp_path))
    assert "error" not in baseline

    for _ in range(999):
        result = await analyze_project(project_path=str(tmp_path))
        assert result == baseline

    stats = _cache_stats()
    assert stats["computes"] == 1
    assert stats["hits"] >= 999


async def test_lru_eviction_caps_entries(tmp_path):
    for d in range(9):
        sub = tmp_path / f"proj_{d}"
        sub.mkdir()
        (sub / "main.py").write_text(f"value = {d}\n", encoding="utf-8")

    reports = [
        await analyze_project(project_path=str(tmp_path / f"proj_{d}")) for d in range(9)
    ]

    assert all("error" not in report for report in reports)
    stats = _cache_stats()
    assert stats["entries"] <= 8
    assert stats["computes"] == 9

    again = await analyze_project(project_path=str(tmp_path / "proj_8"))
    assert again == reports[-1]
    assert _cache_stats()["computes"] == 9
