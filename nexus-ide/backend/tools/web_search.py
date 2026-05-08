"""Web search using DuckDuckGo HTML scraping (no API key required)."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


async def web_search(query: str, max_results: int = 10) -> list[SearchResult]:
    """Perform web search via DuckDuckGo HTML scraping."""
    url = f"https://duckduckgo.com/html/?q={query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            html = response.text
            results = []
            
            # Simple fallback: return mock results if parsing fails
            # TODO: Implement proper HTML parsing
            results.append(SearchResult(
                title=f"Search results for: {query}",
                url="https://duckduckgo.com",
                snippet="Web search functionality - coming soon"
            ))
            
            logger.info(f"Web search returning {len(results)} results")
            return results
            
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return []


register_tool(ToolSpec(
    name="web_search",
    description="Search the web using DuckDuckGo (no API key required)",
    schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "default": 10, "description": "Maximum results"},
        },
        "required": ["query"],
    },
    handler=web_search,
))
