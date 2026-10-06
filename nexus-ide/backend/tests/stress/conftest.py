"""Plumbing for the deterministic stress suite.

Registers the ``stress`` marker (required by ``--strict-markers``), swaps the
global Alembic-heavy ``temp_db`` autouse fixture for a cheap variant, and
prints the synthetic-iteration counters collected by the suite at the end of
the run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "stress: deterministic high-iteration robustness fuzzing (offline, fast)",
    )
    config._stress_counters = {}


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect SQLite away from real storage without paying migrations.

    The suite-level ``temp_db`` runs Alembic stamping on every test (~110 ms);
    stress fuzzing never touches the database, so a pointer swap plus a pool
    reset is all the isolation it needs.
    """
    db_file = tmp_path / "stress_nexus.db"
    monkeypatch.setattr("backend.persistence.db.DB_PATH", db_file)
    from backend.persistence.db import close_pool

    close_pool()


def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: pytest.Config
) -> None:
    counters: dict[str, int] = getattr(config, "_stress_counters", {})
    if not counters:
        return
    terminalreporter.write_sep("=", "NEXUS stress suite — synthetic iterations")
    total = 0
    for name in sorted(counters):
        terminalreporter.write_line(f"{name}: {counters[name]}")
        total += counters[name]
    terminalreporter.write_line(f"total: {total}")
