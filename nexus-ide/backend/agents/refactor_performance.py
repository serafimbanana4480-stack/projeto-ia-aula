"""REFACTOR_PERFORMANCE — performance refactoring agent with ReAct loop.

Model: CODER tier (resolved via config/models.yaml).
Prompt: config/prompts/refactor_performance.md

Supports autonomous execution via ReAct loop:
- Reads files to understand performance bottlenecks
- Profiles code execution time and memory usage
- Identifies bottlenecks (N+1 queries, inefficient algorithms)
- Applies optimizations: caching, memoization, async patterns, vectorization
- Compares before/after performance with benchmarks
- Generates performance reports with metrics
"""

from __future__ import annotations

from .base import AgentAction, AgentBase


class RefactorPerformanceAgent(AgentBase):
    """Performance refactoring agent with ReAct tool-use loop.

    Uses the ReAct loop from AgentBase to autonomously:
    1. Read existing files to understand the codebase
    2. Profile and benchmark code to establish baselines
    3. Identify bottlenecks (N+1 queries, inefficient algorithms, hotspots)
    4. Apply optimizations (caching, memoization, async patterns, vectorization)
    5. Execute code to verify improvements with before/after metrics
    6. Iterate until performance goals are met
    """

    name = "REFACTOR_PERFORMANCE"
    model_key = "coder"
    prompt_file = "refactor_performance"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.WRITE_FILE,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
    }
