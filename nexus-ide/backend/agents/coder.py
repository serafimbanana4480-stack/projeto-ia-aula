"""CODER — production code generation agent with ReAct loop.

Model: qwen2.5-coder:7b (MEDIUM). Context 8K.
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
    model_key = "medium"
    prompt_file = "coder"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.WRITE_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
        AgentAction.EXECUTE_CODE,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run the coder agent with ReAct loop for autonomous execution.

        For simple queries, falls back to single-shot streaming.
        For complex tasks (file creation, code changes), uses the full ReAct loop.
        """
        # Check if the query suggests a complex multi-step task
        is_complex = self._is_complex_task(request.query)

        if is_complex and request.max_iterations > 1:
            # Use ReAct loop for complex tasks
            async for token in self._run_react_loop(request):
                yield token
        else:
            # Simple single-shot for quick questions
            async for token in self.stream_llm(request):
                yield token

    def _is_complex_task(self, query: str) -> bool:
        """Heuristic to detect complex tasks that need the ReAct loop."""
        complex_markers = [
            "create a", "build a", "implement", "write a", "make a",
            "add ", "refactor", "set up", "configure", "develop",
            "generate", "scaffold", "initialize", "install",
            "fix the", "debug", "update the", "modify",
            "criar", "construir", "implementar", "desenvolver",
            "configurar", "gerar", "corrigir", "atualizar",
        ]
        lowered = query.lower()
        return any(marker in lowered for marker in complex_markers)
