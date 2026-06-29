"""RESEARCHER_WEB — deep web research agent.

Model: qwen2.5-coder:7b (CODER tier) with recursive link following.
Prompt: config/prompts/researcher_web.md

Supports autonomous execution via ReAct loop:
- Searches the web for information
- Fetches and reads URLs for detailed content
- Follows links recursively (max depth 2)
- Cross-references multiple sources
- Generates structured reports with citations
"""

from __future__ import annotations

from .base import AgentAction, AgentBase


class ResearcherWebAgent(AgentBase):
    """Deep web research agent with recursive link following.

    Capabilities:
    1. Execute targeted web searches
    2. Fetch and analyze page content
    3. Follow relevant links up to depth 2
    4. Cross-reference facts across sources
    5. Generate structured reports with citations
    """

    name = "RESEARCHER_WEB"
    model_key = "coder"
    prompt_file = "researcher_web"
    supported_actions = {
        AgentAction.SEARCH_WEB,
        AgentAction.FETCH_URL,
        AgentAction.ANALYZE_DATA,
        AgentAction.CONSULT_AGENT,
        AgentAction.GENERATE_REPORT,
        AgentAction.SEARCH_GITHUB,
        AgentAction.SEARCH_DOCS,
        AgentAction.DEEP_RESEARCH,
    }
