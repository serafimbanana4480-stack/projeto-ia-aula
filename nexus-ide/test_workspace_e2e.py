#!/usr/bin/env python3
"""End-to-end test for Workspace Manager in NEXUS IDE."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Ensure backend is importable
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.workspace import (
    read_file_absolute,
    write_file_absolute,
    list_dir_absolute,
    execute_shell,
    execute_python,
    discover_projects,
    get_project_info,
    git_status,
)

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

RESULTS: list[dict] = []


def log_result(
    name: str,
    passed: bool,
    details: str = "",
    duration_ms: float = 0.0,
    concerns: list[str] | None = None,
) -> None:
    RESULTS.append({
        "name": name,
        "passed": passed,
        "details": details,
        "duration_ms": round(duration_ms, 2),
        "concerns": concerns or [],
    })


async def test_read_file_absolute() -> None:
    """Test reading a file outside the project (user's home dir)."""
    start = time.perf_counter()
    home = Path.home()
    target = home / ".gitconfig"
    if not target.exists():
        target = home / ".bashrc"
    if not target.exists():
        target = home / "Documents"
        if target.exists():
            # pick any file inside Documents
            files = [f for f in target.iterdir() if f.is_file()]
            target = files[0] if files else home / "test_dummy.txt"

    if isinstance(target, Path) and target.is_dir():
        # create a temp file in home to read
        target = home / "nexus_test_read.txt"
        target.write_text("hello from nexus test", encoding="utf-8")

    result = await read_file_absolute(str(target))
    duration = (time.perf_counter() - start) * 1000

    concerns: list[str] = []
    if "error" in result:
        log_result("read_file_absolute", False, f"Error: {result['error']}", duration, concerns)
        if target.name == "nexus_test_read.txt":
            target.unlink(missing_ok=True)
        return

    content = result.get("content", "")
    size = result.get("size", 0)
    if size != len(content):
        concerns.append(f"Size mismatch: reported {size}, actual {len(content)}")

    log_result(
        "read_file_absolute",
        True,
        f"Read {size} bytes from {result.get('path')}",
        duration,
        concerns,
    )
    if target.name == "nexus_test_read.txt":
        target.unlink(missing_ok=True)


async def test_write_file_absolute() -> None:
    """Test creating a new file in a temp directory."""
    start = time.perf_counter()
    tmp_dir = Path(tempfile.gettempdir()) / "nexus_workspace_test"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "test_write.txt"

    content = f"NEXUS workspace test file\nCreated at: {datetime.now().isoformat()}\n"
    result = await write_file_absolute(str(target), content)
    duration = (time.perf_counter() - start) * 1000

    concerns: list[str] = []
    if "error" in result:
        log_result("write_file_absolute", False, f"Error: {result['error']}", duration, concerns)
        return

    if not target.exists():
        concerns.append("File was reported as written but does not exist on disk")
        log_result("write_file_absolute", False, "File missing after write", duration, concerns)
        return

    actual = target.read_text(encoding="utf-8")
    if actual != content:
        concerns.append("Written content does not match expected content")

    backup = result.get("backup", {})
    if not backup.get("backed_up") and target.exists():
        # First write — no backup expected since file didn't exist
        if backup.get("reason") != "file did not exist":
            concerns.append(f"Unexpected backup status: {backup}")

    log_result(
        "write_file_absolute",
        len(concerns) == 0,
        f"Wrote {result.get('size')} bytes to {result.get('path')}",
        duration,
        concerns,
    )

    # Cleanup
    target.unlink(missing_ok=True)


async def test_list_dir_absolute() -> None:
    """Test listing a directory."""
    start = time.perf_counter()
    target = str(Path.home() / "Documents")
    if not Path(target).exists():
        target = str(Path.home())

    result = await list_dir_absolute(target, recursive=False)
    duration = (time.perf_counter() - start) * 1000

    concerns: list[str] = []
    if "error" in result:
        log_result("list_dir_absolute", False, f"Error: {result['error']}", duration, concerns)
        return

    items = result.get("items", [])
    count = result.get("count", 0)
    if count != len(items):
        concerns.append(f"Count mismatch: reported {count}, actual {len(items)}")

    if not any(item.get("type") == "dir" for item in items):
        concerns.append("No directories found in listing — possible filter issue")

    log_result(
        "list_dir_absolute",
        len(concerns) == 0,
        f"Listed {count} items in {result.get('path')}",
        duration,
        concerns,
    )


async def test_execute_shell() -> None:
    """Test running shell commands."""
    concerns: list[str] = []

    # Test 1: echo hello
    start = time.perf_counter()
    result = await execute_shell("echo hello")
    duration = (time.perf_counter() - start) * 1000

    if "error" in result:
        log_result("execute_shell (echo)", False, f"Error: {result['error']}", duration, concerns)
    else:
        stdout = result.get("stdout", "").strip()
        if stdout != "hello":
            concerns.append(f"Unexpected stdout for echo: '{stdout}'")
        log_result(
            "execute_shell (echo)",
            stdout == "hello",
            f"stdout='{stdout}', exit_code={result.get('exit_code')}",
            duration,
            concerns,
        )

    # Test 2: python --version
    start = time.perf_counter()
    result = await execute_shell("python --version")
    duration = (time.perf_counter() - start) * 1000

    if "error" in result:
        log_result(
            "execute_shell (python --version)",
            False,
            f"Error: {result['error']}",
            duration,
        )
    else:
        stdout = result.get("stdout", "").strip()
        stderr = result.get("stderr", "").strip()
        output = stdout or stderr
        if "Python" not in output:
            concerns = [f"Unexpected output for python --version: '{output}'"]
        else:
            concerns = []
        log_result(
            "execute_shell (python --version)",
            "Python" in output,
            f"output='{output}', exit_code={result.get('exit_code')}",
            duration,
            concerns,
        )

    # Test 3: blocked command
    start = time.perf_counter()
    result = await execute_shell("rm -rf /")
    duration = (time.perf_counter() - start) * 1000

    if "error" not in result:
        log_result(
            "execute_shell (security)",
            False,
            "Dangerous command was NOT blocked!",
            duration,
            ["CRITICAL: rm -rf / was allowed through"],
        )
    else:
        log_result(
            "execute_shell (security)",
            True,
            f"Correctly blocked: {result.get('error')}",
            duration,
        )


async def test_execute_python() -> None:
    """Test executing a simple Python snippet."""
    start = time.perf_counter()
    code = """
import sys
print("Hello from execute_python")
print(f"Python version: {sys.version_info.major}.{sys.version_info.minor}")
result = 21 * 2
print(f"Result: {result}")
"""
    result = await execute_python(code)
    duration = (time.perf_counter() - start) * 1000

    concerns: list[str] = []
    if "error" in result:
        log_result("execute_python", False, f"Error: {result['error']}", duration, concerns)
        return

    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    success = result.get("success", False)
    returncode = result.get("returncode", -1)

    if returncode != 0:
        concerns.append(f"Non-zero exit code: {returncode}")
    if "Hello from execute_python" not in stdout:
        concerns.append("Expected output not found in stdout")
    if "Result: 42" not in stdout:
        concerns.append("Computation result not found in stdout")
    if stderr:
        concerns.append(f"Unexpected stderr: {stderr[:200]}")

    log_result(
        "execute_python",
        success and len(concerns) == 0,
        f"returncode={returncode}, stdout_len={len(stdout)}, stderr_len={len(stderr)}",
        duration,
        concerns,
    )


async def test_discover_projects() -> None:
    """Test finding projects in user's home."""
    start = time.perf_counter()
    # Scanning the entire home dir is too slow; scan a narrower path
    home = str(Path.home() / "Desktop" / "PROJETO IA AULA GIT CLONE" / "projeto-ia-aula")
    if not Path(home).exists():
        home = str(Path.home())
    result = await discover_projects(home)
    duration = (time.perf_counter() - start) * 1000

    concerns: list[str] = []
    if "error" in result:
        log_result("discover_projects", False, f"Error: {result['error']}", duration, concerns)
        return

    projects = result.get("projects", [])
    count = result.get("count", 0)

    if count != len(projects):
        concerns.append(f"Count mismatch: reported {count}, actual {len(projects)}")

    # Check that nexus-ide itself is found
    nexus_found = any("nexus-ide" in p.get("name", "") for p in projects)
    if not nexus_found:
        concerns.append("nexus-ide project not found in discovery")

    log_result(
        "discover_projects",
        len(concerns) == 0,
        f"Found {count} projects under {result.get('root')}",
        duration,
        concerns,
    )


async def test_get_project_info() -> None:
    """Test analyzing the current project (nexus-ide)."""
    start = time.perf_counter()
    project_path = str(PROJECT_ROOT)
    result = await get_project_info(project_path)
    duration = (time.perf_counter() - start) * 1000

    concerns: list[str] = []
    if "error" in result:
        log_result("get_project_info", False, f"Error: {result['error']}", duration, concerns)
        return

    name = result.get("name", "")
    language = result.get("language", "")
    framework = result.get("framework")
    git = result.get("git", {})
    file_count = result.get("file_count", 0)
    dir_count = result.get("dir_count", 0)

    if name != "nexus-ide":
        concerns.append(f"Unexpected project name: '{name}'")
    if language != "python":
        concerns.append(f"Unexpected detected language: '{language}'")
    if not git.get("is_repo"):
        concerns.append("Project is a git repo but was not detected as such")
    if file_count == 0:
        concerns.append("File count is zero — possible traversal issue")
    if dir_count == 0:
        concerns.append("Directory count is zero — possible traversal issue")

    log_result(
        "get_project_info",
        len(concerns) == 0,
        (
            f"name={name}, language={language}, framework={framework}, "
            f"git={git.get('is_repo')}, files={file_count}, dirs={dir_count}"
        ),
        duration,
        concerns,
    )


async def test_git_status() -> None:
    """Test checking git status."""
    start = time.perf_counter()
    project_path = str(PROJECT_ROOT)
    result = await git_status(project_path)
    duration = (time.perf_counter() - start) * 1000

    concerns: list[str] = []
    if "error" in result:
        log_result("git_status", False, f"Error: {result['error']}", duration, concerns)
        return

    output = result.get("output", "")
    exit_code = result.get("exit_code", -1)

    if exit_code != 0:
        concerns.append(f"Non-zero exit code: {exit_code}")
    if "##" not in output:
        concerns.append("Expected git status output format not found (missing '##')")

    log_result(
        "git_status",
        exit_code == 0,
        f"exit_code={exit_code}, output_lines={len(output.splitlines())}",
        duration,
        concerns,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    print("=" * 70)
    print("NEXUS IDE Workspace Manager — End-to-End Test")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")
    print("=" * 70)
    print()

    tests = [
        test_read_file_absolute,
        test_write_file_absolute,
        test_list_dir_absolute,
        test_execute_shell,
        test_execute_python,
        test_discover_projects,
        test_get_project_info,
        test_git_status,
    ]
    for test in tests:
        print(f"Running {test.__name__} ...", flush=True)
        await test()
        print(f"  -> done", flush=True)

    print()
    print("=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    passed = 0
    failed = 0
    for r in RESULTS:
        status = "PASS" if r["passed"] else "FAIL"
        if r["passed"]:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {r['name']:45s} {r['duration_ms']:>8.2f} ms")
        if r["details"]:
            print(f"         -> {r['details']}")
        for c in r["concerns"]:
            print(f"         [!] {c}")

    print()
    print(f"Total: {passed} passed, {failed} failed out of {len(RESULTS)} tests")
    print("=" * 70)

    # Also write a JSON report
    report_path = PROJECT_ROOT / "test_workspace_e2e_report.json"
    report_path.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    print(f"\nDetailed JSON report written to: {report_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
