"""BUG_HUNTER_RUNTIME — runtime bug hunter and dynamic test executor.

Model: qwen3-coder:7b (CODER tier).
Prompt: config/prompts/bug_hunter_runtime.md

Supports autonomous execution via ReAct loop:
- Runs the test suite and captures failures
- Executes code with edge cases and fuzzing-like inputs
- Checks for runtime errors, exceptions, and memory leaks
- Tests API endpoints with malformed inputs
- Generates structured reports with stack traces and reproduction steps
- Consults BUG_HUNTER_STATIC, CODER, or DEBUGGER when needed
"""

from __future__ import annotations

from .base import AgentAction, AgentBase


class BugHunterRuntimeAgent(AgentBase):
    """Runtime bug hunter with ReAct tool-use loop.

    Uses the ReAct loop from AgentBase to autonomously:
    1. Detect the project's test framework and runtime environment
    2. Run the test suite and capture all failures, errors, and skips
    3. Execute code with edge cases, fuzzing-like inputs, and boundary values
    4. Check for runtime errors, unhandled exceptions, and memory leaks
    5. Test API endpoints with malformed, unexpected, and malicious inputs
    6. Produce a structured report with stack traces and reproduction steps
    7. Consult BUG_HUNTER_STATIC, CODER, or DEBUGGER when deeper analysis is needed
    """

    name = "BUG_HUNTER_RUNTIME"
    model_key = "coder"
    prompt_file = "bug_hunter_runtime"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
    }
