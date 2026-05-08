"""Tests for backend.tools.code_executor — sandbox config and dataclass."""
from __future__ import annotations

import pytest

from backend.tools.code_executor import ExecutionResult, SANDBOX_CONFIG, execute_code


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
    def test_raises_not_implemented(self) -> None:
        import asyncio

        with pytest.raises(NotImplementedError):
            asyncio.run(execute_code("print(1)", "python"))
