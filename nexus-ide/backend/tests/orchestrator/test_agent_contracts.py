"""Focused contracts for Task 8 agent scopes and typed tool evidence."""

from __future__ import annotations

import pytest

from backend.orchestrator.agent_capabilities import (
    FileLockRegistry,
    capability_matrix,
    get_agent_capability,
    validate_agent_contract,
)
from backend.tools import registry
from backend.tools.registry import ToolSpec, execute_tool, register_tool


def test_registered_agents_have_capabilities() -> None:
    matrix = capability_matrix()
    assert matrix
    for name, capability in matrix.items():
        assert capability.name == name
        assert capability.allowed_models
        assert capability.max_concurrency >= 1
        assert get_agent_capability(name) == capability


def test_contract_rejects_unknown_model_and_tool() -> None:
    errors = validate_agent_contract("CODER", "unknown-model", ["no_such_tool"])
    assert any("model" in error for error in errors)
    assert any("tool" in error for error in errors)


def test_same_scope_lock_has_one_owner() -> None:
    locks = FileLockRegistry()
    assert locks.acquire("src/app.py", "run-1")
    assert not locks.acquire("src/app.py", "run-2")
    assert locks.owner("src/app.py") == "run-1"
    locks.release("src/app.py", "run-1")
    assert locks.owner("src/app.py") is None


@pytest.mark.asyncio
async def test_tool_schema_validation_and_evidence() -> None:
    async def handler(value: int) -> dict:
        return {"command": "probe", "exit_code": 0, "value": value}

    register_tool(
        ToolSpec(
            name="task8_contract_probe",
            description="test probe",
            schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
            handler=handler,
        )
    )
    ok = await execute_tool("task8_contract_probe", "task8-contract", {"value": 1})
    assert ok["ok"] is True
    assert ok["exit_code"] == 0
    assert ok["evidence"]["verified"] is True
    bad = await execute_tool("task8_contract_probe", "task8-contract", {})
    assert bad["ok"] is False
    assert bad["error_category"] == "invalid_args"
    registry.reset_tool_failures("task8-contract")
