"""RESEARCHER — online research agent.

Model: qwen3.5:9b (SMALL) with Brave Search + URL fetching.
Prompt: config/prompts/researcher.md
See ARCHITECTURE.md §3.3 and §5.3 (web search pipeline).

Supports autonomous execution via ReAct loop:
- Searches the web for information
- Fetches and reads URLs for detailed content
- Reads documentation for reference
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class ResearcherAgent(AgentBase):
    name = "RESEARCHER"
    model_key = "medium"  # qwen2.5-coder:7b for thorough research with tool use
    prompt_file = "researcher"
    supported_actions = {
        AgentAction.SEARCH_WEB,
        AgentAction.FETCH_URL,
        AgentAction.READ_DOCS,
        AgentAction.RECALL_CONTEXT,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run researcher with ReAct loop for research tasks.

        Uses ReAct loop when the task involves searching, looking up
        information, or fetching URLs. Falls back to single-shot for
        simple knowledge questions.
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
            "search for", "look up", "find information", "research",
            "what is the latest", "current status", "fetch",
            "browse", "investigate", "explore", "look into",
            "compare", "what does", "how does", "documentation",
            "procurar", "pesquisar", "investigar", "explorar",
        ]
        lowered = query.lower()
        return any(marker in lowered for marker in complex_markers)
