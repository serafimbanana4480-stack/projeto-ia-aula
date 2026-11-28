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
import base64
import contextlib
import ipaddress
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from html import unescape as _html_unescape
from typing import Any
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlunparse

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


SEARCH_DEADLINE = _env_float("NEXUS_RESEARCH_SEARCH_SECONDS", 15.0)
RESEARCH_DEADLINE = _env_float("NEXUS_RESEARCH_DEADLINE_SECONDS", 45.0)
MAX_CONCURRENT_FETCHES = _env_int("NEXUS_RESEARCH_MAX_CONCURRENT_FETCHES", 5)
FETCH_PAGE_DEADLINE = _env_float("NEXUS_RESEARCH_FETCH_SECONDS", 12.0)
BRIEF_MAX_CHARS = _env_int("NEXUS_RESEARCH_BRIEF_CHARS", 3200)
MAX_IMAGES = 12

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


#: One client per (redirect policy, event loop), so repeated searches in a
#: session reuse connections/TLS instead of building a pool per call.
_shared_clients: dict[str, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}


def _get_http_client(*, follow_redirects: bool) -> httpx.AsyncClient:
    """Return the shared guarded client for the current event loop."""
    key = "redirect" if follow_redirects else "strict"
    loop = asyncio.get_running_loop()
    entry = _shared_clients.get(key)
    if entry is not None and entry[0] is loop and not entry[1].is_closed:
        return entry[1]
    client = httpx.AsyncClient(
        timeout=15.0,
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
            with contextlib.suppress(Exception):
                await client.aclose()
    _shared_clients.clear()


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
# Display URL safety / dedupe
# ---------------------------------------------------------------------------

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = frozenset(
    {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref_src", "ref_url", "si"}
)


def _display_url(value: Any) -> str:
    """Return a display-safe absolute HTTP(S) URL, or ``""``.

    Search hits are third-party data: ``javascript:``, ``data:``,
    credential-bearing and malformed URLs must not reach the model or UI.
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
    """Normalised URL used only to detect duplicates."""
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
    """Drop duplicate URLs and merge engine names, keeping the best hit."""
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


async def search_images(query: str, max_results: int = 12) -> dict[str, Any]:
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
    params: dict[str, str | int] = {
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

    client = _get_http_client(follow_redirects=True)
    try:
        response = await _request_with_retry(client, "POST", url, data=data, headers=headers)
        # DuckDuckGo answers automated clients with an empty 202 bot-check
        # page. Treating that as "no results" hid a total research outage.
        if response.status_code == 202:
            raise SearchProviderError("duckduckgo")
        soup = BeautifulSoup(response.text, "html.parser")
        hits: list[SearchHit] = []
        for result in soup.select(".result"):
            a_tag = result.select_one(".result__a")
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            href_value = a_tag.get("href")
            if not isinstance(href_value, str) or not href_value.strip():
                continue
            href = href_value
            # DuckDuckGo redirects via their own URL. Handle absolute,
            # protocol-relative and root-relative forms; the old code
            # missed "//duckduckgo.com/l/..." and left a redirect URL as
            # the "source" the model would later try to cite.
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

    Search engines occasionally answer a multi-word query with results that
    only match its first word (observed with Bing's keyless HTML endpoint on
    2026-11-21: "James Webb Space Telescope recent discoveries" returned the
    band *James*). Feeding those hits to the model produces a confidently
    wrong answer, so a Bing hit must mention at least two query terms.
    Single-term queries accept any hit.
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
    """Keyless news-vertical fallback with direct article URLs.

    The general Bing HTML endpoint can serve a degraded result set that only
    matches the first query word. The news vertical honours the full query and
    is structured RSS instead of markup, so it is used when the general
    providers produced no *relevant* hit.
    """
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
        hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet=f"[{tags}] · {answered} · score {score}",
                score=0.6 + min(0.2, float(score) / 100.0),
                source_engine="stackexchange",
                age_hint=str(item.get("creation_date") or ""),
            )
        )
        if len(hits) >= max_results:
            break
    return hits


def _decode_bing_redirect(href: str) -> str:
    """Return the destination of a Bing ``/ck/a`` redirect.

    Bing wraps every result in ``https://www.bing.com/ck/a?...&u=a1<b64url>``.
    Handing that wrapper to the model as the source URL makes citations
    useless and makes the next fetch hit Bing instead of the page.
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
) -> list[SearchHit]:
    """Search Bing's HTML endpoint.

    This is the keyless third provider. Brave needs an API key and
    DuckDuckGo's HTML endpoint answers bot checks with an empty ``202`` page
    on many networks, so without this fallback a machine with no Brave key
    could not research at all (verified live 2026-11-21). Best-effort: Bing
    can rate-limit or change markup, in which case the call reports a
    provider failure instead of a false "no results".
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
) -> list[SearchHit]:
    """Query the providers concurrently and merge/dedupe their hits.

    Sequential Brave-then-DuckDuckGo paid full latency for Brave even when
    DuckDuckGo was the one with results. Failures stay honest: a provider
    outage is never converted into a cached "no results" answer. Bing is the
    keyless fallback for machines where DuckDuckGo serves its bot-check page.
    """
    tasks = [
        asyncio.create_task(
            _search_brave(query, max_results=max_results, site_filter=site_filter)
        ),
        asyncio.create_task(
            _search_duckduckgo(query, max_results=max_results, site_filter=site_filter)
        ),
        asyncio.create_task(
            _search_bing(query, max_results=max_results, site_filter=site_filter)
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
    brave_configured = bool(get_brave_api_key())
    terms = _query_terms(query)
    dropped = 0
    for provider, task in zip(("brave", "duckduckgo", "bing"), tasks, strict=False):
        if provider == "brave" and not brave_configured:
            # No key: nothing was attempted, so it neither succeeded nor failed.
            continue
        if task in pending:
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
    # failed. A provider that answered with an empty page (or hits the
    # relevance guard rejected) is a genuine no-result — reporting an outage
    # there misleads the model into retrying a search that did run (verified
    # live 2026-11-21).
    if failures and not succeeded:
        raise SearchProvidersUnavailable(failures)
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
    hits = await _search_with_fallback(clean_query, max_results=max_results, site_filter=site)
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


async def _fetch_many(urls: list[str], *, deadline: float | None = None) -> list[Any]:
    """Fetch *urls* with bounded concurrency and a whole-batch deadline.

    ``asyncio.gather`` had no ceiling, so one unreachable host (three retries
    with backoff) could stall the whole research call after every other page
    had already returned.
    """
    if not urls:
        return []

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def _one(url: str) -> dict[str, Any]:
        async with semaphore:
            # A single slow host must not hold the whole batch: the global
            # deadline is a ceiling, not a target. Fast pages still land.
            return await asyncio.wait_for(
                fetch_and_summarize(url), timeout=FETCH_PAGE_DEADLINE
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
    """Build a compact, cited brief that survives the tool-result budget."""
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
    started = time.perf_counter()

    # 1. Search (bounded by SEARCH_DEADLINE inside _search_with_fallback)
    hits = await _search_with_fallback(
        clean_query,
        max_results=max_results * 2,
        site_filter=site,
    )

    if not hits:
        return {
            "query": query,
            "brief": "",
            "sources": [],
            "answer": "",
            "confidence": 0.0,
            "images": [],
            "error": NO_RESULTS_ERROR,
            "error_category": "no_results",
            "attempted_urls": [],
            "fetch_failure_count": 0,
        }

    hits = _dedupe_hits(_rank_hits(clean_query, hits))[:max_results]

    # 2. Fetch content concurrently, bounded. The search time is subtracted
    # from the budget so the whole call stays near RESEARCH_DEADLINE.
    remaining = RESEARCH_DEADLINE - (time.perf_counter() - started)
    fetched_list = await _fetch_many([h.url for h in hits], deadline=remaining)

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
                "links": (content.get("links") or [])[:20],
                "images": (content.get("images") or [])[:MAX_IMAGES],
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
            "images": [],
            "error": NO_EVIDENCE_ERROR,
            "error_category": "no_evidence",
            "attempted_urls": [h.url for h in hits],
            "fetch_failure_count": len(failed_urls),
        }

    images = _collect_images(fetched)
    brief = _build_research_brief(query, fetched, images, confidence)

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
        "images": images,
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

register_tool(
    ToolSpec(
        name="web_search",
        description=(
            "Search the web with Brave, DuckDuckGo and Bing queried in "
            "parallel (whichever are reachable); results are deduped and "
            "ranked. Returns title, URL, snippet, score, engine and age hint. "
            "Supports site: filters."
        ),
        when_to_use=(
            "Use for a quick list of sources. Use search_web_v2 when you also "
            "need a recency_days window, and deep_research when you need a "
            "synthesized, cited answer."
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
                    "description": "Number of results (1-20)",
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
            "Fetch one public HTTP(S) page and return title, cleaned summary, "
            "publish date, outbound links, and absolute image URLs (with alt "
            "and source page). Cached for one hour."
        ),
        when_to_use=(
            "Use to read a specific result in depth or to collect the images "
            "and links of one page. Prefer fetch_content_v2 when you need the "
            "fuller content/date fields."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute public HTTP(S) URL to fetch",
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
        description=(
            "Search, fetch the top pages concurrently under a 45 s deadline, "
            "and return a compact cited `brief` plus an `answer` and an "
            "`images` list. Fails honestly (empty answer + error_category) "
            "when no page could be read."
        ),
        when_to_use=(
            "Use for a question that needs an answer backed by several "
            "sources. `search_and_answer` returns a `brief`; when the user "
            "asked for visuals, embed up to four entries from `images` in your "
            "answer as ![alt](url). `deep_research` is the richer/newer "
            "equivalent."
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
                    "default": 3,
                    "minimum": 1,
                    "maximum": 8,
                    "description": "Pages to fetch and cite (1-8)",
                },
            },
            "required": ["query"],
        },
        handler=search_and_answer,
    )
)

register_tool(
    ToolSpec(
        name="search_images",
        description=(
            "Image search (Brave Images). Returns up to 50 display-ready hits: "
            "title, absolute source-page URL, Brave-proxied thumbnail URL, "
            "source host and pixel dimensions. Unsafe or non-HTTPS thumbnails "
            "are dropped."
        ),
        when_to_use=(
            "Use only when the user explicitly asks for pictures/illustrations "
            "or when images are needed alongside text results. For a page's "
            "own images, fetch the page instead."
        ),
        tags=["web", "external"],
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What the images should depict",
                },
                "max_results": {
                    "type": "integer",
                    "default": 12,
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Number of images (1-50, default 12)",
                },
            },
            "required": ["query"],
        },
        handler=search_images,
    )
)
