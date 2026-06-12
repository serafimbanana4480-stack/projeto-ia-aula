"""Tests for directory_tools."""

from __future__ import annotations

import pytest

from backend.tools.directory_tools import (
    copy_file,
    create_directory,
    delete_directory,
    delete_file,
    get_file_info,
    move_file,
)


@pytest.mark.asyncio
async def test_create_directory(tmp_path):
    target = tmp_path / "new_dir" / "nested"
    result = await create_directory(str(target.relative_to(tmp_path)), project_path=str(tmp_path))
    assert result["created"] is True
    assert target.exists()


@pytest.mark.asyncio
async def test_create_directory_outside_project():
    result = await create_directory("/etc/test_dir", project_path="/tmp")
    assert "error" in result


@pytest.mark.asyncio
async def test_copy_file(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("hello")
    result = await copy_file("src.txt", "dest.txt", project_path=str(tmp_path))
    assert result["copied"] is True
    assert (tmp_path / "dest.txt").read_text() == "hello"


@pytest.mark.asyncio
async def test_move_file(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("data")
    result = await move_file("a.txt", "b.txt", project_path=str(tmp_path))
    assert result["moved"] is True
    assert not src.exists()
    assert (tmp_path / "b.txt").read_text() == "data"


@pytest.mark.asyncio
async def test_delete_file_without_confirm(tmp_path):
    f = tmp_path / "del.txt"
    f.write_text("x")
    result = await delete_file("del.txt", project_path=str(tmp_path))
    assert result.get("deleted") is True
    assert not f.exists()


@pytest.mark.asyncio
async def test_delete_file_missing_file(tmp_path):
    result = await delete_file("missing.txt", project_path=str(tmp_path))
    assert "error" in result
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_delete_directory_moves_to_trash(tmp_path):
    target = tmp_path / "to_delete"
    target.mkdir()
    (target / "file.txt").write_text("x")

    result = await delete_directory("to_delete", project_path=str(tmp_path))
    assert result["deleted"] is True
    assert "trash_path" in result
    assert not target.exists()


@pytest.mark.asyncio
async def test_delete_directory_permanent(tmp_path):
    target = tmp_path / "to_delete"
    target.mkdir()

    result = await delete_directory(
        "to_delete", project_path=str(tmp_path), move_to_trash=False
    )
    assert result["deleted"] is True
    assert result["trash_path"] is None
    assert not target.exists()


@pytest.mark.asyncio
async def test_delete_directory_protected(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    result = await delete_directory(".git", project_path=str(tmp_path))
    assert "error" in result
    assert git_dir.exists()


@pytest.mark.asyncio
async def test_delete_directory_not_a_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")

    result = await delete_directory("file.txt", project_path=str(tmp_path))
    assert "error" in result


@pytest.mark.asyncio
async def test_get_file_info(tmp_path):
    f = tmp_path / "info.txt"
    f.write_text("hello", encoding="utf-8")

    result = await get_file_info("info.txt", project_path=str(tmp_path))
    assert result["type"] == "file"
    assert result["size"] == 5
    assert result["exists"] is True


@pytest.mark.asyncio
async def test_get_file_info_directory(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()

    result = await get_file_info("subdir", project_path=str(tmp_path))
    assert result["type"] == "dir"
    assert result["exists"] is True
