"""Web content fetcher with extraction, caching, and retry logic.

Fetches URLs using:
1. Jina AI Reader (r.jina.ai) — free, fast, returns clean Markdown
2. Direct fetch via httpx + BeautifulSoup4 fallback

Results are cached in SQLite (``data/web_cache.db``) for 1 hour.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from backend.tools.registry import ToolSpec, register_tool
from backend.tools.safe_http import (
    PublicAddressHTTPTransport,
    normalize_public_http_url,
    remote_reader_enabled,
)

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 15.0
MAX_RETRIES = 3
BASE_DELAY = 1.0
CACHE_TTL_SECONDS = 3600  # 1 hour

CACHE_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "web_cache.db"

# ---------------------------------------------------------------------------
# SQLite cache helpers
# ---------------------------------------------------------------------------


def _init_cache_db() -> None:
    """Ensure the web cache database exists with proper schema."""
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(CACHE_DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_cache (
                url TEXT PRIMARY KEY,
                title TEXT,
                summary TEXT,
                links TEXT,
                status TEXT,
                created_at REAL,
                expires_at REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_web_cache_expires ON web_cache(expires_at)")
        conn.commit()


def _cache_get(url: str) -> dict[str, Any] | None:
    """Retrieve cached fetch result if still valid."""
    _init_cache_db()
    try:
        now = time.time()
        with sqlite3.connect(str(CACHE_DB_PATH)) as conn:
            row = conn.execute(
                "SELECT url, title, summary, links, status FROM web_cache "
                "WHERE url = ? AND expires_at > ?",
                (url, now),
            ).fetchone()
            if row:
                return {
                    "url": row[0],
                    "title": row[1] or "",
                    "summary": row[2] or "",
                    "links": json.loads(row[3]) if row[3] else [],
                    "status": row[4] or "",
                }
    except Exception as exc:
        logger.warning("Web cache read failed for %s: %s", url, exc)
    return None


def _cache_set(url: str, result: dict[str, Any]) -> None:
    """Store fetch result in cache."""
    _init_cache_db()
    try:
        now = time.time()
        with sqlite3.connect(str(CACHE_DB_PATH)) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO web_cache
                   (url, title, summary, links, status, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    result["url"],
                    result.get("title", ""),
                    result.get("summary", ""),
                    json.dumps(result.get("links", [])),
                    result.get("status", "cached"),
                    now,
                    now + CACHE_TTL_SECONDS,
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("Web cache write failed for %s: %s", url, exc)


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


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------


def _extract_text_bs4(html: str, base_url: str) -> tuple[str, str, list[str]]:
    """Extract title, main text, and links from HTML using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noisy elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    # Try to find main content area
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"content|main|article", re.I))
    )
    if main:
        text = main.get_text(separator="\n", strip=True)
    else:
        text = soup.get_text(separator="\n", strip=True)

    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Extract links
    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme in ("http", "https") and full not in seen:
            seen.add(full)
            links.append(full)

    return title, text, links[:50]


async def _fetch_via_jina(url: str) -> dict[str, Any] | None:
    """Try fetching via Jina AI Reader API."""
    if not remote_reader_enabled():
        return None
    url = normalize_public_http_url(url)
    jina_url = f"https://r.jina.ai/{url}"
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            transport=PublicAddressHTTPTransport(),
        ) as client:
            response = await _request_with_retry(client, "GET", jina_url)
            text = response.text
            lines = text.splitlines()
            title = ""
            content_lines: list[str] = []
            links: list[str] = []
            for line in lines:
                line = line.strip()
                if line.startswith("Title:"):
                    title = line.replace("Title:", "").strip()
                elif line.startswith("URL:"):
                    pass
                elif line:
                    content_lines.append(line)
                    # Extract markdown links
                    for match in re.finditer(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line):
                        links.append(match.group(2))
            summary = "\n".join(content_lines)
            return {
                "url": url,
                "title": title,
                "summary": summary,
                "links": links,
                "status": "fetched_via_jina",
            }
    except Exception as exc:
        logger.debug("Jina fetch failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_and_summarize(url: str) -> dict[str, Any]:
    """Fetch a URL and extract main content with caching and fallback.

    Args:
        url: The URL to fetch.

    Returns:
        dict with keys: ``url``, ``title``, ``summary``, ``links``, ``status``.
    """
    try:
        url = normalize_public_http_url(url)
    except ValueError as exc:
        return {
            "url": str(url)[:2000],
            "title": "",
            "summary": f"Error fetching URL: {exc}",
            "links": [],
            "status": "error",
        }

    # Validate before consulting the cache so a cached response cannot make an
    # unsupported scheme, local IP, or credential-bearing URL appear fetchable.
    cached = _cache_get(url)
    if cached:
        cached["status"] = "cache_hit"
        return cached

    # Try Jina AI first (fast, clean extraction)
    jina_result = await _fetch_via_jina(url)
    if jina_result:
        _cache_set(url, jina_result)
        return jina_result

    # Fallback to direct fetch + BeautifulSoup
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            trust_env=False,
            transport=PublicAddressHTTPTransport(),
        ) as client:
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
            title, text, links = _extract_text_bs4(html, url)

            # Truncate summary to keep token counts reasonable
            summary = text[:4000] if text else ""
            result = {
                "url": url,
                "title": title,
                "summary": summary,
                "links": links[:20],
                "status": "fetched_direct",
            }
            _cache_set(url, result)
            return result
    except Exception as exc:
        logger.error("Failed to fetch %s: %s", url, exc)
        return {
            "url": url,
            "title": "",
            "summary": f"Error fetching URL: {exc}",
            "links": [],
            "status": "error",
        }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

register_tool(
    ToolSpec(
        name="fetch_and_summarize",
        description=(
            "Fetch a URL and return a structured summary with title, "
            "main text, and extracted links."
        ),
        schema={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to fetch"}},
            "required": ["url"],
        },
        handler=fetch_and_summarize,
    )
)
