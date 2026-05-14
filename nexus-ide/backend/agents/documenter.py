"""DOCUMENTER — technical writing agent.

Model: qwen3.5:9b (SMALL).
Prompt: config/prompts/documenter.md
See ARCHITECTURE.md §3.7.

Supports autonomous execution via ReAct loop:
- Reads files to understand what needs documenting
- Writes documentation files
- Searches codebase for context
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class DocumenterAgent(AgentBase):
    name = "DOCUMENTER"
    model_key = "small"
    prompt_file = "documenter"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.WRITE_FILE,
        AgentAction.SEARCH_CODEBASE,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run documenter with ReAct loop for documentation tasks.

        Uses ReAct loop when the task involves writing, generating,
        or updating documentation. Falls back to single-shot for
        simple questions.
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
            "document", "write docs", "generate docs", "readme",
            "comment", "explain", "describe", "create documentation",
            "update docs", "add documentation", "write a guide",
            "documentar", "escrever docs", "gerar docs", "comentar",
            "explicar", "descrever", "atualizar docs",
        ]
        lowered = query.lower()
        return any(marker in lowered for marker in complex_markers)
