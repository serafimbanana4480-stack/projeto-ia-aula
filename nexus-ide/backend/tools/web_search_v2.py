"""Vastly improved web search system with multi-provider support, deep research,
GitHub search, documentation search, and intelligent caching.

New capabilities over web_search.py v1:
- Jina AI Reader API as primary content extractor
- DuckDuckGo fallback with robust HTML parsing
- Result ranking by relevance + recency
- Redis caching (1 hour TTL)
- Exponential backoff retry
- GitHub repository search
- Cached documentation indices for popular frameworks
- Cross-referenced fact synthesis
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from typing import Any
from urllib.parse import quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from backend.cache import cache_result
from backend.config.settings import get_settings
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

SEARCH_CACHE_TTL = 3600  # 1 hour
FETCH_CACHE_TTL = 1800  # 30 minutes
MAX_RETRIES = 3
BASE_DELAY = 1.0
FETCH_TIMEOUT = 15.0

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
    age_hint: str = ""
    published_date: str = ""


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
    published_date: str = ""
    content_length: int = 0
    content_type: str = ""
    extraction_method: str = ""
    links: list[str] = field(default_factory=list)


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
    last_exception: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504):
                last_exception = e
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)
            else:
                raise
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            last_exception = e
            delay = BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Request failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                MAX_RETRIES,
                delay,
                e,
            )
            await asyncio.sleep(delay)
    raise last_exception or RuntimeError("All retry attempts failed")


# ---------------------------------------------------------------------------
# Scoring / ranking helpers
# ---------------------------------------------------------------------------

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

_RECENCY_WEIGHT = 0.15
_RELEVANCE_WEIGHT = 0.85


def _domain_score(url: str) -> float:
    """Return a domain authority bonus between 0.0 and 1.0."""
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if any(netloc.endswith(d) or netloc == d for d in _AUTHORITY_DOMAINS):
            return 0.25
    except Exception:
        pass
    return 0.0


def _parse_age_hint(age_hint: str) -> float:
    """Convert age hint string to recency score (higher = newer)."""
    if not age_hint:
        return 0.5  # neutral
    age_lower = age_hint.lower()
    # Very recent
    if any(x in age_lower for x in ("just now", "minute ago", "minutes ago", "hour ago", "hours ago", "today")):
        return 1.0
    # Recent
    if any(x in age_lower for x in ("day ago", "days ago", "yesterday")):
        return 0.85
    # Moderately recent
    if any(x in age_lower for x in ("week ago", "weeks ago")):
        return 0.7
    # Older
    if any(x in age_lower for x in ("month ago", "months ago")):
        return 0.5
    # Very old
    if any(x in age_lower for x in ("year ago", "years ago")):
        return 0.2
    return 0.5


def _relevance_score(query: str, hit: SearchHit) -> float:
    """Compute a composite relevance score for a search hit."""
    q_words = set(re.findall(r"\b\w{3,}\b", query.lower()))
    if not q_words:
        return 0.0

    text = f"{hit.title} {hit.snippet}".lower()
    matches = sum(1 for w in q_words if w in text)
    coverage = matches / len(q_words)

    phrase_bonus = 0.15 if query.lower() in text else 0.0
    authority = _domain_score(hit.url)
    length_bonus = min(len(hit.snippet) / 500, 0.1)

    score = coverage * 0.6 + phrase_bonus + authority + length_bonus
    return round(min(score, 1.0), 4)


def _rank_hits(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    """Re-rank hits using local composite scoring (relevance + recency)."""
    for h in hits:
        relevance = _relevance_score(query, h)
        recency = _parse_age_hint(h.age_hint)
        h.score = round(_RELEVANCE_WEIGHT * relevance + _RECENCY_WEIGHT * recency, 4)
    hits.sort(key=lambda x: x.score, reverse=True)
    return hits


# ---------------------------------------------------------------------------
# Site filter / recency helpers
# ---------------------------------------------------------------------------


def _extract_site_filter(query: str) -> tuple[str, str | None]:
    """Parse ``site:example.com`` from query. Returns (clean_query, site_filter)."""
    pattern = r"site:([a-zA-Z0-9._\-]+)"
    match = re.search(pattern, query)
    if match:
        site = match.group(1)
        clean = re.sub(pattern, "", query).strip()
        return clean, site
    return query, None


def _apply_recency_filter(query: str, recency_days: int | None) -> str:
    """Append time-based keywords to query for DuckDuckGo."""
    if not recency_days:
        return query
    if recency_days <= 1:
        return f"{query} today"
    if recency_days <= 7:
        return f"{query} this week"
    if recency_days <= 30:
        return f"{query} this month"
    if recency_days <= 365:
        return f"{query} this year"
    return query


# ---------------------------------------------------------------------------
# Brave Search
# ---------------------------------------------------------------------------


async def _search_brave(
    query: str,
    max_results: int = 10,
    site_filter: str | None = None,
    recency_days: int | None = None,
) -> list[SearchHit]:
    """Search via Brave Search API."""
    settings = get_settings()
    api_key = getattr(settings, "brave_api_key", None)
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
    if recency_days and recency_days <= 30:
        params["freshness"] = "pw"  # past week
    elif recency_days and recency_days <= 365:
        params["freshness"] = "py"  # past year

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
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
# DuckDuckGo fallback (improved parsing)
# ---------------------------------------------------------------------------


async def _search_duckduckgo(
    query: str,
    max_results: int = 10,
    site_filter: str | None = None,
    recency_days: int | None = None,
) -> list[SearchHit]:
    """Search via DuckDuckGo HTML interface with robust parsing."""
    q = _apply_recency_filter(query, recency_days)
    if site_filter:
        q = f"{q} site:{site_filter}"

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

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await _request_with_retry(client, "POST", url, data=data, headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")
            hits: list[SearchHit] = []

            # Try multiple result selectors for resilience
            result_selectors = [
                ".result",
                ".web-result",
                ".result__body",
            ]
            results = []
            for selector in result_selectors:
                results = soup.select(selector)
                if results:
                    break

            for result in results:
                a_tag = result.select_one(".result__a") or result.select_one("a.result__a")
                if not a_tag:
                    # Fallback: any link inside result
                    a_tag = result.find("a")
                if not a_tag:
                    continue

                title = a_tag.get_text(strip=True)
                href = a_tag.get("href", "")

                # Decode DuckDuckGo redirect URLs
                if href.startswith("/"):
                    href = f"https://duckduckgo.com{href}"
                elif href.startswith("http://duckduckgo.com/l/") or "uddg=" in href:
                    match = re.search(r"uddg=([^&]+)", href)
                    if match:
                        href = unquote(match.group(1))

                snippet_tag = result.select_one(".result__snippet") or result.select_one(".result__snippet")
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                # Try to extract age hint
                age_hint = ""
                age_tag = result.select_one(".result__timestamp") or result.select_one(".result__date")
                if age_tag:
                    age_hint = age_tag.get_text(strip=True)

                hits.append(
                    SearchHit(
                        title=title,
                        url=href,
                        snippet=snippet,
                        source_engine="duckduckgo",
                        age_hint=age_hint,
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


@cache_result("web_search_v2:", ttl=SEARCH_CACHE_TTL)
async def search_web(
    query: str,
    max_results: int = 10,
    site: str | None = None,
    recency_days: int | None = None,
) -> dict[str, Any]:
    """Search the web using Brave (primary) or DuckDuckGo (fallback).

    Args:
        query: Search query. Supports ``site:example.com`` filtering.
        max_results: Maximum number of results to return.
        site: Optional site filter (e.g., "github.com").
        recency_days: Optional recency filter in days.

    Returns:
        dict with ``query``, ``hits``, ``count``.
    """
    clean_query, site_from_query = _extract_site_filter(query)
    site_filter = site or site_from_query

    hits = await _search_brave(clean_query, max_results=max_results, site_filter=site_filter, recency_days=recency_days)
    if not hits:
        hits = await _search_duckduckgo(clean_query, max_results=max_results, site_filter=site_filter, recency_days=recency_days)

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


def _extract_publish_date(soup: BeautifulSoup) -> str:
    """Extract publish date from HTML meta tags."""
    selectors = [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "pubdate"}),
        ("meta", {"name": "publish-date"}),
        ("meta", {"name": "date"}),
        ("meta", {"property": "og:published_time"}),
    ]
    for tag_name, attrs in selectors:
        tag = soup.find(tag_name, attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"]

    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        return time_tag["datetime"]

    return ""


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Extract unique links from BeautifulSoup object."""
    from urllib.parse import urljoin

    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme in ("http", "https") and full not in seen:
            seen.add(full)
            links.append(full)
    return links[:50]


def _extract_text_bs4(html: str, base_url: str) -> tuple[str, str, list[str], str]:
    """Extract title, main text, links, and publish date from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"]

    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"content|main|article", re.I))
    )
    if main:
        text = main.get_text(separator="\n", strip=True)
    else:
        text = soup.get_text(separator="\n", strip=True)

    text = re.sub(r"\n{3,}", "\n\n", text)
    links = _extract_links(soup, base_url)
    published_date = _extract_publish_date(soup)

    return title, text, links, published_date


async def _fetch_via_jina(url: str, max_length: int = 500) -> FetchedContent | None:
    """Try fetching via Jina AI Reader API."""
    jina_url = f"https://r.jina.ai/{url}"
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            response = await _request_with_retry(client, "GET", jina_url)
            text = response.text
            lines = text.splitlines()
            title = ""
            content_lines: list[str] = []
            links: list[str] = []
            published_date = ""

            for line in lines:
                line = line.strip()
                if line.startswith("Title:"):
                    title = line.replace("Title:", "").strip()
                elif line.startswith("URL:"):
                    pass
                elif line.startswith("Date:"):
                    published_date = line.replace("Date:", "").strip()
                elif line:
                    content_lines.append(line)
                    for match in re.finditer(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line):
                        links.append(match.group(2))

            content = "\n".join(content_lines)
            summary = content[:max_length] if content else ""
            return FetchedContent(
                url=url,
                title=title,
                content=content,
                summary=summary,
                published_date=published_date,
                content_length=len(content),
                extraction_method="jina_ai",
                links=links,
            )
    except Exception as exc:
        logger.debug("Jina fetch failed for %s: %s", url, exc)
        return None


async def _fetch_via_httpx(url: str, max_length: int = 500) -> FetchedContent | None:
    """Fallback fetch via httpx + BeautifulSoup."""
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            response = await _request_with_retry(
                client,
                "GET",
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                },
            )
            html = response.text
            title, text, links, published_date = _extract_text_bs4(html, url)
            content = text[:8000] if text else ""
            summary = content[:max_length] if content else ""
            return FetchedContent(
                url=url,
                title=title,
                content=content,
                summary=summary,
                published_date=published_date,
                content_length=len(content),
                extraction_method="httpx_bs4",
                links=links,
            )
    except Exception as exc:
        logger.error("HTTPX fetch failed for %s: %s", url, exc)
        return None


@cache_result("fetch_content_v2:", ttl=FETCH_CACHE_TTL)
async def fetch_and_summarize(url: str, max_length: int = 500) -> dict[str, Any]:
    """Fetch a URL and return a structured summary with title, content, and publish date.

    Args:
        url: The URL to fetch.
        max_length: Maximum length of the summary.

    Returns:
        dict with ``url``, ``title``, ``summary``, ``content``, ``published_date``,
        ``content_length``, ``extraction_method``, ``links``, ``status``.
    """
    # Try Jina AI first
    result = await _fetch_via_jina(url, max_length=max_length)
    if result is None:
        result = await _fetch_via_httpx(url, max_length=max_length)

    if result is None:
        return {
            "url": url,
            "title": "",
            "summary": f"Error fetching URL: unable to retrieve content",
            "content": "",
            "published_date": "",
            "content_length": 0,
            "extraction_method": "failed",
            "links": [],
            "status": "error",
        }

    return {
        "url": result.url,
        "title": result.title,
        "summary": result.summary,
        "content": result.content,
        "published_date": result.published_date,
        "content_length": result.content_length,
        "extraction_method": result.extraction_method,
        "links": result.links,
        "status": "success",
    }


# ---------------------------------------------------------------------------
# Search + fetch + synthesize (deep research)
# ---------------------------------------------------------------------------


def _cross_reference_facts(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-reference facts across multiple sources and score consensus."""
    if not summaries:
        return {"consensus_score": 0.0, "common_phrases": [], "conflicts": []}

    # Simple heuristic: find common significant phrases (4+ words)
    all_phrases: list[set[str]] = []
    for s in summaries:
        text = f"{s.get('title', '')} {s.get('summary', '')}"
        words = re.findall(r"\b\w+\b", text.lower())
        phrases = set()
        for i in range(len(words) - 3):
            phrase = " ".join(words[i : i + 4])
            phrases.add(phrase)
        all_phrases.append(phrases)

    if len(all_phrases) < 2:
        return {"consensus_score": 0.5, "common_phrases": [], "conflicts": []}

    common = all_phrases[0].intersection(*all_phrases[1:])
    common_sorted = sorted(common, key=lambda p: len(p), reverse=True)[:10]

    consensus_score = min(len(common) / 10, 1.0) if common else 0.0
    return {
        "consensus_score": round(consensus_score, 2),
        "common_phrases": common_sorted,
        "conflicts": [],
    }


@cache_result("deep_research:", ttl=SEARCH_CACHE_TTL)
async def search_and_answer(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the web, fetch top results, and synthesize a coherent answer.

    Args:
        query: Search query.
        max_results: Number of top results to fetch and include.

    Returns:
        dict with ``query``, ``sources``, ``answer``, ``confidence``, ``consensus``.
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
            "consensus": {},
        }

    hits = _rank_hits(clean_query, hits)[:max_results]

    # 2. Fetch content concurrently
    fetch_tasks = [fetch_and_summarize(h.url, max_length=800) for h in hits]
    fetched_list = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    fetched: list[dict[str, Any]] = []
    for hit, content in zip(hits, fetched_list):
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
                "published_date": content.get("published_date", ""),
                "extraction_method": content.get("extraction_method", ""),
            }
        )

    # 3. Cross-reference facts
    consensus = _cross_reference_facts(fetched)

    # 4. Synthesize answer
    synthesis_parts = [f"# Research: {query}\n"]
    synthesis_parts.append(f"\n*Confidence: {consensus['consensus_score']:.0%} consensus across sources*\n")

    synthesis_parts.append("\n## Sources\n")
    for i, item in enumerate(fetched, 1):
        date_str = f" ({item['published_date']})" if item.get("published_date") else ""
        synthesis_parts.append(
            f"{i}. [{item['title']}]({item['url']}){date_str}\n"
        )

    synthesis_parts.append("\n## Key Findings\n")
    for i, item in enumerate(fetched, 1):
        synthesis_parts.append(f"\n### Source {i}: {item['title']}\n")
        synthesis_parts.append(item["snippet"])
        if item["summary"] and item["summary"] != item["snippet"]:
            synthesis_parts.append(f"\n{item['summary'][:800]}")

    if consensus["common_phrases"]:
        synthesis_parts.append("\n## Consensus Points\n")
        for phrase in consensus["common_phrases"][:5]:
            synthesis_parts.append(f"- {phrase}")

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
        "consensus": consensus,
    }


# ---------------------------------------------------------------------------
# GitHub search
# ---------------------------------------------------------------------------


@cache_result("search_github:", ttl=SEARCH_CACHE_TTL)
async def search_github(
    query: str,
    language: str | None = None,
    stars_min: int = 100,
) -> dict[str, Any]:
    """Search GitHub repositories using the GitHub Search API.

    Args:
        query: Search query for repositories.
        language: Optional programming language filter.
        stars_min: Minimum star count (default 100).

    Returns:
        dict with ``query``, ``repositories``, ``count``.
    """
    q = f"{query} stars:>={stars_min}"
    if language:
        q += f" language:{language}"

    url = f"https://api.github.com/search/repositories?q={quote_plus(q)}&sort=stars&order=desc&per_page=10"
    headers = {"Accept": "application/vnd.github.v3+json"}

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await _request_with_retry(client, "GET", url, headers=headers)
            data = response.json()
            repos: list[dict[str, Any]] = []
            for item in data.get("items", []):
                repos.append(
                    {
                        "name": item.get("full_name", ""),
                        "url": item.get("html_url", ""),
                        "description": item.get("description", ""),
                        "stars": item.get("stargazers_count", 0),
                        "language": item.get("language", ""),
                        "updated_at": item.get("updated_at", ""),
                    }
                )
            return {
                "query": query,
                "repositories": repos,
                "count": len(repos),
                "total_count": data.get("total_count", 0),
            }
        except Exception as exc:
            logger.error("GitHub search failed: %s", exc)
            return {
                "query": query,
                "repositories": [],
                "count": 0,
                "total_count": 0,
                "error": str(exc),
            }


# ---------------------------------------------------------------------------
# Documentation search
# ---------------------------------------------------------------------------

_DOC_INDICES: dict[str, str] = {
    "python": "docs.python.org",
    "django": "docs.djangoproject.com",
    "fastapi": "fastapi.tiangolo.com",
    "flask": "flask.palletsprojects.com",
    "sqlalchemy": "docs.sqlalchemy.org",
    "react": "react.dev",
    "vue": "vuejs.org",
    "angular": "angular.io",
    "nextjs": "nextjs.org",
    "svelte": "svelte.dev",
    "nodejs": "nodejs.org",
    "typescript": "typescriptlang.org",
    "rust": "doc.rust-lang.org",
    "go": "pkg.go.dev",
    "kotlin": "kotlinlang.org",
    "swift": "swift.org",
    "docker": "docs.docker.com",
    "kubernetes": "kubernetes.io",
    "terraform": "developer.hashicorp.com",
    "aws": "docs.aws.amazon.com",
    "gcp": "cloud.google.com",
    "azure": "learn.microsoft.com",
    "postgres": "postgresql.org",
    "mysql": "dev.mysql.com",
    "mongodb": "mongodb.com",
    "redis": "redis.io",
    "elasticsearch": "elastic.co",
    "tensorflow": "tensorflow.org",
    "pytorch": "pytorch.org",
    "numpy": "numpy.org",
    "pandas": "pandas.pydata.org",
    "scikit": "scikit-learn.org",
    "matplotlib": "matplotlib.org",
    "openai": "platform.openai.com",
    "langchain": "python.langchain.com",
    "pytest": "docs.pytest.org",
    "celery": "docs.celeryq.dev",
    "nginx": "nginx.org",
}


@cache_result("search_docs:", ttl=SEARCH_CACHE_TTL)
async def search_docs(query: str, framework: str) -> dict[str, Any]:
    """Search official documentation for a popular framework.

    Args:
        query: Search query.
        framework: Framework name (e.g., "python", "react", "docker").

    Returns:
        dict with ``query``, ``framework``, ``hits``, ``count``.
    """
    framework_lower = framework.lower()
    domain = _DOC_INDICES.get(framework_lower)

    if not domain:
        # Fallback: try to find docs via general web search
        fallback_query = f"{framework} official documentation {query}"
        web_result = await search_web(fallback_query, max_results=5)
        return {
            "query": query,
            "framework": framework,
            "hits": web_result.get("hits", []),
            "count": web_result.get("count", 0),
            "note": f"No cached doc index for '{framework}'. Used general web search.",
        }

    doc_query = f"{query} site:{domain}"
    web_result = await search_web(doc_query, max_results=8)
    hits = web_result.get("hits", [])

    # Boost results that are actually from the expected domain
    for h in hits:
        parsed = urlparse(h["url"])
        if domain in parsed.netloc:
            h["score"] = min(h.get("score", 0) + 0.15, 1.0)
            h["source_engine"] = f"docs:{framework}"

    hits.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {
        "query": query,
        "framework": framework,
        "hits": hits,
        "count": len(hits),
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

register_tool(
    ToolSpec(
        name="search_web_v2",
        description=(
            "Enhanced web search with Brave/DuckDuckGo fallback, "
            "relevance + recency ranking, site filtering, and 1-hour caching."
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
                "site": {
                    "type": "string",
                    "description": "Optional site filter (e.g. github.com)",
                },
                "recency_days": {
                    "type": "integer",
                    "description": "Optional recency filter in days",
                },
            },
            "required": ["query"],
        },
        handler=search_web,
    )
)

register_tool(
    ToolSpec(
        name="fetch_content_v2",
        description=(
            "Fetch a URL and return a structured summary with title, "
            "main content, publish date, and extracted links. Uses Jina AI "
            "Reader first, then falls back to direct extraction."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch",
                },
                "max_length": {
                    "type": "integer",
                    "default": 500,
                    "description": "Maximum summary length",
                },
            },
            "required": ["url"],
        },
        handler=fetch_and_summarize,
    )
)

register_tool(
    ToolSpec(
        name="deep_research",
        description=(
            "One-shot deep research: search the web, fetch top results, "
            "cross-reference facts, and synthesize a coherent answer with sources."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research query",
                },
                "max_results": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of top results to analyze",
                },
            },
            "required": ["query"],
        },
        handler=search_and_answer,
    )
)

register_tool(
    ToolSpec(
        name="search_github",
        description=(
            "Search GitHub repositories by query, language, and minimum stars."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for repositories",
                },
                "language": {
                    "type": "string",
                    "description": "Programming language filter",
                },
                "stars_min": {
                    "type": "integer",
                    "default": 100,
                    "description": "Minimum star count",
                },
            },
            "required": ["query"],
        },
        handler=search_github,
    )
)

register_tool(
    ToolSpec(
        name="search_docs",
        description=(
            "Search official documentation for popular frameworks "
            "(python, react, docker, rust, go, etc.)."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "framework": {
                    "type": "string",
                    "description": "Framework name (e.g. python, react, docker)",
                },
            },
            "required": ["query", "framework"],
        },
        handler=search_docs,
    )
)
