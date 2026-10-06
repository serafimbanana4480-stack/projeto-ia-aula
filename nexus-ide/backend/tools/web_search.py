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
from backend.tools.safe_http import PublicAddressHTTPTransport
from backend.tools.search_errors import SearchProviderError, SearchProvidersUnavailable
from backend.tools.web_fetcher import fetch_and_summarize

logger = logging.getLogger(__name__)

SEARCH_CACHE_TTL = 3600  # 1 hour
FETCH_CACHE_TTL = 1800  # 30 minutes
BRAVE_IMAGE_THUMBNAIL_HOST = "imgs.search.brave.com"

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

    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=False,
        trust_env=False,
        transport=PublicAddressHTTPTransport(),
    ) as client:
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


def get_brave_api_key() -> str:
    """Resolve Brave credentials from the encrypted runtime store or env."""
    try:
        # Settings entered through the UI are encrypted at rest. Read them via
        # the canonical loader instead of handing the ciphertext to Brave.
        from backend.orchestrator.routes.settings import _load_runtime_settings

        runtime_settings = _load_runtime_settings()
    except Exception as exc:  # noqa: BLE001 - search can still use its no-key fallback
        logger.warning("Could not load runtime Brave credentials (%s)", type(exc).__name__)
        runtime_settings = {}
    configured = str(runtime_settings.get("brave_api_key", "") or "").strip()
    if configured:
        return configured
    # Match the settings UI's runtime-override precedence. A stored key may
    # replace an environment fallback; leaving the input empty preserves env.
    return str(getattr(get_settings(), "brave_api_key", "") or "").strip()


def _safe_url(value: Any, *, schemes: tuple[str, ...], host: str | None = None) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    try:
        parsed = urlparse(candidate)
        hostname = parsed.hostname
        # Accessing port also validates malformed bracket/port syntax.
        _ = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() not in schemes
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    if host is not None and hostname.lower() != host:
        return ""
    if host is not None and parsed.port not in (None, 443):
        return ""
    return candidate


def normalize_brave_image_results(data: Any, limit: int = 24) -> list[dict[str, Any]]:
    """Return safe, display-ready image hits; never keep raw provider payloads."""
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        return []
    hits: list[dict[str, Any]] = []
    for item in data["results"]:
        if not isinstance(item, dict):
            continue
        thumbnail = item.get("thumbnail")
        properties = item.get("properties")
        meta_url = item.get("meta_url")
        thumbnail = thumbnail if isinstance(thumbnail, dict) else {}
        properties = properties if isinstance(properties, dict) else {}
        meta_url = meta_url if isinstance(meta_url, dict) else {}
        # Brave documents ``url`` as the originating page, while
        # ``properties.url`` is the original image file. The UI links to the
        # source page and renders only Brave's proxied thumbnail.
        page_url = _safe_url(item.get("url"), schemes=("http", "https"))
        thumbnail_url = _safe_url(
            thumbnail.get("src"),
            schemes=("https",),
            host=BRAVE_IMAGE_THUMBNAIL_HOST,
        )
        if not page_url or not thumbnail_url:
            continue
        source = item.get("source") or meta_url.get("hostname") or ""
        hits.append(
            {
                "title": str(item.get("title") or source or "Imagem")[:500],
                "url": page_url,
                "thumbnail_url": thumbnail_url,
                "source": str(source)[:200],
                "width": _positive_dimension(
                    thumbnail.get("width") or properties.get("width")
                ),
                "height": _positive_dimension(
                    thumbnail.get("height") or properties.get("height")
                ),
            }
        )
        if len(hits) >= max(1, min(int(limit), 50)):
            break
    return hits


def _positive_dimension(value: Any) -> int | None:
    try:
        dimension = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return dimension if 0 < dimension <= 20_000 else None


async def search_images(query: str, max_results: int = 24) -> dict[str, Any]:
    """Search Brave Images without caching third-party results."""
    normalized_query = query.strip()
    if not normalized_query:
        return {"query": "", "hits": [], "count": 0, "configured": bool(get_brave_api_key())}
    api_key = get_brave_api_key()
    if not api_key:
        return {
            "query": normalized_query,
            "hits": [],
            "count": 0,
            "configured": False,
            "error": "Pesquisa de imagens indisponível: falta configurar a chave Brave.",
            "error_code": "not_configured",
        }

    url = "https://api.search.brave.com/res/v1/images/search"
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
        "Cache-Control": "no-cache",
    }
    params = {
        "q": normalized_query[:400],
        "count": max(1, min(int(max_results), 50)),
        "safesearch": "strict",
    }
    try:
        # The Brave credential is sent in a custom header (not Authorization).
        # HTTPX preserves custom headers across cross-origin redirects, so keep
        # this fixed provider endpoint redirect-free to prevent token disclosure.
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=False,
            trust_env=False,
            transport=PublicAddressHTTPTransport(),
        ) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        message = (
            "A chave Brave não foi aceite. Confirma a configuração."
            if status in {401, 403}
            else "O limite da pesquisa de imagens foi atingido. Tenta mais tarde."
            if status == 429
            else "O fornecedor de pesquisa de imagens não respondeu corretamente."
        )
        logger.warning("Brave image search failed with HTTP %s", status)
        return {
            "query": normalized_query,
            "hits": [],
            "count": 0,
            "configured": True,
            "error": message,
            "error_code": (
                "invalid_credentials"
                if status in {401, 403}
                else "rate_limited"
                if status == 429
                else "provider_error"
            ),
        }
    except (httpx.RequestError, ValueError) as exc:
        logger.warning("Brave image search request failed (%s)", type(exc).__name__)
        return {
            "query": normalized_query,
            "hits": [],
            "count": 0,
            "configured": True,
            "error": "Não foi possível ligar ao fornecedor de pesquisa de imagens.",
            "error_code": "provider_unavailable",
        }

    hits = normalize_brave_image_results(payload, max_results)
    return {
        "query": normalized_query,
        "hits": hits,
        "count": len(hits),
        "configured": True,
        "provider": "brave",
    }
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

    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=True,
        trust_env=False,
        transport=PublicAddressHTTPTransport(),
    ) as client:
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
            raise SearchProviderError("duckduckgo") from exc


async def _search_with_fallback(
    query: str,
    max_results: int,
    site_filter: str | None,
) -> list[SearchHit]:
    """Try Brave first, then DuckDuckGo, keeping provider failures distinct from no hits."""
    failures: list[str] = []
    try:
        hits = await _search_brave(query, max_results=max_results, site_filter=site_filter)
    except SearchProviderError as exc:
        failures.append(exc.provider)
        hits = []

    if hits:
        return hits

    try:
        fallback_hits = await _search_duckduckgo(
            query,
            max_results=max_results,
            site_filter=site_filter,
        )
    except SearchProviderError as exc:
        failures.append(exc.provider)
        raise SearchProvidersUnavailable(failures) from exc

    # A failed primary plus an empty fallback cannot safely be represented as
    # a genuine no-results answer. Raising also keeps the cache decorator from
    # storing that misleading empty response for its one-hour TTL.
    if failures and not fallback_hits:
        raise SearchProvidersUnavailable(failures)
    return fallback_hits


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
    hits = await _search_with_fallback(clean_query, max_results=max_results, site_filter=site)
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

NO_RESULTS_ERROR = "No search provider returned hits for this query; no answer was synthesised."
NO_EVIDENCE_ERROR = (
    "Search returned hits but every page fetch failed; no answer was synthesised."
)

_EVIDENCE_TERM_RE = re.compile(r"\b\w{3,}\b")


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


@cache_result("search_answer:", ttl=SEARCH_CACHE_TTL)
async def search_and_answer(query: str, max_results: int = 3) -> dict[str, Any]:
    """Search the web, fetch top results, and synthesize a coherent answer.

    Args:
        query: Search query. Supports ``site:`` filtering.
        max_results: Number of top results to fetch and include.

    Returns:
        dict with ``query``, ``sources``, ``answer``, ``confidence``.

        ``answer`` is ``""`` -- never a prose shell with nothing under it -- and
        ``error_category`` is set when nothing could be synthesised:
        ``no_results`` (no provider returned hits) or ``no_evidence`` (hits
        existed but every page fetch failed). ``confidence`` comes only from the
        pages that were retrieved, so it is ``0.0`` in both failure shapes.
    """
    clean_query, site = _extract_site_filter(query)

    # 1. Search
    hits = await _search_with_fallback(
        clean_query,
        max_results=max_results * 2,
        site_filter=site,
    )

    if not hits:
        return {
            "query": query,
            "sources": [],
            "answer": "",
            "confidence": 0.0,
            "error": NO_RESULTS_ERROR,
            "error_category": "no_results",
            "attempted_urls": [],
            "fetch_failure_count": 0,
        }

    hits = _rank_hits(clean_query, hits)[:max_results]

    # 2. Fetch content concurrently
    fetch_tasks = [fetch_and_summarize(h.url) for h in hits]
    fetched_list = await asyncio.gather(*fetch_tasks, return_exceptions=True)

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
                "title": page_title or hit.title,
                "summary": page_summary,
                "snippet": hit.snippet,
            }
        )
        # Only text that came back from the page itself counts as evidence; the
        # search snippet fallback must not sneak back in as retrieved content.
        page_text = f"{page_title} {page_summary}".strip()
        if page_text:
            evidence.append(page_text)

    confidence = _evidence_confidence(query, evidence, attempted=len(hits))

    # 3. No evidence retrieved: say so instead of emitting a heading over nothing.
    if not evidence:
        logger.warning(
            "search_and_answer retrieved no evidence for %s (%d fetch failures)",
            query,
            len(failed_urls),
        )
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
            "answer": "",
            "confidence": 0.0,
            "error": NO_EVIDENCE_ERROR,
            "error_category": "no_evidence",
            "attempted_urls": [h.url for h in hits],
            "fetch_failure_count": len(failed_urls),
        }

    # 4. Synthesize answer
    synthesis_parts = [f"## Answer for: {query}\n"]
    synthesis_parts.append(
        f"*Evidence confidence: {confidence:.0%} "
        f"(from {len(fetched)} of {len(hits)} retrieved pages)*\n"
    )
    for i, item in enumerate(fetched, 1):
        synthesis_parts.append(f"\n### Source {i}: [{item['title']}]({item['url']})\n")
        # Include both snippet and first part of summary
        synthesis_parts.append(item["snippet"])
        if item["summary"] and item["summary"] != item["snippet"]:
            synthesis_parts.append(f"\n{item['summary'][:800]}")

    answer = "\n".join(synthesis_parts)

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
