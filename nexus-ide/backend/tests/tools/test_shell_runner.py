"""Tests for shell_runner."""

from __future__ import annotations

import pytest

from backend.tools.shell_runner import run_shell


@pytest.mark.asyncio
async def test_run_shell_echo():
    result = await run_shell("echo hello")
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


@pytest.mark.asyncio
async def test_run_shell_blocked_command():
    result = await run_shell("rm -rf /")
    assert "error" in result
    assert "blocked" in result["error"].lower()


@pytest.mark.asyncio
async def test_run_shell_whitelist():
    result = await run_shell("python --version")
    assert result.get("exit_code", -1) == 0 or "error" not in result


@pytest.mark.asyncio
async def test_run_shell_timeout():
    # Use node to simulate a long-running command since sleep is not whitelisted
    result = await run_shell("node -e \"setTimeout(()=>{}, 10000)\"", timeout=1)
    assert "error" in result
    assert "timed out" in result["error"].lower()
