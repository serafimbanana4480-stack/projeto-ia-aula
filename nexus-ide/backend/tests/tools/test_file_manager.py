"""Tests for backend.tools.file_manager — file read/write with path safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools.file_manager import (
    ALLOWED_EXTENSIONS,
    BLOCKED_PATH_PARTS,
    UnsafePathError,
    read_file,
    write_file,
)


class TestReadFile:
    """Test read_file function."""

    @pytest.mark.asyncio
    async def test_read_file_success(self, tmp_path: Path) -> None:
        """Test reading an existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World", encoding="utf-8")

        content = await read_file(str(test_file))
        assert content == "Hello World"

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, tmp_path: Path) -> None:
        """Test reading a non-existent file raises FileNotFoundError."""
        test_file = tmp_path / "nonexistent.txt"

        with pytest.raises(FileNotFoundError, match="File not found"):
            await read_file(str(test_file))

    @pytest.mark.asyncio
    async def test_read_file_not_a_file(self, tmp_path: Path) -> None:
        """Test reading a directory raises ValueError."""
        with pytest.raises(ValueError, match="Not a file"):
            await read_file(str(tmp_path))

    @pytest.mark.asyncio
    async def test_read_file_blocked_path(self) -> None:
        """Test reading a blocked path raises UnsafePathError."""
        with pytest.raises(UnsafePathError, match="Blocked path"):
            await read_file("/etc/passwd")

    @pytest.mark.asyncio
    async def test_read_file_blocked_extension(self, tmp_path: Path) -> None:
        """Test reading a file with disallowed extension raises UnsafePathError."""
        test_file = tmp_path / "test.exe"
        test_file.write_text("content", encoding="utf-8")

        with pytest.raises(UnsafePathError, match="Disallowed extension"):
            await read_file(str(test_file))


class TestWriteFile:
    """Test write_file function."""

    @pytest.mark.asyncio
    async def test_write_file_success(self, tmp_path: Path) -> None:
        """Test writing a new file."""
        test_file = tmp_path / "new.txt"
        await write_file(str(test_file), "New content")

        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == "New content"

    @pytest.mark.asyncio
    async def test_write_file_overwrite(self, tmp_path: Path) -> None:
        """Test overwriting an existing file."""
        test_file = tmp_path / "existing.txt"
        test_file.write_text("Old content", encoding="utf-8")

        await write_file(str(test_file), "New content")

        assert test_file.read_text(encoding="utf-8") == "New content"

    @pytest.mark.asyncio
    async def test_write_file_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that write_file creates parent directories."""
        test_file = tmp_path / "subdir" / "nested" / "file.txt"

        await write_file(str(test_file), "Content")

        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == "Content"

    @pytest.mark.asyncio
    async def test_write_file_blocked_path(self) -> None:
        """Test writing to a blocked path raises UnsafePathError."""
        with pytest.raises(UnsafePathError, match="Blocked path"):
            await write_file("/etc/passwd", "malicious")

    @pytest.mark.asyncio
    async def test_write_file_blocked_extension(self, tmp_path: Path) -> None:
        """Test writing a file with disallowed extension raises UnsafePathError."""
        test_file = tmp_path / "malicious.exe"

        with pytest.raises(UnsafePathError, match="Disallowed extension"):
            await write_file(str(test_file), "content")


class TestPathValidation:
    """Test path validation logic."""

    def test_allowed_extensions(self) -> None:
        """Test that common extensions are allowed."""
        assert ".py" in ALLOWED_EXTENSIONS
        assert ".ts" in ALLOWED_EXTENSIONS
        assert ".js" in ALLOWED_EXTENSIONS
        assert ".md" in ALLOWED_EXTENSIONS
        assert ".json" in ALLOWED_EXTENSIONS

    def test_blocked_paths(self) -> None:
        """Test that dangerous paths are blocked."""
        assert "/etc" in BLOCKED_PATH_PARTS
        assert "/sys" in BLOCKED_PATH_PARTS
        assert "/proc" in BLOCKED_PATH_PARTS
        assert ".ssh" in BLOCKED_PATH_PARTS
        assert "/root" in BLOCKED_PATH_PARTS

    @pytest.mark.asyncio
    async def test_blocked_path_component_rejects_system_path(self, tmp_path: Path) -> None:
        """Real system paths like /etc/passwd are still blocked."""
        with pytest.raises(UnsafePathError, match="Blocked path"):
            await read_file("/etc/passwd")

    @pytest.mark.asyncio
    async def test_substring_false_positive_allowed(self, tmp_path: Path) -> None:
        """Legitimate paths containing blocked substrings are permitted."""
        # e.g. ``my.ssh.project`` or ``etcetera`` should not be blocked.
        test_file = tmp_path / "etcetera.txt"
        test_file.write_text("safe content", encoding="utf-8")

        content = await read_file(str(test_file))
        assert content == "safe content"

    @pytest.mark.asyncio
    async def test_ssh_substring_in_filename_allowed(self, tmp_path: Path) -> None:
        """A file name containing '.ssh' as a substring is not blocked."""
        test_file = tmp_path / "my.ssh.project.txt"
        test_file.write_text("safe content", encoding="utf-8")

        content = await read_file(str(test_file))
        assert content == "safe content"
