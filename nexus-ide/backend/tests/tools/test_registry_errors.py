"""Tests for execute_tool error propagation from handler result dicts."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.tools.registry import ToolSpec, execute_tool, register_tool


@pytest.mark.asyncio
async def test_execute_tool_surfaces_handler_error_dict() -> None:
    """A handler that reports an error must surface it at the top level."""
    async def failing(**kwargs):
        return {"error": "handler refused the write"}

    register_tool(
        ToolSpec(
            name="error_dict_probe",
            description="always reports an error",
            handler=failing,
        )
    )
    result = await execute_tool("error_dict_probe", "test-session", {})
    assert "error" in result
    assert result["error"]
    assert isinstance(result.get("result"), dict)
    assert result["result"].get("error")


@pytest.mark.asyncio
async def test_execute_tool_allows_verified_write() -> None:
    """A write inside the selected project still runs."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "nexus_registry_test_ok.txt"
        result = await execute_tool(
            "write_file_absolute",
            "test-session",
            {"path": str(target), "content": "ok"},
            project_path=tmp,
        )
        assert "error" not in result, result
        assert result["result"]["written"] is True
        assert target.read_text(encoding="utf-8") == "ok"


@pytest.mark.asyncio
async def test_execute_tool_no_false_success_on_blocked_paths() -> None:
    """Regression: handler errors must surface at the execute_tool top level."""
    blocked_cases = [
        ("/etc/passwd", "hack"),
        (r"C:\outside_project\secret.txt", "Y"),
    ]
    for path, content in blocked_cases:
        result = await execute_tool(
            "write_file_absolute",
            "test-session",
            {"path": path, "content": content},
        )
        assert "error" in result, path
        # Without a selected project the call never reaches the handler: there
        # is no authorised folder, so nothing was written anywhere.
        assert result.get("error_category") == "project_scope_denied", path

    with tempfile.TemporaryDirectory() as tmp:
        posix_target = Path(tmp) / "posix.txt"
        posix_result = await execute_tool(
            "write_file_absolute",
            "test-session",
            {"path": str(posix_target), "content": "X"},
            project_path=tmp,
        )
        assert "error" not in posix_result, posix_result
        assert posix_result["result"]["written"] is True
