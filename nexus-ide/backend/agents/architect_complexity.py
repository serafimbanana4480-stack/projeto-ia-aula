"""ARCHITECT_COMPLEXITY — complexity analysis & decomposition specialist agent.

Model: reasoning tier (deep thinking) with ReAct loop.
Prompt: config/prompts/architect_complexity.md

Supports autonomous execution via ReAct loop:
- Reads files to understand code structure
- Searches codebase for patterns, coupling, and dependencies
- Consults other agents (ANALYZER, ARCHITECT) for specialized input
- Analyzes data to produce complexity reports and heatmaps
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class ArchitectComplexityAgent(AgentBase):
    name = "ARCHITECT_COMPLEXITY"
    model_key = "reasoning"
    prompt_file = "architect_complexity"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
        AgentAction.ANALYZE_DATA,
    }


