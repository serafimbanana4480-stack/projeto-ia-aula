"""Tests for backend.core.workspace_fs new operations."""

from __future__ import annotations

from pathlib import Path

from backend.core.workspace_fs import (
    copy_file_absolute,
    create_dir_absolute,
    delete_dir_absolute,
    delete_file_absolute,
    get_file_info_absolute,
    list_dir_absolute,
    move_file_absolute,
    read_file_absolute,
    read_multiple_files_absolute,
    write_file_absolute,
)


class TestWriteFileAbsolute:
    async def test_write_and_read(self, tmp_path: Path) -> None:
        target = tmp_path / "hello.txt"
        result = await write_file_absolute(str(target), "hello world")
        assert result["written"] is True
        assert target.read_text(encoding="utf-8") == "hello world"

        read = await read_file_absolute(str(target))
        assert read["content"] == "hello world"

    async def test_overwrite_false_protects_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "existing.txt"
        target.write_text("original", encoding="utf-8")

        result = await write_file_absolute(str(target), "new", overwrite=False)
        assert "error" in result
        assert result.get("exists") is True
        assert target.read_text(encoding="utf-8") == "original"

    async def test_overwrite_true_replaces_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "existing.txt"
        target.write_text("original", encoding="utf-8")

        result = await write_file_absolute(str(target), "new", overwrite=True)
        assert result["written"] is True
        assert target.read_text(encoding="utf-8") == "new"

    async def test_blocked_path_rejected(self, tmp_path: Path) -> None:
        result = await write_file_absolute(r"C:\Windows\nexus_test.txt", "x")
        assert "error" in result


class TestDirectoryOperations:
    async def test_create_dir_nested(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c"
        result = await create_dir_absolute(str(target))
        assert result["created"] is True
        assert target.is_dir()

    async def test_delete_dir_moves_to_trash(self, tmp_path: Path) -> None:
        target = tmp_path / "to_delete"
        target.mkdir()
        (target / "file.txt").write_text("x", encoding="utf-8")

        result = await delete_dir_absolute(str(target), move_to_trash=True)
        assert result["deleted"] is True
        assert "trash_path" in result
        assert not target.exists()

    async def test_delete_dir_permanent(self, tmp_path: Path) -> None:
        target = tmp_path / "to_delete"
        target.mkdir()

        result = await delete_dir_absolute(str(target), move_to_trash=False)
        assert result["deleted"] is True
        assert result["trash_path"] is None
        assert not target.exists()

    async def test_list_dir_respects_include_hidden(self, tmp_path: Path) -> None:
        (tmp_path / "visible.txt").write_text("x", encoding="utf-8")
        (tmp_path / ".hidden").write_text("x", encoding="utf-8")

        with_hidden = await list_dir_absolute(str(tmp_path), include_hidden=True)
        names = {i["name"] for i in with_hidden["items"]}
        assert ".hidden" in names

        without_hidden = await list_dir_absolute(str(tmp_path), include_hidden=False)
        names = {i["name"] for i in without_hidden["items"]}
        assert ".hidden" not in names
        assert without_hidden["skipped_hidden"] >= 1


class TestMoveAndCopy:
    async def test_move_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("x", encoding="utf-8")
        dest = tmp_path / "dest.txt"

        result = await move_file_absolute(str(src), str(dest))
        assert result["moved"] is True
        assert not src.exists()
        assert dest.read_text(encoding="utf-8") == "x"

    async def test_move_rejects_existing_dest(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("x", encoding="utf-8")
        dest = tmp_path / "dest.txt"
        dest.write_text("y", encoding="utf-8")

        result = await move_file_absolute(str(src), str(dest))
        assert "error" in result

    async def test_copy_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("x", encoding="utf-8")
        dest = tmp_path / "dest.txt"

        result = await copy_file_absolute(str(src), str(dest))
        assert result["copied"] is True
        assert src.exists()
        assert dest.read_text(encoding="utf-8") == "x"

    async def test_copy_rejects_directory(self, tmp_path: Path) -> None:
        src = tmp_path / "src_dir"
        src.mkdir()
        dest = tmp_path / "dest_dir"

        result = await copy_file_absolute(str(src), str(dest))
        assert "error" in result


class TestFileInfo:
    async def test_file_info(self, tmp_path: Path) -> None:
        target = tmp_path / "info.txt"
        target.write_text("hello", encoding="utf-8")

        result = await get_file_info_absolute(str(target))
        assert result["type"] == "file"
        assert result["size"] == 5
        assert result["exists"] is True
        assert "modified" in result

    async def test_dir_info(self, tmp_path: Path) -> None:
        (tmp_path / "child.txt").write_text("x", encoding="utf-8")

        result = await get_file_info_absolute(str(tmp_path))
        assert result["type"] == "dir"
        assert result["children_count"] >= 1


class TestDeleteFile:
    async def test_delete_file_moves_to_trash(self, tmp_path: Path) -> None:
        target = tmp_path / "delete_me.txt"
        target.write_text("x", encoding="utf-8")

        result = await delete_file_absolute(str(target), move_to_trash=True)
        assert result["deleted"] is True
        assert "trash_path" in result
        assert not target.exists()

    async def test_delete_file_permanent(self, tmp_path: Path) -> None:
        target = tmp_path / "delete_me.txt"
        target.write_text("x", encoding="utf-8")

        result = await delete_file_absolute(str(target), move_to_trash=False)
        assert result["deleted"] is True
        assert result["trash_path"] is None
        assert not target.exists()


class TestReadMultipleFilesAbsolute:
    async def test_read_multiple_files(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("content a", encoding="utf-8")
        b.write_text("content b", encoding="utf-8")

        result = await read_multiple_files_absolute([str(a), str(b)])

        assert result["read_count"] == 2
        assert result["files"][str(a)] == "content a"
        assert result["files"][str(b)] == "content b"
        assert not result["errors"]

    async def test_read_multiple_files_missing_file(self, tmp_path: Path) -> None:
        existing = tmp_path / "existing.txt"
        existing.write_text("ok", encoding="utf-8")
        missing = tmp_path / "missing.txt"

        result = await read_multiple_files_absolute([str(existing), str(missing)])

        assert result["read_count"] == 1
        assert result["files"][str(existing)] == "ok"
        assert "File not found" in result["errors"][str(missing)]

    async def test_read_multiple_files_blocked_path(self, tmp_path: Path) -> None:
        result = await read_multiple_files_absolute(["/etc/passwd"])

        assert result["read_count"] == 0
        assert "/etc/passwd" in result["errors"]

    async def test_read_multiple_files_max_files(self, tmp_path: Path) -> None:
        files = []
        for i in range(5):
            f = tmp_path / f"f{i}.txt"
            f.write_text(str(i), encoding="utf-8")
            files.append(str(f))

        result = await read_multiple_files_absolute(files, max_files=2)

        assert result["read_count"] == 2
        assert result["skipped_count"] == 3

    async def test_read_multiple_files_max_total_bytes(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("aa", encoding="utf-8")
        b.write_text("bbb", encoding="utf-8")

        result = await read_multiple_files_absolute(
            [str(a), str(b)], max_total_bytes=2
        )

        assert result["read_count"] == 1
        assert result["total_bytes"] == 2
        assert "max_total_bytes" in result["errors"][str(b)]

    async def test_read_multiple_files_empty(self, tmp_path: Path) -> None:
        result = await read_multiple_files_absolute([])

        assert result["read_count"] == 0
        assert result["skipped_count"] == 0
        assert result["total_bytes"] == 0


class TestListDirAbsoluteFilters:
    async def test_list_dir_only_files(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        (tmp_path / "subdir").mkdir()

        result = await list_dir_absolute(
            str(tmp_path), include_files=True, include_dirs=False
        )

        names = {i["name"] for i in result["items"]}
        assert "file.txt" in names
        assert "subdir" not in names

    async def test_list_dir_only_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        (tmp_path / "subdir").mkdir()

        result = await list_dir_absolute(
            str(tmp_path), include_files=False, include_dirs=True
        )

        names = {i["name"] for i in result["items"]}
        assert "subdir" in names
        assert "file.txt" not in names

    async def test_list_dir_glob_filter(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "b.txt").write_text("x", encoding="utf-8")

        result = await list_dir_absolute(str(tmp_path), glob_pattern="*.py")

        names = {i["name"] for i in result["items"]}
        assert "a.py" in names
        assert "b.txt" not in names


class TestPosixTmpPaths:
    async def test_write_read_delete_posix_tmp(self) -> None:
        import os
        import uuid

        import pytest

        if os.name != "nt":
            pytest.skip("POSIX /tmp remapping is Windows-specific")

        rel = f"/tmp/nexus_test_{uuid.uuid4().hex}.txt"
        content = "posix tmp content"

        write_result = await write_file_absolute(rel, content)
        assert write_result.get("written") is True
        resolved = write_result["path"]
        assert "tmp" in resolved.replace("\\", "/").lower()
        assert os.path.isfile(resolved)

        read_result = await read_file_absolute(rel)
        assert read_result.get("content") == content

        list_result = await list_dir_absolute(
            "/tmp", include_files=True, include_dirs=False, glob_pattern="nexus_test_*.txt"
        )
        listed_paths = {item["path"] for item in list_result.get("items", [])}
        assert resolved in listed_paths

        delete_result = await delete_file_absolute(rel, move_to_trash=False)
        assert delete_result.get("deleted") is True
        assert not os.path.isfile(resolved)


class TestListDirRecursiveGlob:
    async def test_list_dir_recursive_glob(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.py").write_text("x", encoding="utf-8")
        (sub / "b.txt").write_text("x", encoding="utf-8")

        result = await list_dir_absolute(
            str(tmp_path), recursive=True, glob_pattern="*.py"
        )

        names = {i["name"] for i in result["items"]}
        assert "a.py" in names
        assert "b.txt" not in names
