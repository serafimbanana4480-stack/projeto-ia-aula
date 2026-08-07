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

from .base import AgentAction, AgentBase


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
        AgentAction.READ_FILE_ABSOLUTE,
        AgentAction.WRITE_FILE,
        AgentAction.WRITE_FILE_ABSOLUTE,
        AgentAction.LIST_DIR,
        AgentAction.LIST_DIR_ABSOLUTE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.SEARCH_SYMBOLS,
        AgentAction.INDEX_SYMBOLS,
        AgentAction.CONSULT_AGENT,
        AgentAction.EXECUTE_CODE,
        AgentAction.RUN_SHELL,
        AgentAction.RUN_TESTS,
        AgentAction.RUN_LINT,
        AgentAction.TYPE_CHECK,
        AgentAction.SPAWN_TASK,
        AgentAction.RECALL_CONTEXT,
        AgentAction.STORE_MEMORY,
        AgentAction.FETCH_URL,
    }
