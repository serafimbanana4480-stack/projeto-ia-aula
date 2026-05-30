"""TEST_RUNNER_E2E — end-to-end and integration test execution.

Model: qwen3-coder:7b (CODER tier).
Prompt: config/prompts/test_runner_e2e.md

Supports autonomous execution via ReAct loop:
- Runs end-to-end tests (Playwright, Postman collections, Selenium)
- Tests API contracts (OpenAPI validation)
- Performance/load testing basics (wrk, ab, or Python scripts)
- Integration testing across multiple services
- Generates structured reports with screenshots, logs, response times
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class TestRunnerE2EAgent(AgentBase):
    """End-to-end test runner agent with ReAct tool-use loop.

    Uses the ReAct loop from AgentBase to autonomously:
    1. Discover and run end-to-end tests (Playwright, Postman, Selenium, etc.)
    2. Validate API contracts against OpenAPI specifications
    3. Execute basic performance and load tests
    4. Orchestrate integration tests across multiple services
    5. Produce structured reports with screenshots, logs, and response times
    6. Consult other agents when blockers or bugs are discovered
    """

    name = "TEST_RUNNER_E2E"
    model_key = "coder"
    prompt_file = "test_runner_e2e"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
    }

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run the E2E test agent with ReAct loop for autonomous execution.

        ALWAYS uses the ReAct loop so that file operations, code execution,
        search, and inter-agent consultation are available.
        """
        async for token in self._run_react_loop(request):
            yield token
