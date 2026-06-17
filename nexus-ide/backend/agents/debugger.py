"""DEBUGGER — root cause analysis.

Model: qwen2.5-coder:7b (CODER tier). Can execute code in Docker sandbox.
Prompt: config/prompts/debugger.md
See ARCHITECTURE.md §3.6.

Supports autonomous execution via ReAct loop:
- Reads files to understand the code causing issues
- Executes code to reproduce and verify bugs
- Searches codebase for related issues
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class DebuggerAgent(AgentBase):
    name = "DEBUGGER"
    model_key = "coder"
    prompt_file = "debugger"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.READ_FILE_ABSOLUTE,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.SEARCH_SYMBOLS,
        AgentAction.INDEX_SYMBOLS,
        AgentAction.CONSULT_AGENT,
        AgentAction.RECALL_CONTEXT,
        AgentAction.STORE_MEMORY,
    }


