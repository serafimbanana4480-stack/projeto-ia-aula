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
- Lexical overlap reporting across the pages that were actually fetched
  (no claim extraction, no corroboration claim, no conflict detection)
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import ipaddress
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape as _html_unescape
from typing import Any, cast
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote_plus,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

import httpx
from bs4 import BeautifulSoup

from backend.cache import cache_result
from backend.tools.registry import ToolSpec, register_tool
from backend.tools.safe_http import (
    PublicAddressHTTPTransport,
    normalize_public_http_url,
    remote_reader_enabled,
)
from backend.tools.search_errors import SearchProviderError, SearchProvidersUnavailable

logger = logging.getLogger(__name__)

SEARCH_CACHE_TTL = 3600  # 1 hour
FETCH_CACHE_TTL = 1800  # 30 minutes
MAX_RETRIES = 3
BASE_DELAY = 1.0
FETCH_TIMEOUT = 15.0


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


#: Provider search ceiling. Each provider retries up to three times with
#: backoff; without this the search phase alone could take ~48 s before the
#: first fetch started.
SEARCH_DEADLINE = _env_float("NEXUS_RESEARCH_SEARCH_SECONDS", 15.0)
#: Whole-call ceiling for ``deep_research``. The time spent searching is
#: subtracted from the fetch budget so the total stays near this value.
RESEARCH_DEADLINE = _env_float("NEXUS_RESEARCH_DEADLINE_SECONDS", 45.0)
#: Top-N pages fetched in parallel. Bounded so a wide search cannot open dozens
#: of sockets or hammer one origin.
MAX_CONCURRENT_FETCHES = _env_int("NEXUS_RESEARCH_MAX_CONCURRENT_FETCHES", 5)
FETCH_PAGE_DEADLINE = _env_float("NEXUS_RESEARCH_FETCH_SECONDS", 12.0)
#: Compact brief budget. Kept well under the agent's 6000-char tool-result
#: budget so the brief survives serialisation instead of being cut in half.
BRIEF_MAX_CHARS = _env_int("NEXUS_RESEARCH_BRIEF_CHARS", 3200)
MAX_IMAGES = 12
MAX_LINKS = 20

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
    images: list[dict[str, Any]] = field(default_factory=list)


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
                delay = BASE_DELAY * (2**attempt)
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
            delay = BASE_DELAY * (2**attempt)
            logger.warning(
                "Request failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                MAX_RETRIES,
                delay,
                e,
            )
            await asyncio.sleep(delay)
    raise last_exception or RuntimeError("All retry attempts failed")


#: One client per (redirect policy, event loop). A deep-research call fetches
#: 3-5 pages; building a fresh ``AsyncClient`` for each one discarded HTTP
#: connection/TLS reuse, so the whole fan-out paid the handshake cost twice.
#: Loop-keyed because tests (and some callers) run each coroutine batch under
#: ``asyncio.run`` and a client cannot cross event loops.
_shared_clients: dict[str, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}


def _get_http_client(*, follow_redirects: bool) -> httpx.AsyncClient:
    """Return the shared guarded client for the current event loop."""
    key = "redirect" if follow_redirects else "strict"
    loop = asyncio.get_running_loop()
    entry = _shared_clients.get(key)
    if entry is not None and entry[0] is loop and not entry[1].is_closed:
        return entry[1]
    client = httpx.AsyncClient(
        timeout=FETCH_TIMEOUT,
        follow_redirects=follow_redirects,
        trust_env=False,
        transport=PublicAddressHTTPTransport(),
    )
    _shared_clients[key] = (loop, client)
    return client


async def close_shared_http_clients() -> None:
    """Close shared clients (lifespan/shutdown hook and tests)."""
    for _loop, client in list(_shared_clients.values()):
        if not client.is_closed:
            # A loop that already closed makes aclose() itself fail; there is
            # nothing left to release in that case.
            with contextlib.suppress(Exception):
                await client.aclose()
    _shared_clients.clear()


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
    if any(
        x in age_lower
        for x in ("just now", "minute ago", "minutes ago", "hour ago", "hours ago", "today")
    ):
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
# Display URL safety / dedupe
# ---------------------------------------------------------------------------

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = frozenset(
    {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref_src", "ref_url", "si"}
)


def _display_url(value: Any) -> str:
    """Return a display-safe absolute HTTP(S) URL, or ``""``.

    Search and page content are untrusted: ``javascript:``, ``data:``,
    credential-bearing and malformed URLs must never reach the model or the
    UI. This is deliberately looser than ``normalize_public_http_url`` because
    a display URL is not fetched here (``.test``/``.example`` links stay
    visible), but the scheme/host/credential checks are the same.
    """
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate or any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        return ""
    try:
        parsed = urlparse(candidate)
        _ = parsed.port
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    hostname = parsed.hostname.rstrip(".").lower()
    if (
        not hostname
        or "%" in hostname
        or hostname == "localhost"
        or hostname.endswith((".local", ".internal"))
    ):
        return ""
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        return candidate
    if isinstance(literal, ipaddress.IPv6Address) and literal.ipv4_mapped is not None:
        literal = literal.ipv4_mapped
    # The UI may render this URL, making the viewer's browser the requester.
    # Loopback/private targets must not become reachable through a search hit.
    return candidate if literal.is_global else ""


def _canonical_url(url: str) -> str:
    """Normalised URL used only to detect duplicates (fragment/tracking-free)."""
    safe = _display_url(url)
    if not safe:
        return ""
    parsed = urlparse(safe)
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = hostname
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith(_TRACKING_PREFIXES) and key.lower() not in _TRACKING_KEYS
        ]
    )
    return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))


def _dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    """Drop duplicate URLs, keep the best-ranked hit and merge engine names.

    Brave and DuckDuckGo frequently return the same page under tracking or
    trailing-slash variants. Concatenating both provider lists without this
    wastes context on duplicates and pushes genuinely different sources out of
    the result window.
    """
    chosen: dict[str, SearchHit] = {}
    order: list[str] = []
    for hit in hits:
        hit.url = _display_url(hit.url)
        if not hit.url:
            continue
        key = _canonical_url(hit.url)
        if not key:
            continue
        existing = chosen.get(key)
        if existing is None:
            chosen[key] = hit
            order.append(key)
            continue
        engines = {existing.source_engine, hit.source_engine}
        existing.source_engine = "+".join(sorted(engine for engine in engines if engine))
        if hit.score > existing.score:
            existing.title = hit.title or existing.title
            existing.snippet = hit.snippet or existing.snippet
            existing.url = hit.url
            existing.score = hit.score
            existing.age_hint = hit.age_hint or existing.age_hint
    return [chosen[key] for key in order]


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
    # Keep deep research aligned with the Search settings page: UI-saved keys
    # are encrypted at rest and resolved by the shared runtime credential path.
    from backend.tools.web_search import get_brave_api_key

    api_key = get_brave_api_key()
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

    client = _get_http_client(follow_redirects=False)
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
        raise SearchProviderError("brave") from exc
    except Exception as exc:
        logger.error("Brave search failed: %s", exc)
        raise SearchProviderError("brave") from exc


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

    client = _get_http_client(follow_redirects=True)
    try:
        response = await _request_with_retry(client, "POST", url, data=data, headers=headers)
        # DuckDuckGo answers automated clients with an empty 202 bot-check
        # page. Treating that as "no results" hid a total research outage.
        if response.status_code == 202:
            raise SearchProviderError("duckduckgo")
        soup = BeautifulSoup(response.text, "html.parser")
        hits: list[SearchHit] = []

        # Try multiple result selectors for resilience
        result_selectors = [
            ".result",
            ".web-result",
            ".result__body",
        ]
        results: list[Any] = []
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
            if href.startswith("//"):
                href = f"https:{href}"
            if "uddg=" in href or href.startswith(
                ("http://duckduckgo.com/l/", "https://duckduckgo.com/l/")
            ):
                match = re.search(r"uddg=([^&]+)", href)
                if match:
                    href = unquote(match.group(1))
            elif href.startswith("/"):
                href = f"https://duckduckgo.com{href}"

            snippet_tag = result.select_one(".result__snippet")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

            # Try to extract age hint
            age_hint = ""
            age_tag = result.select_one(".result__timestamp") or result.select_one(
                ".result__date"
            )
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
        raise SearchProviderError("duckduckgo") from exc


_QUERY_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "these", "those",
        "what", "when", "where", "which", "how", "why", "who", "are", "was",
        "were", "has", "have", "had", "into", "about", "your", "you", "not",
        "but", "all", "any", "can", "will", "would", "should", "could", "does",
        "did", "their", "there", "then", "than", "them", "they", "its", "our",
        "como", "para", "por", "que", "com", "uma", "dos", "das", "nos", "nas",
        "sobre", "mais", "nao", "seu", "sua", "pelo", "pela", "entre", "ate",
        "aos", "um", "em", "no", "na", "de", "do", "da", "os", "as",
    }
)


def _normalise_text(value: str) -> str:
    """Casefold and strip accents so query matching is script-insensitive."""
    decomposed = unicodedata.normalize("NFKD", (value or "").casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _query_terms(query: str) -> list[str]:
    """Return the meaningful terms of *query* (3+ chars, no stopwords)."""
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9][a-z0-9+_.-]{2,}", _normalise_text(query)):
        token = token.strip(".-_")
        if len(token) < 3 or token in _QUERY_STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
    return terms


def _hit_matches_query(hit: SearchHit, terms: list[str], *, required: int | None = None) -> bool:
    """Whether a hit is plausibly about the query.

    The keyless Bing HTML endpoint can answer a multi-word query with results
    matching only its first word (observed live 2026-11-21: a JWST query
    returned the band *James*). Such hits make the model answer confidently
    about the wrong subject, so a hit must cover a minimum share of the query
    terms. Single-term queries accept any hit; two or more terms require at
    least two distinct matches.
    """
    if not terms:
        return True
    if required is None:
        required = 1 if len(terms) == 1 else 2
    corpus = _normalise_text(f"{hit.title} {hit.snippet} {hit.url}")
    present = sum(1 for term in terms if term in corpus)
    return present >= min(len(terms), required)


def _unwrap_news_url(value: str) -> str:
    """Unwrap Bing News' ``apiclick.aspx?url=<target>`` wrapper."""
    candidate = _html_unescape(value or "").strip()
    if not candidate:
        return ""
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host == "bing.com" or host.endswith(".bing.com"):
        try:
            target = (parse_qs(parsed.query).get("url") or [""])[0]
        except ValueError:
            target = ""
        if target:
            return _display_url(target)
    return _display_url(candidate)


def _parse_bing_news_rss(markup: str, max_results: int) -> list[SearchHit]:
    """Parse Bing News RSS items into hits with a direct article URL."""
    hits: list[SearchHit] = []
    for block in re.findall(r"<item>(.*?)</item>", markup or "", re.S):
        title_match = re.search(r"<title>(.*?)</title>", block, re.S)
        link_match = re.search(r"<link>(.*?)</link>", block, re.S)
        if title_match is None or link_match is None:
            continue
        title = _html_unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", title_match.group(1))).strip()
        url = _unwrap_news_url(re.sub(r"<!\[CDATA\[|\]\]>", "", link_match.group(1)))
        if not title or not url:
            continue
        description = re.search(r"<description>(.*?)</description>", block, re.S)
        snippet = (
            _html_unescape(re.sub(r"<[^>]+>", " ", description.group(1))).strip()
            if description
            else ""
        )
        published = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
        age_hint = published.group(1).strip() if published else ""
        hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet=re.sub(r"\s+", " ", snippet),
                score=0.65,
                source_engine="bing_news",
                age_hint=age_hint,
                published_date=age_hint,
            )
        )
        if len(hits) >= max_results:
            break
    return hits


_NEWS_TIME_TOKENS_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"
    r"|\b(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december|janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|"
    r"setembro|outubro|novembro|dezembro)\b",
    re.IGNORECASE,
)


def _simplify_news_query(query: str) -> str:
    """Drop year/month tokens that empty an otherwise valid news query.

    Live check (2026-11-21): ``Portugal wildfires November 2026`` returned no
    RSS items while ``Portugal wildfires`` returned four. News search does not
    need the date words the user (or the model) added; the published date is in
    each item.
    """
    simplified = re.sub(r"\s+", " ", _NEWS_TIME_TOKENS_RE.sub(" ", query)).strip()
    return simplified if simplified and simplified != query.strip() else ""


async def _search_bing_news(
    query: str,
    max_results: int = 10,
    site_filter: str | None = None,
) -> list[SearchHit]:
    """Keyless news-vertical fallback with direct article URLs."""
    q = f"{query} site:{site_filter}" if site_filter else query
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml,application/xml,text/xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    client = _get_http_client(follow_redirects=True)
    try:
        response = await _request_with_retry(
            client,
            "GET",
            "https://www.bing.com/news/search",
            headers=headers,
            params={"q": q, "format": "rss", "count": min(max_results, 20)},
        )
        hits = _parse_bing_news_rss(response.text, max_results)
        if not hits and "captcha" in response.text.lower():
            raise SearchProviderError("bing_news")
        if not hits:
            simplified = _simplify_news_query(q)
            if simplified:
                retry = await _request_with_retry(
                    client,
                    "GET",
                    "https://www.bing.com/news/search",
                    headers=headers,
                    params={
                        "q": simplified,
                        "format": "rss",
                        "count": min(max_results, 20),
                    },
                )
                hits = _parse_bing_news_rss(retry.text, max_results)
                if hits:
                    logger.info("Bing News recovered with simplified query %r", simplified)
        return hits
    except SearchProviderError:
        raise
    except Exception as exc:
        logger.error("Bing News search failed: %s", exc)
        raise SearchProviderError("bing_news") from exc


async def _search_stackexchange(
    query: str,
    max_results: int = 5,
    site_filter: str | None = None,
) -> list[SearchHit]:
    """Keyless Stack Overflow search used when general results are unusable.

    The public API answers programming questions with direct, canonical links
    even on networks where the HTML search engines serve degraded results. The
    free tier allows 300 requests/day without a key, so this is a fallback, not
    a primary provider.
    """
    if site_filter and "stackoverflow" not in site_filter.casefold():
        return []
    client = _get_http_client(follow_redirects=True)
    try:
        response = await _request_with_retry(
            client,
            "GET",
            "https://api.stackexchange.com/2.3/search/advanced",
            headers={"Accept": "application/json"},
            params={
                "order": "desc",
                "sort": "relevance",
                "q": query,
                "site": "stackoverflow",
                "pagesize": min(max(1, max_results), 10),
            },
        )
        payload = response.json()
        items = payload.get("items") if isinstance(payload, dict) else None
    except Exception as exc:
        logger.error("Stack Overflow search failed: %s", exc)
        raise SearchProviderError("stackexchange") from exc

    hits: list[SearchHit] = []
    for item in items or []:
        url = _display_url(str(item.get("link") or ""))
        title = _html_unescape(str(item.get("title") or "")).strip()
        if not url or not title:
            continue
        tags = ", ".join(str(tag) for tag in (item.get("tags") or [])[:5])
        answered = "respondida" if item.get("is_answered") else "sem resposta aceite"
        score = item.get("score") or 0
        try:
            created = int(item.get("creation_date") or 0)
        except (TypeError, ValueError):
            created = 0
        published = (
            datetime.fromtimestamp(created, UTC).isoformat() if created > 0 else ""
        )
        hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet=f"[{tags}] · {answered} · score {score}",
                score=0.6 + min(0.2, float(score) / 100.0),
                source_engine="stackexchange",
                age_hint=published,
                published_date=published,
            )
        )
        if len(hits) >= max_results:
            break
    return hits


def _decode_bing_redirect(href: str) -> str:
    """Return the destination of a Bing ``/ck/a`` redirect.

    Bing wraps every result in ``https://www.bing.com/ck/a?...&u=a1<b64url>``;
    citing that wrapper instead of the page breaks the citation and makes a
    follow-up fetch hit Bing again.
    """
    candidate = _html_unescape(href or "").strip()
    if not candidate:
        return ""
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    is_bing_redirect = (host == "bing.com" or host.endswith(".bing.com")) and parsed.path.startswith(
        "/ck/a"
    )
    if not is_bing_redirect:
        return _display_url(candidate)
    try:
        value = (parse_qs(parsed.query).get("u") or [""])[0]
    except ValueError:
        return ""
    if not value:
        return ""
    if value.startswith("a1"):
        value = value[2:]
    try:
        padded = value + "=" * (-len(value) % 4)
        return _display_url(base64.urlsafe_b64decode(padded).decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return ""


def _parse_bing_hits(markup: str, max_results: int) -> list[SearchHit]:
    """Parse Bing's organic results (``li.b_algo``) into hits."""
    soup = BeautifulSoup(markup, "html.parser")
    hits: list[SearchHit] = []
    for block in soup.select("li.b_algo"):
        link = block.select_one("h2 a[href]")
        if link is None:
            continue
        url = _decode_bing_redirect(str(link.get("href") or ""))
        if not url:
            continue
        title = link.get_text(" ", strip=True)
        if not title:
            continue
        snippet_tag = block.select_one(".b_caption p") or block.select_one("p")
        snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
        hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet=snippet,
                source_engine="bing",
            )
        )
        if len(hits) >= max_results:
            break
    return hits


async def _search_bing(
    query: str,
    max_results: int = 10,
    site_filter: str | None = None,
    recency_days: int | None = None,
) -> list[SearchHit]:
    """Search Bing's HTML endpoint as the keyless third provider.

    Brave needs an API key and DuckDuckGo's HTML endpoint answers bot checks
    with an empty ``202`` page on many networks, so without this fallback a
    machine with no Brave key could not research at all (verified live
    2026-11-21). Bing's recency filter is not applied here; the query itself
    is passed unchanged apart from ``site:``.
    """
    q = f"{query} site:{site_filter}" if site_filter else query
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    client = _get_http_client(follow_redirects=True)
    try:
        response = await _request_with_retry(
            client,
            "GET",
            "https://www.bing.com/search",
            headers=headers,
            params={"q": q, "count": min(max_results, 20), "setlang": "en"},
        )
        markup = response.text
        hits = _parse_bing_hits(markup, max_results)
        lowered = markup.lower()
        if not hits and ("captcha" in lowered or "unusual traffic" in lowered):
            raise SearchProviderError("bing")
        return hits
    except SearchProviderError:
        raise
    except Exception as exc:
        logger.error("Bing search failed: %s", exc)
        raise SearchProviderError("bing") from exc


async def _search_with_fallback(
    query: str,
    max_results: int,
    site_filter: str | None,
    recency_days: int | None,
) -> list[SearchHit]:
    """Query the providers concurrently and merge what came back.

    Sequential Brave-then-DuckDuckGo paid the full latency of the first
    provider even when it had no hits. Running them in parallel gives the
    fallback for free in wall-clock terms; the merge is deduped because the
    engines routinely return the same page under tracking/trailing-slash
    variants. Provider outages are still reported strictly: if nothing answered
    at all, this raises instead of returning a misleading empty result (which
    the cache decorator would then keep for an hour). Hits that a provider did
    return but the relevance guard rejected are a genuine no-result, not an
    outage. Bing covers machines with no Brave key, where DuckDuckGo often
    serves its bot-check page.
    """
    tasks = [
        asyncio.create_task(
            _search_brave(
                query,
                max_results=max_results,
                site_filter=site_filter,
                recency_days=recency_days,
            )
        ),
        asyncio.create_task(
            _search_duckduckgo(
                query,
                max_results=max_results,
                site_filter=site_filter,
                recency_days=recency_days,
            )
        ),
        asyncio.create_task(
            _search_bing(
                query,
                max_results=max_results,
                site_filter=site_filter,
                recency_days=recency_days,
            )
        ),
    ]
    done, pending = await asyncio.wait(tasks, timeout=max(0.01, SEARCH_DEADLINE))
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    failures: list[str] = []
    merged: list[SearchHit] = []
    succeeded = False
    from backend.tools.web_search import get_brave_api_key

    brave_configured = bool(get_brave_api_key())
    terms = _query_terms(query)
    dropped = 0
    for provider, task in zip(("brave", "duckduckgo", "bing"), tasks, strict=False):
        if provider == "brave" and not brave_configured:
            # No key: nothing was attempted, so it neither succeeded nor failed.
            continue
        if task in pending:
            # A provider that did not answer within the search budget is an
            # outage for reporting purposes, but completed results are kept.
            failures.append(provider)
            continue
        try:
            result = task.result()
        except SearchProviderError as exc:
            failures.append(exc.provider)
            continue
        except Exception:  # noqa: BLE001 - reported as a provider failure
            failures.append(provider)
            continue
        succeeded = True
        if provider == "bing":
            # Bing's keyless endpoint degrades to first-word matches. Filtering
            # only this provider keeps a real Brave/DuckDuckGo hit that does not
            # repeat the query verbatim.
            kept = [hit for hit in result if _hit_matches_query(hit, terms)]
            dropped += len(result) - len(kept)
            result = kept
        merged.extend(result)

    if dropped:
        logger.info(
            "Dropped %d Bing hit(s) that did not cover the query terms %s",
            dropped,
            terms[:8],
        )
    merged = _dedupe_hits(merged)

    # A degraded general provider answered, but nothing it returned is about
    # the query. The news vertical honours the full query, and Stack Exchange
    # is a reliable keyless source for programming questions, so give both one
    # bounded chance before reporting no result.
    if not merged and succeeded:
        fallbacks = await asyncio.gather(
            _search_bing_news(query, max_results=max_results, site_filter=site_filter),
            _search_stackexchange(query, max_results=max_results, site_filter=site_filter),
            return_exceptions=True,
        )
        recovered: list[SearchHit] = []
        for provider, outcome in zip(("bing_news", "stackexchange"), fallbacks, strict=False):
            if isinstance(outcome, SearchProviderError):
                failures.append(outcome.provider)
                continue
            if isinstance(outcome, BaseException):
                failures.append(provider)
                continue
            recovered.extend(outcome)
        merged = _dedupe_hits(
            [hit for hit in recovered if _hit_matches_query(hit, terms)]
        )

    if merged:
        return merged
    # "Providers unavailable" is only true when every configured provider
    # failed. An empty answer from a provider that ran is a no-result.
    if failures and not succeeded:
        raise SearchProvidersUnavailable(failures)
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

    hits = await _search_with_fallback(
        clean_query,
        max_results=max_results,
        site_filter=site_filter,
        recency_days=recency_days,
    )

    hits = _dedupe_hits(_rank_hits(clean_query, hits))[: max(1, int(max_results))]
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
    selectors: list[tuple[str, dict[str, Any]]] = [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "pubdate"}),
        ("meta", {"name": "publish-date"}),
        ("meta", {"name": "date"}),
        ("meta", {"property": "og:published_time"}),
    ]
    for tag_name, attrs in selectors:
        tag = soup.find(tag_name, attrs=attrs)
        content = tag.get("content") if tag else None
        if isinstance(content, str) and content:
            return content

    time_tag = soup.find("time")
    datetime_value = time_tag.get("datetime") if time_tag else None
    if isinstance(datetime_value, str) and datetime_value:
        return datetime_value

    return ""


_IMAGE_META_KEYS = frozenset(
    {
        "og:image",
        "og:image:url",
        "og:image:secure_url",
        "twitter:image",
        "twitter:image:src",
    }
)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")

_SMALL_IMAGE_DIMS_RE = re.compile(r"(?<!\d)(\d{2,3})x(\d{2,3})(?!\d)")
_IMAGE_WIDTH_PARAM_RE = re.compile(r"[?&](?:width|w)=(\d{1,3})(?:&|$)")
_DECORATIVE_IMAGE_RE = re.compile(
    r"(?:^|[/._-])(?:logo|logos|sprite|sprites|favicon|avatar|badge|icon|icons|"
    r"placeholder|spacer|pixel)(?:[/._-]|$)",
    re.IGNORECASE,
)


def _is_decorative_image(url: str) -> bool:
    """True for logos, icons and thumbnails too small to show as content."""
    if _DECORATIVE_IMAGE_RE.search(url):
        return True
    path = urlparse(url).path.lower()
    if path.endswith(".svg"):
        # Vector marks are icons or logos; photographs are raster.
        return True
    for width, height in _SMALL_IMAGE_DIMS_RE.findall(url):
        if int(width) < 300 and int(height) < 300:
            return True
    width_param = _IMAGE_WIDTH_PARAM_RE.search(url)
    return bool(width_param and int(width_param.group(1)) < 300)


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Extract unique, display-safe links from a BeautifulSoup document."""
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not isinstance(href, str) or not href.strip():
            continue
        full = _display_url(urljoin(base_url, href.strip()))
        if not full:
            continue
        key = _canonical_url(full)
        if key and key not in seen:
            seen.add(key)
            links.append(full)
    return links[:50]


def _extract_images_bs4(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Collect absolute, display-safe page images with alt text and source.

    Covers ``og:image``/``twitter:image`` and normal/``data-src`` ``<img>``
    tags. ``javascript:``, ``data:``, relative-only and credential-bearing
    URLs are dropped; the model/UI must never be handed an executable URL.
    Logos, icons and sub-300px thumbnails are dropped as site chrome.
    """
    images: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(raw_url: Any, alt: str = "", title: str = "") -> None:
        if not isinstance(raw_url, str) or not raw_url.strip():
            return
        full = _display_url(urljoin(base_url, raw_url.strip()))
        if not full:
            return
        if _is_decorative_image(full):
            return
        key = _canonical_url(full)
        if not key or key in seen:
            return
        seen.add(key)
        images.append(
            {
                "url": full,
                "alt": str(alt or title or "")[:300].strip(),
                "title": str(title or alt or "")[:300].strip(),
                "source": base_url,
            }
        )

    for meta in soup.find_all("meta"):
        marker = str(meta.get("property") or meta.get("name") or "").lower()
        if marker in _IMAGE_META_KEYS and meta.get("content"):
            add(meta["content"])

    for image in soup.find_all("img"):
        source = image.get("src") or image.get("data-src") or image.get("data-original")
        if not source and image.get("srcset"):
            source = str(image["srcset"]).split(",")[0].strip().split(" ")[0]
        add(source, str(image.get("alt") or ""), str(image.get("title") or ""))
        if len(images) >= MAX_IMAGES:
            break

    return images[:MAX_IMAGES]


def _images_from_markdown(text: str, base_url: str) -> list[dict[str, Any]]:
    """Extract image links from Jina Reader Markdown."""
    images: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alt, raw_url in _MARKDOWN_IMAGE_RE.findall(text):
        full = _display_url(raw_url)
        if not full:
            continue
        key = _canonical_url(full)
        if not key or key in seen:
            continue
        seen.add(key)
        images.append({"url": full, "alt": alt[:300], "title": "", "source": base_url})
        if len(images) >= MAX_IMAGES:
            break
    return images


def _extract_text_bs4(
    html: str, base_url: str
) -> tuple[str, str, list[str], str, list[dict[str, Any]]]:
    """Extract title, main text, links, publish date and images from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    og_title = soup.find("meta", property="og:title")
    og_title_value = og_title.get("content") if og_title else None
    if isinstance(og_title_value, str) and og_title_value:
        title = og_title_value

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
    images = _extract_images_bs4(soup, base_url)

    return title, text, links, published_date, images


async def _fetch_via_jina(url: str, max_length: int = 500) -> FetchedContent | None:
    """Try fetching via Jina AI Reader API (opt-in third-party reader)."""
    if not remote_reader_enabled():
        return None
    try:
        url = normalize_public_http_url(url)
    except ValueError:
        return None
    jina_url = f"https://r.jina.ai/{url}"
    try:
        client = _get_http_client(follow_redirects=False)
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
            links=links[:50],
            images=_images_from_markdown(content, url),
        )
    except Exception as exc:
        logger.debug("Jina fetch failed for %s: %s", url, exc)
        return None


async def _fetch_via_httpx(url: str, max_length: int = 500) -> FetchedContent | None:
    """Fallback fetch via httpx + BeautifulSoup."""
    try:
        url = normalize_public_http_url(url)
        client = _get_http_client(follow_redirects=True)
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
        title, text, links, published_date, images = _extract_text_bs4(html, url)
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
            links=links[:50],
            images=images,
        )
    except Exception as exc:
        logger.error("HTTPX fetch failed for %s: %s", url, exc)
        return None


@cache_result("fetch_content_v2:", ttl=FETCH_CACHE_TTL)
async def _fetch_and_summarize_cached(url: str, max_length: int = 500) -> dict[str, Any]:
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
            "summary": "Error fetching URL: unable to retrieve content",
            "content": "",
            "published_date": "",
            "content_length": 0,
            "extraction_method": "failed",
            "links": [],
            "images": [],
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
        "images": result.images,
        "status": "success",
    }


async def fetch_and_summarize(url: str, max_length: int = 500) -> dict[str, Any]:
    """Validate the URL before a cached result can bypass network controls."""
    try:
        normalized_url = normalize_public_http_url(url)
    except ValueError as exc:
        return {
            "url": str(url)[:2000],
            "title": "",
            "summary": f"Error fetching URL: {exc}",
            "content": "",
            "published_date": "",
            "content_length": 0,
            "extraction_method": "blocked",
            "links": [],
            "images": [],
            "status": "error",
        }
    return cast(
        dict[str, Any],
        await _fetch_and_summarize_cached(normalized_url, max_length=max_length),
    )


# ---------------------------------------------------------------------------
# Search + fetch + synthesize (deep research)
# ---------------------------------------------------------------------------

NO_RESULTS_ERROR = "No search provider returned hits for this query; no answer was synthesised."
NO_EVIDENCE_ERROR = (
    "Search returned hits but every page fetch failed; no answer was synthesised."
)

_EVIDENCE_TERM_RE = re.compile(r"\b\w{3,}\b")
_OVERLAP_BASIS = "phrase_overlap_4gram"


def _evidence_confidence(query: str, evidence: list[str], attempted: int) -> float:
    """Return a confidence derived only from the pages that were actually read.

    A search-hit score ranks *candidate* URLs. It says nothing about whether the
    page exists, is readable, or says anything about the query, so it can never
    justify a confidence value on its own -- reporting one would let the tool
    claim high confidence while nothing at all had been retrieved. This function
    therefore takes the text that came back from the pages, not the hits.

    The value is a retrieval heuristic: the share of query terms the retrieved
    pages cover, damped by the share of attempted pages that were readable. It
    is not a measure of corroboration between sources, and it is ``0.0`` when
    no evidence was retrieved because there is then nothing to be confident
    about -- the caller is told separately via ``error_category``.
    """
    if not evidence:
        return 0.0
    q_words = set(_EVIDENCE_TERM_RE.findall(query.lower()))
    coverages = [
        (sum(1 for word in q_words if word in text.lower()) / len(q_words)) if q_words else 0.0
        for text in evidence
    ]
    term_coverage = sum(coverages) / len(coverages)
    retrieval_ratio = len(evidence) / attempted if attempted else 0.0
    return round(min(1.0, 0.7 * term_coverage + 0.3 * retrieval_ratio), 2)


def _cross_reference_facts(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Report the lexical overlap between the summaries that were fetched.

    This counts 4-word phrases shared by *every* summary. That is surface-form
    similarity between scraped text, not agreement about a claim, so the score
    is reported as ``phrase_overlap_score`` and never as ``consensus``: a
    reader who saw "87% consensus across sources" would take it for
    independent corroboration, and it is nothing of the kind.

    Contradiction detection is NOT implemented here. No claim is extracted, so
    this function cannot say whether sources agree or disagree; it therefore
    returns no ``conflicts`` key at all instead of an empty list, which would
    imply "checked and found none".

    A single source has nothing to overlap with, so it reports ``0.0`` rather
    than a mid value: one page cannot corroborate itself.
    """
    if not summaries:
        return {"phrase_overlap_score": 0.0, "common_phrases": [], "basis": _OVERLAP_BASIS}

    # Heuristic: 4-word phrases shared by every fetched summary.
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
        return {"phrase_overlap_score": 0.0, "common_phrases": [], "basis": _OVERLAP_BASIS}

    common = all_phrases[0].intersection(*all_phrases[1:])
    common_sorted = sorted(common, key=lambda p: len(p), reverse=True)[:10]

    return {
        "phrase_overlap_score": round(min(len(common) / 10, 1.0), 2),
        "common_phrases": common_sorted,
        "basis": _OVERLAP_BASIS,
    }


async def _fetch_many(
    urls: list[str], *, max_length: int, deadline: float | None = None
) -> list[Any]:
    """Fetch *urls* with bounded concurrency and one whole-batch deadline.

    ``asyncio.gather`` alone has no ceiling: one unreachable host (three
    retries x 15 s plus backoff) could hold the research call far longer than
    every other fetch combined. Results keep the input order; a timed-out or
    failed page is returned as an exception so the caller can count it as a
    fetch failure without losing the pages that did complete.
    """
    if not urls:
        return []

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def _one(url: str) -> dict[str, Any]:
        async with semaphore:
            # A single slow host must not hold the whole batch: the global
            # deadline is a ceiling, not a target.
            return await asyncio.wait_for(
                fetch_and_summarize(url, max_length=max_length),
                timeout=FETCH_PAGE_DEADLINE,
            )

    tasks = [asyncio.create_task(_one(url)) for url in urls]
    budget = RESEARCH_DEADLINE if deadline is None else deadline
    done, pending = await asyncio.wait(tasks, timeout=max(0.01, budget))
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    results: list[Any] = []
    for task in tasks:
        if task in done:
            try:
                results.append(task.result())
            except Exception as exc:  # noqa: BLE001 - reported as a fetch failure
                results.append(exc)
        else:
            results.append(TimeoutError("research fetch deadline exceeded"))
    return results


def _collect_images(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge per-page images into one display list keyed by absolute URL."""
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        for image in source.get("images") or []:
            url = _display_url(image.get("url"))
            if not url:
                continue
            key = _canonical_url(url)
            if not key or key in seen:
                continue
            seen.add(key)
            collected.append(
                {
                    "url": url,
                    "alt": str(image.get("alt") or image.get("title") or "")[:300],
                    "source": _display_url(image.get("source")) or source.get("url", ""),
                }
            )
            if len(collected) >= MAX_IMAGES:
                return collected
    return collected


def _prefer_descriptive_title(page_title: str, hit_title: str) -> str:
    """Keep the article title when the page exposes only the site name.

    Some CMS pages report ``<title>MSN</title>`` while the search index knows
    the article title. A two-word site name is not a usable citation label.
    """
    page_title = str(page_title or "").strip()
    hit_title = str(hit_title or "").strip()
    if not page_title:
        return hit_title
    if len(page_title) < 20 and len(hit_title) > len(page_title) + 10:
        return hit_title
    return page_title


def _build_research_brief(
    query: str,
    sources: list[dict[str, Any]],
    images: list[dict[str, Any]],
    confidence: float,
) -> str:
    """Build the compact, citable brief the model consumes first.

    Deliberately structured rather than prose: numbered sources with an
    inline ``[n] URL`` citation, a date when the page exposed one, and a short
    excerpt. The whole block stays under ``BRIEF_MAX_CHARS`` so it survives
    the agent's 6000-char tool-result budget instead of being truncated in the
    middle.
    """
    lines = [
        f"# Research brief: {query}",
        (
            f"Confidence: {confidence:.0%} (retrieval heuristic; "
            f"{len(sources)} page(s) read)"
        ),
        "",
    ]
    for index, source in enumerate(sources, 1):
        title = str(source.get("title") or "Untitled").strip()
        url = source.get("url", "")
        date = str(source.get("published_date") or "").strip()
        suffix = f" | {date}" if date else ""
        lines.append(f"[{index}] {title} — {url}{suffix}")
        excerpt = " ".join(str(source.get("summary") or source.get("snippet") or "").split())
        if excerpt:
            lines.append(f"  {excerpt[:420]}")
        page_images = source.get("images") or []
        if page_images:
            lines.append(f"  Images: {len(page_images)}")
        lines.append("")

    if images:
        lines.append("## Images")
        for index, image in enumerate(images[:8], 1):
            label = image.get("alt") or "image"
            lines.append(
                f"- [{index}] {label} — {image.get('url')} "
                f"(source: {image.get('source') or 'unknown'})"
            )

    return "\n".join(lines)[:BRIEF_MAX_CHARS]


@cache_result("deep_research:", ttl=SEARCH_CACHE_TTL)
async def search_and_answer(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the web, fetch top results, and synthesize a coherent answer.

    Args:
        query: Search query.
        max_results: Number of top results to fetch and include.

    Returns:
        dict with ``query``, ``sources``, ``answer``, ``confidence``, ``consensus``.

        ``answer`` is ``""`` -- never a prose shell with empty headings -- and
        ``error_category`` is set when nothing could be synthesised:
        ``no_results`` (no provider returned hits) or ``no_evidence`` (hits
        existed but every page fetch failed). ``confidence`` comes only from
        the pages that were retrieved, so it is ``0.0`` in both failure shapes.
        ``consensus`` keeps its top-level name but reports ``phrase_overlap_score``
        (lexical overlap, not corroboration) and carries no ``conflicts`` key.
    """
    clean_query, site = _extract_site_filter(query)
    started = time.perf_counter()

    # 1. Search (bounded by SEARCH_DEADLINE inside _search_with_fallback)
    hits = await _search_with_fallback(
        clean_query,
        max_results=max_results * 2,
        site_filter=site,
        recency_days=None,
    )

    if not hits:
        return {
            "query": query,
            "brief": "",
            "sources": [],
            "answer": "",
            "confidence": 0.0,
            "consensus": _cross_reference_facts([]),
            "images": [],
            "error": NO_RESULTS_ERROR,
            "error_category": "no_results",
            "attempted_urls": [],
            "fetch_failure_count": 0,
        }

    hits = _dedupe_hits(_rank_hits(clean_query, hits))[:max_results]

    # 2. Fetch content concurrently, bounded. Subtract the time already spent
    # searching so the whole call stays near RESEARCH_DEADLINE, not search +
    # full fetch budget.
    remaining = RESEARCH_DEADLINE - (time.perf_counter() - started)
    fetched_list = await _fetch_many(
        [h.url for h in hits], max_length=800, deadline=remaining
    )

    fetched: list[dict[str, Any]] = []
    evidence: list[str] = []
    failed_urls: list[str] = []
    for hit, content in zip(hits, fetched_list, strict=False):
        if isinstance(content, Exception):
            logger.warning("Fetch failed for %s: %s", hit.url, content)
            failed_urls.append(hit.url)
            continue
        if content.get("status") == "error":
            failed_urls.append(hit.url)
            continue
        page_title = content.get("title", "")
        page_summary = content.get("summary", hit.snippet)
        fetched.append(
            {
                "url": hit.url,
                "title": _prefer_descriptive_title(page_title, hit.title),
                "summary": page_summary,
                "snippet": hit.snippet,
                "published_date": content.get("published_date", ""),
                "extraction_method": content.get("extraction_method", ""),
                "images": (content.get("images") or [])[:MAX_IMAGES],
                "links": (content.get("links") or [])[:MAX_LINKS],
            }
        )
        # Only text that came back from the page itself counts as evidence; the
        # search snippet fallback must not sneak back in as retrieved content.
        page_text = f"{page_title} {page_summary}".strip()
        if page_text:
            evidence.append(page_text)

    confidence = _evidence_confidence(query, evidence, attempted=len(hits))

    # 3. No evidence retrieved: say so instead of emitting headings over nothing.
    if not evidence:
        logger.warning(
            "deep_research retrieved no evidence for %s (%d fetch failures)",
            query,
            len(failed_urls),
        )
        return {
            "query": query,
            "brief": "",
            "sources": [
                {
                    "url": h.url,
                    "title": h.title,
                    "snippet": h.snippet,
                    "score": h.score,
                }
                for h in hits
            ],
            "answer": "",
            "confidence": 0.0,
            "consensus": _cross_reference_facts([]),
            "images": [],
            "error": NO_EVIDENCE_ERROR,
            "error_category": "no_evidence",
            "attempted_urls": [h.url for h in hits],
            "fetch_failure_count": len(failed_urls),
        }

    # 4. Cross-reference fetched text (lexical overlap only)
    overlap = _cross_reference_facts(fetched)
    images = _collect_images(fetched)
    brief = _build_research_brief(query, fetched, images, confidence)

    # 5. Synthesize answer
    synthesis_parts = [f"# Research: {query}\n"]
    synthesis_parts.append(
        f"\n*Evidence confidence: {confidence:.0%} "
        f"(from {len(fetched)} of {len(hits)} retrieved pages; "
        "a retrieval heuristic, not corroboration between sources)*\n"
    )

    synthesis_parts.append("\n## Sources\n")
    for i, item in enumerate(fetched, 1):
        date_str = f" ({item['published_date']})" if item.get("published_date") else ""
        synthesis_parts.append(f"{i}. [{item['title']}]({item['url']}){date_str}\n")

    synthesis_parts.append("\n## Key Findings\n")
    for i, item in enumerate(fetched, 1):
        synthesis_parts.append(f"\n### Source {i}: {item['title']}\n")
        synthesis_parts.append(item["snippet"])
        if item["summary"] and item["summary"] != item["snippet"]:
            synthesis_parts.append(f"\n{item['summary'][:800]}")

    if overlap["common_phrases"]:
        synthesis_parts.append("\n## Shared Phrases (lexical overlap, not corroboration)\n")
        for phrase in overlap["common_phrases"][:5]:
            synthesis_parts.append(f"- {phrase}")

    answer = "\n".join(synthesis_parts)

    return {
        "query": query,
        # ``brief`` first: it is the field the model should read and cite.
        "brief": brief,
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
        "consensus": overlap,
        # ``images`` last so the tail of the 6000-char tool-result budget keeps
        # the absolute display URLs even if the middle of the JSON is cut.
        "images": images,
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

    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        trust_env=False,
        transport=PublicAddressHTTPTransport(),
    ) as client:
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
            "Fast multi-provider web search (Brave, DuckDuckGo and Bing queried "
            "in parallel, whichever are reachable), deduped and ranked by "
            "relevance and recency. Returns title, URL, snippet, score and "
            "age/date hint. Supports site: filters and recency_days."
        ),
        when_to_use=(
            "Use for a list of candidate sources, or when you need a site "
            "filter (site='github.com') or results from the last N days "
            "(recency_days). Follow up with fetch_content_v2 on the best URLs."
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
                    "minimum": 1,
                    "maximum": 20,
                    "description": "How many hits to return (1-20)",
                },
                "site": {
                    "type": "string",
                    "description": "Optional domain filter (e.g. github.com)",
                },
                "recency_days": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional recency window in days",
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
            "Fetch one page and return a structured, LLM-ready result: title, "
            "summary, cleaned main content, publish date, outbound links, and "
            "absolute image URLs with alt text and source page. Uses the "
            "configured reader (Jina when enabled) then direct extraction."
        ),
        when_to_use=(
            "Use after search_web_v2/deep_research to read a specific URL in "
            "depth, or when you need the page's images and outbound links. "
            "Only HTTP(S) public URLs are fetched."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute public HTTP(S) URL to fetch",
                },
                "max_length": {
                    "type": "integer",
                    "default": 500,
                    "minimum": 100,
                    "maximum": 8000,
                    "description": "Maximum summary characters (default 500)",
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
            "One-shot deep research: searches all reachable providers in "
            "parallel, "
            "fetches the top pages concurrently under a deadline, and returns "
            "a compact cited `brief` (numbered [n] URL sources with dates and "
            "excerpts), the per-source `answer`, and a deduped `images` list. "
            "The whole call is bounded to ~45 s."
        ),
        when_to_use=(
            "Use for a factual question that needs a synthesized, citable "
            "answer and images from several sites. Prefer it over search_web_v2 "
            "when the user wants an answer, not just links. When the user asks "
            "for visuals, embed up to four entries from `images` in your answer "
            "as ![alt](url)."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research question; supports site: filtering",
                },
                "max_results": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 8,
                    "description": "Pages to fetch and analyse (1-8)",
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
            "Search GitHub repositories by query, language and minimum stars. "
            "Returns name, URL, description, stars, language and last update."
        ),
        when_to_use=(
            "Use when you need existing open-source projects or a reference "
            "implementation, not documentation prose."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Repository search terms",
                },
                "language": {
                    "type": "string",
                    "description": "Optional language, e.g. python",
                },
                "stars_min": {
                    "type": "integer",
                    "default": 100,
                    "minimum": 0,
                    "description": "Minimum star count (default 100)",
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
            "(python, react, docker, rust, go, etc.) with a domain boost, "
            "falling back to a general web search when the framework is unknown."
        ),
        when_to_use=(
            "Use when the answer must come from vendor documentation rather "
            "than blogs. Prefer it over a plain web search for API/reference "
            "questions about a known framework."
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
