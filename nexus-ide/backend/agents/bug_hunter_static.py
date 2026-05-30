"""BUG_HUNTER_STATIC — static analysis and security vulnerability hunter.

Model: qwen3-coder:7b (CODER tier).
Prompt: config/prompts/bug_hunter_static.md

Supports autonomous execution via ReAct loop:
- Runs static analysis tools (pylint, mypy, bandit, ruff)
- Checks for security vulnerabilities (SQL injection, XSS, path traversal)
- Analyzes code complexity and cyclomatic complexity
- Detects anti-patterns and code smells
- Generates structured severity reports
- Consults CODER or DEBUGGER when fixes are needed
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class BugHunterStaticAgent(AgentBase):
    """Static analysis bug hunter with ReAct tool-use loop.

    Uses the ReAct loop from AgentBase to autonomously:
    1. Discover the project's language and tooling setup
    2. Run static analysis tools (pylint, mypy, bandit, ruff, etc.)
    3. Search the codebase for known vulnerability patterns
    4. Analyze code complexity and flag hotspots
    5. Detect anti-patterns and code smells
    6. Produce a structured report with CRITICAL/HIGH/MEDIUM/LOW severity
    7. Consult CODER or DEBUGGER when automated fixes are appropriate
    """

    name = "BUG_HUNTER_STATIC"
    model_key = "coder"
    prompt_file = "bug_hunter_static"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.EXECUTE_CODE,
        AgentAction.CONSULT_AGENT,
    }

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run the static bug hunter with ReAct loop for autonomous execution.

        ALWAYS uses the ReAct loop so that file operations, code execution,
        search, and inter-agent consultation are available.
        """
        async for token in self._run_react_loop(request):
            yield token
