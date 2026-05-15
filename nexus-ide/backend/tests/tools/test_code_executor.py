"""Tests for backend.tools.code_executor — dataclass and execution."""

from __future__ import annotations

import asyncio

import pytest

from backend.tools.code_executor import ExecutionResult, execute_code


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
    def test_sandbox_executor_available(self) -> None:
        """Verify SandboxExecutor is importable and provides security."""
        from backend.sandbox.executor import SandboxConfig
        config = SandboxConfig()
        assert config.network_enabled is False
        assert config.max_memory_mb == 512
        assert config.read_only_root is True
        assert config.timeout_seconds == 30

    def test_dangerous_command_detector(self) -> None:
        """Verify dangerous command detection works."""
        from backend.sandbox.executor import DangerousCommandDetector, RiskLevel
        risk, reasons = DangerousCommandDetector.assess_risk("rm -rf /")
        assert risk == RiskLevel.CRITICAL
        assert len(reasons) > 0


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
