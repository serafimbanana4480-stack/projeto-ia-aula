"""Tests for shell_runner."""

from __future__ import annotations

import pytest
import sys

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
    result = await run_shell(f'"{sys.executable}" --version')
    assert result.get("exit_code", -1) == 0 or "error" not in result


@pytest.mark.asyncio
async def test_run_shell_timeout():
    # Create a tiny Python script that sleeps so we can test timeout without
    # relying on blocked flags like -e / -c.
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("import time; time.sleep(10)\n")
        script_path = f.name

    try:
        result = await run_shell(f'"{sys.executable}" "{script_path}"', timeout=1)
        assert "error" in result
        assert "timed out" in result["error"].lower()
    finally:
        Path(script_path).unlink(missing_ok=True)
