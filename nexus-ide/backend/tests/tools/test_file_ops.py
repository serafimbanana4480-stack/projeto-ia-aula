"""Tests for file operations tool."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.tools.file_api import _validate_relative_path as _validate_path
from backend.tools.file_ops import (
    list_dir,
    read_file,
    read_multiple_files,
    search_in_files,
    write_file,
)


@pytest.fixture(autouse=True)
def mock_propose_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock propose_change to avoid database dependency."""
    monkeypatch.setattr("backend.tools.file_ops.propose_change", MagicMock())


class TestValidatePath:
    """Test path validation."""

    def test_valid_relative_path(self, tmp_path: Path) -> None:
        """Test that valid relative path is accepted."""
        project = tmp_path / "project"
        project.mkdir()
        result = _validate_path(str(project), "subdir/file.txt")
        assert result == (project / "subdir" / "file.txt").resolve()

    def test_valid_absolute_path_within_project(self, tmp_path: Path) -> None:
        """Test that absolute path within project is accepted."""
        project = tmp_path / "project"
        project.mkdir()
        target = project / "file.txt"
        result = _validate_path(str(project), str(target))
        assert result == target.resolve()

    def test_path_outside_project_raises_permission_error(self, tmp_path: Path) -> None:
        """Test that path outside project raises PermissionError."""
        project = tmp_path / "project"
        project.mkdir()
        other = tmp_path / "other"
        other.mkdir()

        with pytest.raises(PermissionError) as exc_info:
            _validate_path(str(project), str(other / "file.txt"))
        assert "outside project root" in str(exc_info.value)

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Test that path traversal is blocked."""
        project = tmp_path / "project"
        project.mkdir()

        with pytest.raises(PermissionError):
            _validate_path(str(project), "../etc/passwd")


class TestReadFile:
    """Test file reading."""

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path: Path) -> None:
        """Test reading an existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World", encoding="utf-8")

        result = await read_file("test.txt", str(tmp_path))
        assert result["content"] == "Hello World"
        assert result["size"] == 11
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        """Test reading a non-existent file."""
        result = await read_file("nonexistent.txt", str(tmp_path))
        assert "error" in result
        assert "File not found" in result["error"]

    @pytest.mark.asyncio
    async def test_read_file_outside_project(self, tmp_path: Path) -> None:
        """Test reading file outside project is blocked."""
        result = await read_file("../etc/passwd", str(tmp_path))
        assert "error" in result
        assert "not allowed" in result["error"]


class TestWriteFile:
    """Test file writing."""

    @pytest.mark.asyncio
    async def test_write_new_file(self, tmp_path: Path) -> None:
        """Test writing a new file."""
        result = await write_file("new.txt", "New content", str(tmp_path))
        assert result["written"] is True
        assert result["size"] == 11

        # Verify file was written
        test_file = tmp_path / "new.txt"
        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == "New content"

    @pytest.mark.asyncio
    async def test_write_existing_file(self, tmp_path: Path) -> None:
        """Test overwriting an existing file."""
        test_file = tmp_path / "existing.txt"
        test_file.write_text("Old content", encoding="utf-8")

        result = await write_file("existing.txt", "New content", str(tmp_path))
        assert "error" not in result

        # Verify file was overwritten
        assert test_file.read_text(encoding="utf-8") == "New content"

    @pytest.mark.asyncio
    async def test_write_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that write_file creates parent directories."""
        result = await write_file("subdir/nested/file.txt", "Content", str(tmp_path))
        assert result["written"] is True

        # Verify directories were created
        assert (tmp_path / "subdir" / "nested" / "file.txt").exists()

    @pytest.mark.asyncio
    async def test_write_file_outside_project_blocked(self, tmp_path: Path) -> None:
        """Test writing outside project is blocked."""
        result = await write_file("../etc/passwd", "malicious", str(tmp_path))
        assert "error" in result
        assert "not allowed" in result["error"]


class TestListDir:
    """Test directory listing."""

    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_path: Path) -> None:
        """Test listing a directory."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "subdir").mkdir()

        result = await list_dir(".", str(tmp_path), recursive=False)
        names = {i["name"] for i in result.get("items", [])}
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "subdir" in names
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_list_directory_recursive(self, tmp_path: Path) -> None:
        """Test listing a directory recursively."""
        (tmp_path / "file1.txt").write_text("content1")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("content2")

        result = await list_dir(".", str(tmp_path), recursive=True)
        names = {i["name"] for i in result.get("items", [])}
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "subdir" in names

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test listing a non-existent directory."""
        result = await list_dir("nonexistent", str(tmp_path))
        assert "error" in result
        assert "Path not found" in result["error"]

    @pytest.mark.asyncio
    async def test_list_directory_outside_project_blocked(self, tmp_path: Path) -> None:
        """Test listing outside project is blocked."""
        result = await list_dir("../", str(tmp_path))
        assert "error" in result
        assert "not allowed" in result["error"]


class TestSearchInFiles:
    """Test file search."""

    @pytest.mark.asyncio
    async def test_search_in_files(self, tmp_path: Path) -> None:
        """Test searching for text in files."""
        (tmp_path / "file1.py").write_text("def hello():\n    print('hello')")
        (tmp_path / "file2.py").write_text("def world():\n    print('world')")

        result = await search_in_files("hello", str(tmp_path), "*.py")
        assert result["count"] == 1
        assert result["results"][0]["path"] == "file1.py"

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, tmp_path: Path) -> None:
        """Test that search is case-insensitive."""
        (tmp_path / "file.py").write_text("HELLO world")

        result = await search_in_files("hello", str(tmp_path), "*.py")
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_search_no_matches(self, tmp_path: Path) -> None:
        """Test search with no matches."""
        (tmp_path / "file.py").write_text("Hello World")

        result = await search_in_files("nonexistent", str(tmp_path), "*.py")
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_search_with_file_pattern(self, tmp_path: Path) -> None:
        """Test search with file pattern."""
        (tmp_path / "file.py").write_text("hello")
        (tmp_path / "file.txt").write_text("hello")

        result = await search_in_files("hello", str(tmp_path), "*.py")
        assert result["count"] == 1
        assert result["results"][0]["path"] == "file.py"

    @pytest.mark.asyncio
    async def test_search_includes_line_preview(self, tmp_path: Path) -> None:
        """Test that search includes line preview."""
        (tmp_path / "file.py").write_text("line1\nhello\nline3")

        result = await search_in_files("hello", str(tmp_path), "*.py")
        assert result["count"] == 1
        assert "preview" in result["results"][0]
        assert len(result["results"][0]["preview"]) > 0


class TestReadMultipleFiles:
    """Test reading multiple files in one call."""

    @pytest.mark.asyncio
    async def test_read_multiple_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("content a", encoding="utf-8")
        (tmp_path / "b.txt").write_text("content b", encoding="utf-8")

        result = await read_multiple_files(["a.txt", "b.txt"], project_path=str(tmp_path))

        assert result["read_count"] == 2
        assert result["files"][str(tmp_path / "a.txt")] == "content a"
        assert result["files"][str(tmp_path / "b.txt")] == "content b"

    @pytest.mark.asyncio
    async def test_read_multiple_files_with_missing(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("content a", encoding="utf-8")

        result = await read_multiple_files(["a.txt", "missing.txt"], project_path=str(tmp_path))

        assert result["read_count"] == 1
        assert "File not found" in result["errors"][str(tmp_path / "missing.txt")]

    @pytest.mark.asyncio
    async def test_read_multiple_files_outside_project(self, tmp_path: Path) -> None:
        result = await read_multiple_files(["../etc/passwd"], project_path=str(tmp_path))

        assert result["read_count"] == 0
        assert "not allowed" in result["errors"]["../etc/passwd"]

    @pytest.mark.asyncio
    async def test_read_multiple_files_empty(self, tmp_path: Path) -> None:
        result = await read_multiple_files([], project_path=str(tmp_path))

        assert result["read_count"] == 0
        assert result["skipped_count"] == 0
