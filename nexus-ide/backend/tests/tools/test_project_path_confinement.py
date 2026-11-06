"""Model-supplied paths must stay inside the selected project."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.workspace import WorkspaceManager
from backend.tools.append_file import append_file
from backend.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_append_file_rejects_an_absolute_path_outside_the_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = await append_file(str(outside), "\nmore", project_path=str(project))

    assert "error" in result
    assert "outside project root" in result["error"]
    assert outside.read_text(encoding="utf-8") == "secret"


@pytest.mark.asyncio
async def test_append_file_still_appends_inside_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "notes.txt"
    target.write_text("a", encoding="utf-8")

    result = await append_file("notes.txt", "b", project_path=str(project))

    assert "error" not in result
    assert target.read_text(encoding="utf-8") == "ab"


def test_workspace_manager_rejects_absolute_paths_outside_its_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    manager = WorkspaceManager(str(project))

    with pytest.raises(PermissionError, match="outside project root"):
        manager._resolve(str(outside / "file.txt"))
    with pytest.raises(PermissionError, match="outside project root"):
        manager._resolve_path(str(outside / "file.txt"))


def test_workspace_manager_accepts_an_absolute_path_inside_its_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "inside.txt"
    manager = WorkspaceManager(str(project))

    assert Path(manager._resolve(str(target))) == target.resolve()
    assert manager._resolve_path(str(target)) == target.resolve()


@pytest.mark.asyncio
async def test_read_file_absolute_cannot_read_outside_the_selected_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("private-marker", encoding="utf-8")

    result = await execute_tool(
        "read_file_absolute",
        "confinement-session",
        {"path": str(secret)},
        project_path=str(project),
        enforce_confirmation=True,
        user_id="confinement-user",
    )

    assert result["ok"] is False
    assert result["error_category"] == "project_scope_denied"
    assert "private-marker" not in str(result)
    assert secret.read_text(encoding="utf-8") == "private-marker"


@pytest.mark.asyncio
async def test_read_file_absolute_still_reads_inside_the_selected_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    visible = project / "visible.txt"
    visible.write_text("inside-marker", encoding="utf-8")

    result = await execute_tool(
        "read_file_absolute",
        "confinement-session",
        {"path": str(visible)},
        project_path=str(project),
        enforce_confirmation=True,
        user_id="confinement-user",
    )

    assert result["ok"] is True
    assert "inside-marker" in str(result)


@pytest.mark.asyncio
async def test_absolute_path_tool_without_a_project_asks_for_one(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("private-marker", encoding="utf-8")

    result = await execute_tool(
        "read_file_absolute",
        "confinement-session",
        {"path": str(secret)},
        project_path="",
        user_id="confinement-user",
    )

    assert result["ok"] is False
    assert result["error_category"] == "project_scope_denied"
    assert "project" in result["error"].lower()
    assert "private-marker" not in str(result)


@pytest.mark.asyncio
async def test_confirmed_write_absolute_still_cannot_leave_the_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("kept", encoding="utf-8")

    result = await execute_tool(
        "write_file_absolute",
        "confinement-session",
        {"path": str(outside), "content": "overwritten"},
        project_path=str(project),
        confirmed=True,
        enforce_confirmation=True,
        autonomous=True,
        user_id="confinement-user",
    )

    assert result["ok"] is False
    assert result["error_category"] == "project_scope_denied"
    assert outside.read_text(encoding="utf-8") == "kept"
