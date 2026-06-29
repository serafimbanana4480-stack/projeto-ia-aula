"""Tests for backend.tools.doc_tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools.doc_tools import generate_module_doc


class TestDocTools:
    @pytest.mark.asyncio
    async def test_generate_doc_for_python_file(self, tmp_path: Path) -> None:
        src = tmp_path / "module.py"
        src.write_text(
            '"""A sample module."""\n\n'
            "def add(a: int, b: int) -> int:\n"
            '    """Add two numbers."""\n'
            "    return a + b\n",
            encoding="utf-8",
        )

        result = await generate_module_doc(str(src), project_path=str(tmp_path))
        assert "documentation" in result
        assert "add" in result["documentation"]
        assert result["symbols_documented"] >= 1

    @pytest.mark.asyncio
    async def test_generate_doc_writes_file(self, tmp_path: Path) -> None:
        src = tmp_path / "module.py"
        src.write_text("def hello():\n    pass\n", encoding="utf-8")
        out = tmp_path / "docs" / "module.md"

        await generate_module_doc(str(src), output_path=str(out), project_path=str(tmp_path))
        assert out.exists()
        assert "hello" in out.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_generate_doc_missing_file(self) -> None:
        result = await generate_module_doc("/nonexistent/path/file.py")
        assert "error" in result
