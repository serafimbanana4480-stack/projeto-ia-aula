"""Tests for project_analyzer."""

from __future__ import annotations

import pytest

from backend.tools.project_analyzer import analyze_project


@pytest.mark.asyncio
async def test_analyze_project(tmp_path):
    (tmp_path / "main.py").write_text("def hello(): pass\n")
    (tmp_path / "README.md").write_text("# Test\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_hello(): pass\n")

    result = await analyze_project(project_path=str(tmp_path))
    assert "error" not in result
    assert result["lines_of_code"]["total_lines_of_code"] > 0
    assert result["total_files"] >= 3
    assert result["test_coverage"]["test_files_found"] is True
    assert result["health_score"] > 0


@pytest.mark.asyncio
async def test_analyze_project_detects_fastapi(tmp_path):
    # Create a file with fastapi in the name to ensure framework detection picks it up
    (tmp_path / "fastapi_main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    result = await analyze_project(project_path=str(tmp_path))
    assert result["framework"]["primary"] == "fastapi"


@pytest.mark.asyncio
async def test_analyze_project_missing_tests(tmp_path):
    (tmp_path / "main.py").write_text("def hello(): pass\n")
    result = await analyze_project(project_path=str(tmp_path))
    assert result["test_coverage"]["test_files_found"] is False
    assert any("test" in i["recommendation"].lower() for i in result["issues"] if i["type"] == "missing_tests")
