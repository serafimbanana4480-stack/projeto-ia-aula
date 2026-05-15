"""Web search using DuckDuckGo HTML scraping (no API key required).

Parses the DuckDuckGo HTML results page to extract real search results
including titles, URLs, and snippets.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote_plus

import httpx

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    score: float = 0.0


@dataclass
class SearchResult:
    query: str
    sources: list[SearchHit]
    synthesis: str
    confidence: float = 0.0
    search_iterations: int = 1


def _parse_ddg_html(html: str) -> list[SearchHit]:
    """Parse DuckDuckGo HTML results page to extract search hits.

    DuckDuckGo HTML results are structured as:
    <div class="result results_links results_links_deep web-result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=...">Title</a>
      <a class="result__url" href="...">example.com</a>
      <a class="result__snippet">Snippet text...</a>
    </div>
    """
    results: list[SearchHit] = []

    # Split by result containers
    result_blocks = re.split(
        r'<div\s+class="[^"]*result[^"]*"', html
    )

    for block in result_blocks[1:]:  # Skip the first split (before any result)
        if len(results) >= 10:
            break

        # Extract title
        title_match = re.search(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>',
            block,
            re.DOTALL,
        )
        title = ""
        if title_match:
            title = _strip_tags(title_match.group(1)).strip()

        # Extract URL - DuckDuckGo uses redirect URLs
        url_match = re.search(
            r'href="//duckduckgo\.com/l/\?uddg=([^&"]+)',
            block,
        )
        url = ""
        if url_match:
            from urllib.parse import unquote
            url = unquote(url_match.group(1))
        else:
            # Try direct URL pattern
            url_match2 = re.search(
                r'<a[^>]*class="[^"]*result__url[^"]*"[^>]*href="([^"]+)"',
                block,
            )
            if url_match2:
                url = url_match2.group(1)
                if url.startswith("//"):
                    url = "https:" + url

        # Extract snippet
        snippet_match = re.search(
            r'<(?:a|td)[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td)>',
            block,
            re.DOTALL,
        )
        snippet = ""
        if snippet_match:
            snippet = _strip_tags(snippet_match.group(1)).strip()

        if title and (url or snippet):
            results.append(
                SearchHit(
                    title=unescape(title),
                    url=unescape(url) if url else "",
                    snippet=unescape(snippet) if snippet else "",
                )
            )

    return results


def _strip_tags(html: str) -> str:
    """Remove HTML tags and decode entities."""
    # Remove tags
    text = re.sub(r"<[^>]+>", "", html)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def web_search(query: str, max_results: int = 10) -> list[SearchHit]:
    """Perform web search via DuckDuckGo HTML scraping."""
    encoded_query = quote_plus(query)
    url = f"https://duckduckgo.com/html/?q={encoded_query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

            html = response.text
            results = _parse_ddg_html(html)

            if not results:
                logger.info(f"Web search: no results parsed for query '{query}'")
                # Return a single informative result instead of mock
                return [
                    SearchHit(
                        title=f"DuckDuckGo search: {query}",
                        url=f"https://duckduckgo.com/?q={encoded_query}",
                        snippet=f"Search completed for '{query}' but no structured results could be extracted. Try the direct link.",
                    )
                ]

            logger.info(f"Web search returning {len(results)} results for '{query}'")
            return results[:max_results]

    except httpx.HTTPStatusError as e:
        logger.error(f"Web search HTTP error: {e.response.status_code}")
        return []
    except httpx.TimeoutException:
        logger.error("Web search timed out")
        return []
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return []


async def fetch_url(url: str, max_chars: int = 10000) -> dict:
    """Fetch a URL and return its text content with HTML tags stripped.

    Useful for reading the content of a web page found via search.
    Respects max_chars to avoid returning huge payloads.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            html = response.text

            if "text/html" in content_type or html.strip().startswith("<"):
                text = _strip_tags(html)
            else:
                text = html

            text = re.sub(r"\s+", " ", text).strip()

            if len(text) > max_chars:
                text = text[:max_chars] + "\n... [truncated]"

            return {
                "url": url,
                "content": text,
                "content_length": len(text),
                "content_type": content_type,
            }

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} for {url}"}
    except httpx.TimeoutException:
        return {"error": f"Timeout fetching {url}"}
    except Exception as e:
        return {"error": f"Failed to fetch {url}: {e}"}


register_tool(
    ToolSpec(
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
    )
)

register_tool(
    ToolSpec(
        name="fetch_url",
        description="Fetch a URL and return its text content with HTML stripped. Use after web_search to read a specific result page.",
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_chars": {"type": "integer", "default": 10000, "description": "Maximum characters to return"},
            },
            "required": ["url"],
        },
        handler=fetch_url,
    )
)
