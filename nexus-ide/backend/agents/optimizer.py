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
        """Run optimizer with ReAct loop for performance tasks.

        Uses ReAct loop when the task involves optimizing, benchmarking,
        or improving performance. Falls back to single-shot for simple questions.
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
            "optimize", "performance", "speed up", "slow", "bottleneck",
            "benchmark", "improve", "faster", "efficient", "memory usage",
            "cpu usage", "latency", "throughput", "profile",
            "otimizar", "desempenho", "acelerar", "lento", "gargalo",
        ]
        lowered = query.lower()
        return any(marker in lowered for marker in complex_markers)
