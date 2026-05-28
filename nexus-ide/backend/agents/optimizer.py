"""OPTIMIZER — performance tuning agent.

Model: qwen2.5-coder:7b (CODER tier) with optional thinking mode.
Prompt: config/prompts/optimizer.md
See ARCHITECTURE.md §3.8.

Supports autonomous execution via ReAct loop:
- Reads files to understand performance bottlenecks
- Executes code to benchmark and verify improvements
- Searches codebase for optimization opportunities
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class OptimizerAgent(AgentBase):
    name = "OPTIMIZER"
    model_key = "coder"  # qwen2.5-coder:7b for benchmarking + code optimization
    prompt_file = "optimizer"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.ANALYZE_DATA,
    }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run with ReAct loop so tools are always available."""
        async for token in self._run_react_loop(request):
            yield token
