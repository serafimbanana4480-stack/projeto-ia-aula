"""DEBUGGER — root cause analysis.

Model: qwen3-coder:7b (MEDIUM). Can execute code in Docker sandbox.
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
    model_key = "medium"
    prompt_file = "debugger"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run debugger with ReAct loop for debugging tasks.

        Uses ReAct loop when the task involves debugging, fixing,
        or diagnosing issues. Falls back to single-shot for simple questions.
        """
        is_complex = self._is_complex_task(request.query)

        if is_complex and request.max_iterations > 1:
            async for token in self._run_react_loop(request):
                yield token
        else:
            async for token in self.stream_llm(request):
                yield token

    def _is_complex_task(self, query: str) -> bool:
        """Heuristic to detect tasks needing the ReAct loop."""
        complex_markers = [
            "debug", "fix", "error", "bug", "crash", "exception",
            "traceback", "not working", "broken", "issue",
            "why does", "what's wrong", "diagnose", "troubleshoot",
            "stack trace", "fail", "failing",
            "depurar", "corrigir", "erro", "falha", "problema",
        ]
        lowered = query.lower()
        return any(marker in lowered for marker in complex_markers)
