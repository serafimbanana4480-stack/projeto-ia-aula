"""Web search with multi-provider support, caching, retry logic, and content extraction.

Providers (in priority order):
1. Brave Search API -- independent index, ultra-low latency, $5/1k queries,
   free $5 credit/month.  Best for production agent loops.
2. DuckDuckGo HTML -- no API key, free, but fragile to HTML changes.

Content extraction:
- Jina AI Reader (r.jina.ai) -- free tier, no key needed for basic use,
  returns clean Markdown ideal for LLM context windows.
- BeautifulSoup / httpx fallback when Jina fails or for private pages.

New tools exposed to agents:
- web_search          -- enhanced search with ranking & site filtering
- fetch_url           -- upgraded fetch with Jina / BS4 extraction
- fetch_and_summarize -- fetch a URL and return structured summary
- search_and_answer   -- search + fetch top-3 + synthesize snippets
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from backend.cache import cache_result
from backend.config.settings import get_settings
from backend.tools.registry import ToolSpec, register_tool
from backend.tools.web_fetcher import fetch_and_summarize

logger = logging.getLogger(__name__)

SEARCH_CACHE_TTL = 3600  # 1 hour
FETCH_CACHE_TTL = 1800  # 30 minutes

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    score: float = 0.0
    source_engine: str = ""
    age_hint: str = ""  # e.g. "2 days ago" when available


@dataclass
class SearchResult:
    query: str
    sources: list[SearchHit]
    confidence: float = 0.0
    search_iterations: int = 1


@dataclass
class FetchedContent:
    url: str
    title: str = ""
    content: str = ""
    summary: str = ""
    content_length: int = 0
    content_type: str = ""
    extraction_method: str = ""


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Make an HTTP request with exponential backoff retry logic."""
    max_retries = 3
    base_delay = 1.0
    last_exception: Exception | None = None

    for attempt in range(max_retries):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            # Retry on rate-limit or transient server errors
            if e.response.status_code in (429, 500, 502, 503, 504):
                last_exception = e
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)
            else:
                raise
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            last_exception = e
            delay = base_delay * (2**attempt)
            logger.warning(
                "Request failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                max_retries,
                delay,
                e,
            )
            await asyncio.sleep(delay)

    raise last_exception or RuntimeError("All retry attempts failed")


# ---------------------------------------------------------------------------
# Scoring / ranking helpers
# ---------------------------------------------------------------------------

# Domains that usually carry higher authority for technical questions
_AUTHORITY_DOMAINS = {
    "github.com",
    "stackoverflow.com",
    "docs.python.org",
    "developer.mozilla.org",
    "readthedocs.io",
    "medium.com",
    "dev.to",
    "arxiv.org",
    "ieee.org",
    "wikipedia.org",
    "apache.org",
    "npmjs.com",
    "pypi.org",
    "docs.rs",
    "kotlinlang.org",
    "go.dev",
    "rust-lang.org",
    "learn.microsoft.com",
    "cloud.google.com",
    "aws.amazon.com",
    "docs.docker.com",
}


def _domain_score(url: str) -> float:
    """Return a domain authority bonus between 0.0 and 1.0."""
    try:
        netloc = urlparse(url).netloc.lower()
        # Strip www.
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if any(netloc.endswith(d) or netloc == d for d in _AUTHORITY_DOMAINS):
            return 0.25
    except Exception:
        pass
    return 0.0


def _relevance_score(query: str, hit: SearchHit) -> float:
    """Compute a composite relevance score for a search hit."""
    q_words = set(re.findall(r"\b\w{3,}\b", query.lower()))
    if not q_words:
        return 0.0

    text = f"{hit.title} {hit.snippet}".lower()
    matches = sum(1 for w in q_words if w in text)
    coverage = matches / len(q_words)

    # Exact phrase bonus
    phrase_bonus = 0.15 if query.lower() in text else 0.0

    # Domain authority bonus
    authority = _domain_score(hit.url)

    # Snippet length bonus (slight preference for richer snippets)
    length_bonus = min(len(hit.snippet) / 500, 0.1)

    score = coverage * 0.6 + phrase_bonus + authority + length_bonus
    return round(min(score, 1.0), 4)


def _rank_hits(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    """Re-rank hits using local composite scoring."""
    for h in hits:
        h.score = _relevance_score(query, h)
    hits.sort(key=lambda x: x.score, reverse=True)
    return hits


# ---------------------------------------------------------------------------
# Site-specific query parsing
# ---------------------------------------------------------------------------


def _extract_site_filter(query: str) -> tuple[str, str | None]:
    """Parse ``site:example.com`` from query.

    Returns ``(clean_query, site_filter)``.
    """
    pattern = r"site:([a-zA-Z0-9._\-]+)"
    match = re.search(pattern, query)
    if match:
        site = match.group(1)
        clean = re.sub(pattern, "", query).strip()
        return clean, site
    return query, None


# ---------------------------------------------------------------------------
# Brave Search
# ---------------------------------------------------------------------------


async def _search_brave(
    query: str,
    max_results: int = 10,
    site_filter: str | None = None,
) -> list[SearchHit]:
    """Search via Brave Search API."""
    settings = get_settings()
    api_key = settings.brave_api_key
    if not api_key:
        return []

    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    params: dict[str, Any] = {
        "q": query,
        "count": min(max_results, 20),
        "offset": 0,
        "safesearch": "off",
    }
    if site_filter:
        params["q"] = f"{query} site:{site_filter}"

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        try:
            response = await _request_with_retry(client, "GET", url, headers=headers, params=params)
            data = response.json()
            hits: list[SearchHit] = []
            for item in data.get("web", {}).get("results", []):
                hits.append(
                    SearchHit(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("description", ""),
                        source_engine="brave",
                        age_hint=item.get("age", ""),
                    )
                )
                if len(hits) >= max_results:
                    break
            return hits
        except httpx.HTTPStatusError as exc:
            logger.error("Brave search HTTP error: %s", exc.response.status_code)
            return []
        except Exception as exc:
            logger.error("Brave search failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# DuckDuckGo fallback
# ---------------------------------------------------------------------------


async def _search_duckduckgo(
    query: str,
    max_results: int = 10,
    site_filter: str | None = None,
) -> list[SearchHit]:
    """Search via DuckDuckGo HTML interface."""
    q = query
    if site_filter:
        q = f"{query} site:{site_filter}"

    url = "https://html.duckduckgo.com/html/"
    data = {"q": q, "s": "0", "dc": "1"}
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        try:
            response = await _request_with_retry(client, "POST", url, data=data, headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")
            hits: list[SearchHit] = []
            for result in soup.select(".result"):
                a_tag = result.select_one(".result__a")
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                href = a_tag.get("href", "")
                # DuckDuckGo redirects via their own URL
                if href.startswith("/"):
                    href = f"https://duckduckgo.com{href}"
                elif href.startswith("http://duckduckgo.com/l/"):
                    # Extract real URL from redirect
                    match = re.search(r"uddg=([^&]+)", href)
                    if match:
                        href = unquote(match.group(1))

                snippet_tag = result.select_one(".result__snippet")
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                hits.append(
                    SearchHit(
                        title=title,
                        url=href,
                        snippet=snippet,
                        source_engine="duckduckgo",
                    )
                )
                if len(hits) >= max_results:
                    break
            return hits
        except Exception as exc:
            logger.error("DuckDuckGo search failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Public search API
# ---------------------------------------------------------------------------


@cache_result("web_search:", ttl=SEARCH_CACHE_TTL)
async def search_web(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search the web using Brave (primary) or DuckDuckGo (fallback).

    Supports ``site:example.com`` filtering inside *query*.
    Results are ranked by a composite relevance score.
    """
    clean_query, site = _extract_site_filter(query)
    hits = await _search_brave(clean_query, max_results=max_results, site_filter=site)
    if not hits:
        hits = await _search_duckduckgo(clean_query, max_results=max_results, site_filter=site)
    hits = _rank_hits(clean_query, hits)
    return {
        "query": query,
        "hits": [
            {
                "title": h.title,
                "url": h.url,
                "snippet": h.snippet,
                "score": h.score,
                "source_engine": h.source_engine,
                "age_hint": h.age_hint,
            }
            for h in hits
        ],
        "count": len(hits),
    }


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


async def fetch_url(url: str) -> dict[str, Any]:
    """Fetch and summarize the content of a URL.

    Thin wrapper around :func:`backend.tools.web_fetcher.fetch_and_summarize`.
    """
    return await fetch_and_summarize(url)


# ---------------------------------------------------------------------------
# Search + fetch + synthesize
# ---------------------------------------------------------------------------


@cache_result("search_answer:", ttl=SEARCH_CACHE_TTL)
async def search_and_answer(query: str, max_results: int = 3) -> dict[str, Any]:
    """Search the web, fetch top results, and synthesize a coherent answer.

    Args:
        query: Search query. Supports ``site:`` filtering.
        max_results: Number of top results to fetch and include.

    Returns:
        dict with ``query``, ``sources``, ``answer``, ``confidence``.
    """
    clean_query, site = _extract_site_filter(query)

    # 1. Search
    hits = await _search_brave(clean_query, max_results=max_results * 2, site_filter=site)
    if not hits:
        hits = await _search_duckduckgo(clean_query, max_results=max_results * 2, site_filter=site)

    if not hits:
        return {
            "query": query,
            "sources": [],
            "answer": "No search results found.",
            "confidence": 0.0,
        }

    hits = _rank_hits(clean_query, hits)[:max_results]

    # 2. Fetch content concurrently
    fetch_tasks = [fetch_and_summarize(h.url) for h in hits]
    fetched_list = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    fetched: list[dict[str, Any]] = []
    for hit, content in zip(hits, fetched_list, strict=False):
        if isinstance(content, Exception):
            logger.warning("Fetch failed for %s: %s", hit.url, content)
            continue
        if content.get("status") == "error":
            continue
        fetched.append(
            {
                "url": hit.url,
                "title": content.get("title") or hit.title,
                "summary": content.get("summary", hit.snippet),
                "snippet": hit.snippet,
            }
        )

    # 3. Synthesize answer
    synthesis_parts = [f"## Answer for: {query}\n"]
    for i, item in enumerate(fetched, 1):
        synthesis_parts.append(f"\n### Source {i}: [{item['title']}]({item['url']})\n")
        # Include both snippet and first part of summary
        synthesis_parts.append(item["snippet"])
        if item["summary"] and item["summary"] != item["snippet"]:
            synthesis_parts.append(f"\n{item['summary'][:800]}")

    answer = "\n".join(synthesis_parts)
    confidence = round(sum(h.score for h in hits) / len(hits), 2) if hits else 0.0

    return {
        "query": query,
        "sources": [
            {
                "url": h.url,
                "title": h.title,
                "snippet": h.snippet,
                "score": h.score,
            }
            for h in hits
        ],
        "answer": answer,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

register_tool(
    ToolSpec(
        name="web_search",
        description=(
            "Search the web using Brave or DuckDuckGo with ranking, "
            "site filtering, and 1-hour caching."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (supports site: filtering)",
                },
                "max_results": {
                    "type": "integer",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        handler=search_web,
    )
)

register_tool(
    ToolSpec(
        name="fetch_url",
        description=(
            "Fetch and summarize the content of a URL using Jina AI "
            "or direct extraction with caching."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch",
                },
            },
            "required": ["url"],
        },
        handler=fetch_url,
    )
)

register_tool(
    ToolSpec(
        name="search_and_answer",
        description=("Search the web and synthesize a coherent answer from top results."),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "max_results": {
                    "type": "integer",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
        handler=search_and_answer,
    )
)
