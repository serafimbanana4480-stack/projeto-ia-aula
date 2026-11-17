"""Tool-confirmation gate: a confirmation-listed tool can be approved or refused.

These tests drive the real :func:`backend.tools.registry.execute_tool` gate and
the real in-process confirmation store, then prove the outcome: an in-project
write with ``auto_accept`` runs without prompting, an out-of-project write still
requires a decision, and an explicit approval lets the write through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools.confirmations import resolve_confirmation
from backend.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_out_of_project_write_requires_confirmation_then_runs_when_approved(
    tmp_path: Path,
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    target = project / "note.txt"

    blocked = await execute_tool(
        "write_file_absolute",
        "confirm-session",
        {"path": str(target), "content": "hello"},
        enforce_confirmation=True,
        auto_accept=True,
        project_path="",
    )
    assert blocked["ok"] is False
    assert blocked.get("confirmation_required") is True
    confirmation_id = str(blocked["confirmation_id"])
    assert confirmation_id

    assert await resolve_confirmation(confirmation_id, True) is True

    # The same call, now explicitly confirmed, executes the write.
    executed = await execute_tool(
        "write_file_absolute",
        "confirm-session",
        {"path": str(target), "content": "hello"},
        enforce_confirmation=True,
        auto_accept=False,
        confirmed=True,
        project_path=str(project),
    )
    assert executed.get("confirmation_required") is not True, executed
    assert executed["ok"] is True, executed
    assert target.read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_in_project_write_auto_accepts_without_prompting(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    target = project / "auto.txt"

    result = await execute_tool(
        "write_file_absolute",
        "confirm-session",
        {"path": str(target), "content": "auto"},
        enforce_confirmation=True,
        auto_accept=True,
        project_path=str(project),
    )
    assert result.get("confirmation_required") is not True, result
    assert result["ok"] is True, result
    assert target.read_text(encoding="utf-8") == "auto"


@pytest.mark.asyncio
async def test_refused_confirmation_does_not_execute(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    target = project / "refused.txt"

    blocked = await execute_tool(
        "write_file_absolute",
        "confirm-session",
        {"path": str(target), "content": "nope"},
        enforce_confirmation=True,
        auto_accept=True,
        project_path="",
    )
    confirmation_id = str(blocked["confirmation_id"])
    assert await resolve_confirmation(confirmation_id, False) is True
    assert not target.exists()