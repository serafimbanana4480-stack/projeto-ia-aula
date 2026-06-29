"""Tests for execute_tool error propagation from handler result dicts."""

from __future__ import annotations

import pytest

from backend.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_execute_tool_surfaces_handler_error_dict() -> None:
    result = await execute_tool(
        "write_file_absolute",
        "test-session",
        {"path": "/etc/passwd", "content": "blocked"},
    )
    assert "error" in result
    assert result["error"]
    assert isinstance(result.get("result"), dict)
    assert result["result"].get("error")


@pytest.mark.asyncio
async def test_execute_tool_allows_verified_write() -> None:
    import tempfile
    from pathlib import Path

    target = Path(tempfile.gettempdir()) / "nexus_registry_test_ok.txt"
    try:
        result = await execute_tool(
            "write_file_absolute",
            "test-session",
            {"path": str(target), "content": "ok"},
        )
        assert "error" not in result
        assert result["result"]["written"] is True
        assert target.read_text(encoding="utf-8") == "ok"
    finally:
        if target.exists():
            target.unlink()


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
        assert result["result"].get("error")

    posix_result = await execute_tool(
        "write_file_absolute",
        "test-session",
        {"path": "/tmp/nexus_test/posix.txt", "content": "X"},
    )
    assert "error" not in posix_result
    assert posix_result["result"]["written"] is True
