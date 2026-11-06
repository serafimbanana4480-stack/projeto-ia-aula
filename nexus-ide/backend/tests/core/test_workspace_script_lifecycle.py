"""Lifecycle and resource bounds for workspace script execution."""

from __future__ import annotations

import asyncio
import shlex
import sys
from pathlib import Path

import pytest

from backend.core import workspace_shell
from backend.core.workspace_shell import execute_script


def _write_script(tmp_path: Path, source: str) -> Path:
    script = tmp_path / "script.py"
    script.write_text(source, encoding="utf-8")
    return script


async def test_timeout_terminates_script_before_it_can_write_late_marker(
    tmp_path: Path,
) -> None:
    script = _write_script(
        tmp_path,
        "import time\n"
        "time.sleep(0.3)\n"
        "with open('late-marker.txt', 'w', encoding='utf-8') as marker:\n"
        "    marker.write('script survived timeout')\n",
    )

    result = await execute_script(str(script), cwd=str(tmp_path), timeout=0.05)
    assert "timed out" in str(result.get("error", "")).lower()
    assert result.get("termination_confirmed") is True
    await asyncio.sleep(1)
    assert not (tmp_path / "late-marker.txt").exists()


async def test_cancelling_script_execution_terminates_the_child(
    tmp_path: Path,
) -> None:
    script = _write_script(
        tmp_path,
        "import time\n"
        "time.sleep(0.4)\n"
        "with open('cancel-marker.txt', 'w', encoding='utf-8') as marker:\n"
        "    marker.write('script survived cancellation')\n",
    )
    execution = asyncio.create_task(
        execute_script(str(script), cwd=str(tmp_path), timeout=5)
    )

    await asyncio.sleep(0.1)
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution
    await asyncio.sleep(0.5)
    assert not (tmp_path / "cancel-marker.txt").exists()


async def test_script_execution_does_not_inherit_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "script-test-secret")
    script = _write_script(
        tmp_path,
        "import os\n"
        "print(os.getenv('OPENROUTER_API_KEY', 'MISSING'))\n",
    )

    result = await execute_script(str(script), cwd=str(tmp_path))

    assert result.get("exit_code") == 0, result
    assert "script-test-secret" not in str(result.get("stdout", ""))
    assert "MISSING" in str(result.get("stdout", ""))


async def test_script_output_is_capped_and_reports_truncation(tmp_path: Path) -> None:
    script = _write_script(
        tmp_path,
        "import sys\n"
        "print('x' * (2 * 1024 * 1024))\n"
        "sys.stderr.write('y' * (2 * 1024 * 1024))\n",
    )

    result = await execute_script(str(script), cwd=str(tmp_path))

    assert result.get("exit_code") == 0, result
    assert "[output truncated" in str(result.get("stdout", ""))
    assert "[output truncated" in str(result.get("stderr", ""))


async def test_timeout_reports_when_process_termination_cannot_be_confirmed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(workspace_shell, "_SCRIPT_KILL_WAIT_SECONDS", 0.02)
    monkeypatch.setattr(workspace_shell, "_kill_script_process_tree", lambda _process: False)
    script = _write_script(tmp_path, "import time\ntime.sleep(0.25)\n")

    result = await execute_script(str(script), cwd=str(tmp_path), timeout=0.05)

    assert result.get("timed_out") is True
    assert result.get("termination_confirmed") is False
    assert "termination could not be confirmed" in str(result.get("error", ""))


async def test_shell_output_is_capped(tmp_path: Path) -> None:
    script = _write_script(
        tmp_path,
        "import sys\n"
        "print('x' * (2 * 1024 * 1024))\n"
        "sys.stderr.write('y' * (2 * 1024 * 1024))\n",
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"

    result = await workspace_shell.execute_shell(
        command, cwd=str(tmp_path), timeout=10
    )

    assert result.get("exit_code") == 0, result
    assert "[output truncated" in str(result.get("stdout", ""))
    assert "[output truncated" in str(result.get("stderr", ""))
    assert len(str(result.get("stdout", ""))) < workspace_shell._SCRIPT_OUTPUT_LIMIT_BYTES + 100
    assert len(str(result.get("stderr", ""))) < workspace_shell._SCRIPT_OUTPUT_LIMIT_BYTES + 100


async def test_shell_timeout_kills_descendant_processes(tmp_path: Path) -> None:
    marker = tmp_path / "late-descendant-marker.txt"
    child_pid_path = tmp_path / "descendant.pid"
    child_source = (
        "import os, time\n"
        f"with open({str(child_pid_path)!r}, 'w', encoding='utf-8') as f: "
        "f.write(str(os.getpid()))\n"
        "time.sleep(6)\n"
        f"with open({str(marker)!r}, 'w', encoding='utf-8') as f: "
        "f.write('late')\n"
    )
    script = _write_script(
        tmp_path,
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_source!r}])\n"
        "time.sleep(10)\n",
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"

    result = await workspace_shell.execute_shell(
        command, cwd=str(tmp_path), timeout=5.0
    )
    assert result.get("timed_out") is True, result
    assert result.get("termination_confirmed") is True, result
    assert child_pid_path.exists()
    import psutil

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    assert not psutil.pid_exists(child_pid)
    await asyncio.sleep(6.2)
    assert not marker.exists()
