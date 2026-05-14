"""Tests for backend.tools.code_executor — sandbox config, dataclass, and execution."""

from __future__ import annotations

import asyncio

import pytest

from backend.tools.code_executor import SANDBOX_CONFIG, ExecutionResult, execute_code


class TestExecutionResult:
    def test_fields(self) -> None:
        result = ExecutionResult(
            stdout="hello",
            stderr="",
            exit_code=0,
            execution_time=1.23,
            timed_out=False,
        )
        assert result.stdout == "hello"
        assert result.timed_out is False
        assert result.execution_time >= 0


class TestSandboxConfig:
    def test_security_hardening(self) -> None:
        assert SANDBOX_CONFIG["network_mode"] == "none"
        assert SANDBOX_CONFIG["mem_limit"] == "512m"
        assert SANDBOX_CONFIG["read_only"] is True
        assert SANDBOX_CONFIG["user"] == "nobody"
        assert "no-new-privileges" in SANDBOX_CONFIG["security_opt"]
        assert SANDBOX_CONFIG["cap_drop"] == ["ALL"]

    def test_tmpfs_present(self) -> None:
        assert "/tmp" in SANDBOX_CONFIG["tmpfs"]


class TestExecuteCode:
    def test_python_hello(self) -> None:
        """Test that Python code executes and returns output."""
        result = asyncio.run(execute_code("print('hello world')", "python"))
        assert isinstance(result, ExecutionResult)
        assert result.exit_code == 0
        assert "hello world" in result.stdout
        assert result.timed_out is False

    def test_unsupported_language(self) -> None:
        """Test that unsupported languages raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported language"):
            asyncio.run(execute_code("code", "ruby"))

    def test_python_error(self) -> None:
        """Test that Python code with errors returns non-zero exit code."""
        result = asyncio.run(execute_code("raise ValueError('test error')", "python"))
        assert result.exit_code != 0
        assert "test error" in result.stderr

    def test_timeout(self) -> None:
        """Test that code execution times out correctly."""
        result = asyncio.run(execute_code("import time; time.sleep(60)", "python", timeout=1))
        assert result.timed_out is True
