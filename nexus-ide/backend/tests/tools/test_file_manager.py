"""Tests for backend.tools.file_manager — schema only (stubs)."""

from __future__ import annotations

from backend.tools.file_manager import read_file, write_file


class TestFileManager:
    def test_read_file_callable(self) -> None:
        assert callable(read_file)

    def test_write_file_callable(self) -> None:
        assert callable(write_file)
