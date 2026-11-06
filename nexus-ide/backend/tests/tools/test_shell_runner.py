"""Tests for shell_runner."""

from __future__ import annotations

import os
import sys

import pytest

from backend.core import workspace_shell
from backend.tools.shell_runner import run_python_script, run_shell


@pytest.mark.asyncio
async def test_execute_shell_passes_only_allowlisted_environment(monkeypatch):
    captured = {}

    async def fake_run(command, cwd, timeout, *, env=None):
        captured.update({"args": command, "cwd": cwd, "timeout": timeout, "env": env})
        return 0, "ok", "", False, True

    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "cloud-secret")
    monkeypatch.setenv("JWT_SECRET", "jwt-secret")
    monkeypatch.setattr(workspace_shell, "_run_script_process", fake_run)
    monkeypatch.setattr(
        workspace_shell, "_validate_shell_command", lambda command: (True, "")
    )

    result = await workspace_shell.execute_shell(
        "git status",
        env={"CI": "true", "GITHUB_TOKEN": "tool-secret"},
    )

    assert isinstance(captured.get("args"), (list, tuple))
    assert captured["args"] == ["git", "status"]
    child_env = captured["env"]
    assert result["exit_code"] == 0
    assert "PATH" in child_env
    assert child_env["CI"] == "true"
    secret_names = {
        "OPENAI_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "JWT_SECRET",
        "GITHUB_TOKEN",
    }
    assert not secret_names.intersection(child_env)


@pytest.mark.asyncio
async def test_workspace_python_uses_scrubbed_environment(monkeypatch, tmp_path):
    captured = {}

    async def fake_run(command, cwd, timeout, *, env=None):
        captured.update({"command": command, "cwd": cwd, "timeout": timeout, "env": env})
        return 0, "ok", "", False, True

    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setenv("JWT_SECRET", "signing-secret")
    monkeypatch.setattr(workspace_shell, "_run_script_process", fake_run)

    result = await workspace_shell.execute_python("print('ok')", cwd=str(tmp_path))

    assert result["success"] is True
    assert captured["command"][0] == sys.executable
    assert captured["cwd"] == tmp_path.resolve()
    assert "OPENAI_API_KEY" not in captured["env"]
    assert "JWT_SECRET" not in captured["env"]


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


# ---------------------------------------------------------------------------
# D4 — the python execution path must not leak server credentials
# ---------------------------------------------------------------------------


def _capture_python_child_env(monkeypatch) -> dict:
    """Patch ``subprocess.Popen`` and return the dict it was called with."""
    captured: dict = {}

    class CompletedProcess:
        returncode = 0

        def communicate(self):
            return "", ""

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return CompletedProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen, raising=False)
    return captured


@pytest.mark.asyncio
async def test_python_execution_environment_has_no_credentials(monkeypatch, tmp_path):
    """Model-supplied python code must not inherit the server credentials."""
    captured = _capture_python_child_env(monkeypatch)

    monkeypatch.setenv("OPENROUTER_API_KEY", "provider-secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "anthropic-secret")
    monkeypatch.setenv("SECRET_KEY", "app-secret")
    monkeypatch.setenv("DB_PASSWORD", "db-secret")
    monkeypatch.setenv("AWS_CREDENTIAL_FILE", "creds-file")
    monkeypatch.setenv("NEXUS_SECRET_TOKEN", "nexus-secret")

    result = await run_python_script("print('hello')", project_path=str(tmp_path))

    child_env = captured.get("env")
    assert child_env is not None, "the child process must get an explicit environment"
    assert result.get("exit_code") == 0

    secret_names = {
        "OPENROUTER_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "SECRET_KEY",
        "DB_PASSWORD",
        "AWS_CREDENTIAL_FILE",
        "NEXUS_SECRET_TOKEN",
    }
    assert not secret_names.intersection(child_env)

    # Nothing that even looks like a credential may cross the boundary.
    markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH", "PRIVATE")
    for name in child_env:
        assert not any(marker in name.upper() for marker in markers), name


@pytest.mark.asyncio
async def test_python_execution_environment_keeps_path_and_temp(monkeypatch, tmp_path):
    """The scrubbed environment still carries the harmless variables."""
    captured = _capture_python_child_env(monkeypatch)

    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    monkeypatch.setenv("NEXUS_SUBPROCESS_TIMEOUT", "300")

    result = await run_python_script("print('hello')", project_path=str(tmp_path))

    child_env = captured.get("env")
    assert child_env is not None
    assert result.get("exit_code") == 0
    assert child_env.get("PATH")
    assert child_env.get("TEMP") == str(tmp_path)
    assert child_env.get("NEXUS_SUBPROCESS_TIMEOUT") == "300"
