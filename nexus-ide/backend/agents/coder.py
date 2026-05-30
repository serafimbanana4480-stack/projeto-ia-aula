"""CODER — production code generation agent with ReAct loop.

Model: qwen2.5-coder:7b (CODER tier). Context 8K.
Prompt: config/prompts/coder.md
See ARCHITECTURE.md §3.4.

Supports autonomous execution via ReAct loop:
- Reads files to understand existing code
- Writes files to implement changes
- Executes code to verify correctness
- Iterates until the task is complete
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class CoderAgent(AgentBase):
    """Code generation agent with ReAct tool-use loop.

    Uses the ReAct loop from AgentBase to autonomously:
    1. Read existing files to understand the codebase
    2. Write new files or modify existing ones
    3. Execute code to verify it works
    4. Iterate until the task is complete
    """

    name = "CODER"
    model_key = "coder"
    prompt_file = "coder"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.WRITE_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
        AgentAction.EXECUTE_CODE,
    }

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run the coder agent with ReAct loop for autonomous execution.

        ALWAYS uses the ReAct loop so that file operations, code execution,
        and other tools are available for every query.
        """
        async for token in self._run_react_loop(request):
            yield token
