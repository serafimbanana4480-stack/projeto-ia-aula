"""Process cleanup and report isolation for the pytest tool."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from backend.tools import test_runner


class _BlockingProcess:
    def __init__(self) -> None:
        self.pid = 424242
        self.returncode: int | None = None
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def communicate(self) -> tuple[bytes, bytes]:
        self.started.set()
        await self.stopped.wait()
        return b"partial pytest output", b""


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
@pytest.mark.parametrize("cancel", [False, True])  # type: ignore[untyped-decorator]
async def test_timeout_and_cancellation_terminate_the_subprocess(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    process = _BlockingProcess()
    terminated: list[int] = []

    async def create_process(*_args: Any, **_kwargs: Any) -> _BlockingProcess:
        return process

    async def terminate_process_tree(proc: _BlockingProcess) -> None:
        terminated.append(proc.pid)
        proc.returncode = -9
        proc.stopped.set()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(test_runner, "_terminate_process_tree", terminate_process_tree)

    task = asyncio.create_task(
        test_runner._run_pytest([], timeout=1, interpreter=sys.executable)
    )
    await process.started.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert result == (-1, "partial pytest output", "Timeout after 1s")

    assert terminated == [process.pid]
    assert process.returncode == -9


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_concurrent_runs_use_distinct_junit_and_coverage_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    shared_legacy_report = tmp_path / "nexus-junit.xml"
    shared_legacy_report.write_text("keep this existing report", encoding="utf-8")
    report_paths: list[Path] = []
    coverage_paths: list[str] = []

    async def write_result(
        args: list[str],
        cwd: str | None = None,
        timeout: int = 600,
        interpreter: str | None = None,
    ) -> tuple[int, str, str]:
        junit_arg = next(arg for arg in args if arg.startswith("--junit-xml="))
        report = Path(junit_arg.split("=", maxsplit=1)[1])
        report_paths.append(report)
        coverage_arg = next(
            arg for arg in args if arg.startswith("--cov-report=xml:")
        )
        coverage_paths.append(coverage_arg.split(":", maxsplit=1)[1])
        report.write_text(
            '<testsuites><testsuite tests="1" failures="0" errors="0" '
            'skipped="0"><testcase classname="sample" name="passes" '
            'time="0.01" /></testsuite></testsuites>',
            encoding="utf-8",
        )
        return 0, "1 passed in 0.01s", ""

    monkeypatch.setattr(test_runner, "_run_pytest", write_result)

    results = await asyncio.gather(
        test_runner.run_tests(project_path=str(tmp_path), coverage=True),
        test_runner.run_tests(project_path=str(tmp_path), coverage=True),
    )

    assert all(result["ok"] and result["total"] == 1 for result in results)
    assert len(set(report_paths)) == 2
    assert len(set(coverage_paths)) == 2
    assert shared_legacy_report.read_text(encoding="utf-8") == "keep this existing report"
    assert all(not report.exists() for report in report_paths)


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_terminate_process_tree_stops_descendant_process() -> None:
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print(child.pid, flush=True); time.sleep(60)"
    )
    options = (
        {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        parent_code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        **options,
    )
    try:
        assert process.stdout is not None
        child_pid = int((await asyncio.wait_for(process.stdout.readline(), timeout=10)).strip())
        await test_runner._terminate_process_tree(process)

        if os.name == "nt":
            probe = await asyncio.create_subprocess_exec(
                "tasklist.exe",
                "/FI",
                f"PID eq {child_pid}",
                "/NH",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            output, _ = await probe.communicate()
            assert str(child_pid) not in output.decode(errors="replace")
        else:
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)
    finally:
        if process.returncode is None:
            await test_runner._terminate_process_tree(process)
