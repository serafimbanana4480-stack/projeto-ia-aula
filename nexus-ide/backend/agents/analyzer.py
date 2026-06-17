"""ANALYZER — critical code/architecture reviewer.

Model: deepseek-r1:8b (REASONING tier) with thinking mode.
Prompt: config/prompts/analyzer.md
See ARCHITECTURE.md §3.5.

Supports autonomous execution via ReAct loop:
- Reads files to understand code structure
- Searches codebase for patterns and issues
- Reads documentation for context
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest


class AnalyzerAgent(AgentBase):
    name = "ANALYZER"
    model_key = "reasoning"
    prompt_file = "analyzer"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.READ_FILE_ABSOLUTE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.SEARCH_SYMBOLS,
        AgentAction.INDEX_SYMBOLS,
        AgentAction.READ_DOCS,
        AgentAction.ANALYZE_DATA,
        AgentAction.CONSULT_AGENT,
        AgentAction.RECALL_CONTEXT,
        AgentAction.STORE_MEMORY,
        AgentAction.EXECUTE_CODE,
    }


