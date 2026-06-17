"""TEST_RUNNER_UNIT — automated unit test execution and generation.

Model: qwen3-coder:7b (CODER tier).
Prompt: config/prompts/test_runner_unit.md

Supports autonomous execution via ReAct loop:
- Detects test framework (pytest, jest, unittest, go test, etc.)
- Runs unit tests and captures output with coverage
- Generates missing tests for untested functions
- Identifies flaky tests
- Generates structured reports
- Consults BUG_HUNTER_STATIC or CODER when tests fail
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class TestRunnerUnitAgent(AgentBase):
    """Unit test runner agent with ReAct tool-use loop.

    Uses the ReAct loop from AgentBase to autonomously:
    1. Detect the project's test framework and configuration
    2. Run unit tests and capture output with coverage metrics
    3. Generate missing tests for untested or under-tested functions
    4. Identify flaky or non-deterministic tests
    5. Produce structured pass/fail/skip/coverage reports
    6. Consult BUG_HUNTER_STATIC or CODER when tests fail
    """

    name = "TEST_RUNNER_UNIT"
    model_key = "coder"
    prompt_file = "test_runner_unit"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.WRITE_FILE,
        AgentAction.CONSULT_AGENT,
    }


