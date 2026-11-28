"""Web content fetcher with extraction, caching, and retry logic.

Fetches URLs using:
1. Jina AI Reader (r.jina.ai) — free, fast, returns clean Markdown
2. Direct fetch via httpx + BeautifulSoup4 fallback

Results are cached in SQLite (``data/web_cache.db``) for 1 hour.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
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
SUMMARY_MAX_CHARS = 4000
MAX_IMAGES = 12

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
                expires_at REAL,
                images TEXT,
                published_date TEXT
            )
            """
        )
        # Existing databases predate the metadata columns. Additive migration
        # only: nothing is dropped and old rows keep serving their text.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(web_cache)")}
        if "images" not in columns:
            conn.execute("ALTER TABLE web_cache ADD COLUMN images TEXT")
        if "published_date" not in columns:
            conn.execute("ALTER TABLE web_cache ADD COLUMN published_date TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_web_cache_expires ON web_cache(expires_at)")
        conn.commit()


def _cache_get(url: str) -> dict[str, Any] | None:
    """Retrieve cached fetch result if still valid."""
    _init_cache_db()
    try:
        now = time.time()
        with sqlite3.connect(str(CACHE_DB_PATH)) as conn:
            row = conn.execute(
                "SELECT url, title, summary, links, status, images, published_date "
                "FROM web_cache WHERE url = ? AND expires_at > ?",
                (url, now),
            ).fetchone()
            if row:
                return {
                    "url": row[0],
                    "title": row[1] or "",
                    "summary": row[2] or "",
                    "links": json.loads(row[3]) if row[3] else [],
                    "status": row[4] or "",
                    "images": json.loads(row[5]) if row[5] else [],
                    "published_date": row[6] or "",
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
                   (url, title, summary, links, status, created_at, expires_at,
                    images, published_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result["url"],
                    result.get("title", ""),
                    result.get("summary", ""),
                    json.dumps(result.get("links", [])),
                    result.get("status", "cached"),
                    now,
                    now + CACHE_TTL_SECONDS,
                    json.dumps(result.get("images", [])),
                    result.get("published_date", ""),
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


#: Reuse one guarded client per (redirect policy, event loop). Without this a
#: Jina attempt + a direct fallback built two clients (and two connection
#: pools) per URL, so a 5-URL research fan-out paid the TLS handshake cost
#: repeatedly. Loop-keyed because a client cannot cross event loops.
_shared_clients: dict[str, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}


def _get_http_client(*, follow_redirects: bool) -> httpx.AsyncClient:
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
        href_value = a.get("href")
        if not isinstance(href_value, str):
            continue
        href = href_value
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme in ("http", "https") and full not in seen:
            seen.add(full)
            links.append(full)

    return title, text, links[:50]


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


def _display_url(value: Any) -> str:
    """Absolute HTTP(S) URL safe to show to the model/UI, else ``""``."""
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
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
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
    return candidate if literal.is_global else ""


# Site chrome that masquerades as content: 96x96 thumbnails, logos, sprites,
# avatars. Research results that include them look broken next to the article
# image the user actually wants.
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


def _extract_images_bs4(html: str, base_url: str) -> list[dict[str, Any]]:
    """Extract absolute image URLs with alt/title and their source page."""
    soup = BeautifulSoup(html, "html.parser")
    images: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(raw_url: Any, alt: str = "", title: str = "") -> None:
        if not isinstance(raw_url, str) or not raw_url.strip():
            return
        full = _display_url(urljoin(base_url, raw_url.strip()))
        if not full or full in seen:
            return
        if _is_decorative_image(full):
            return
        seen.add(full)
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


def _extract_publish_date(html: str) -> str:
    """Extract a publish date from common meta tags or ``<time>``."""
    soup = BeautifulSoup(html, "html.parser")
    selectors: tuple[dict[str, Any], ...] = (
        {"property": "article:published_time"},
        {"name": "pubdate"},
        {"name": "publish-date"},
        {"name": "date"},
        {"property": "og:published_time"},
    )
    for attributes in selectors:
        tag = soup.find("meta", attrs=attributes)
        content = tag.get("content") if tag else None
        if isinstance(content, str) and content:
            return content
    time_tag = soup.find("time")
    datetime_value = time_tag.get("datetime") if time_tag else None
    if isinstance(datetime_value, str) and datetime_value:
        return datetime_value
    return ""


# Stack Overflow and its siblings answer the browser with HTTP 403 (bot
# protection) while their public API serves the same question body keyless.
# Mapping used by ``_fetch_stackexchange_question``.
_STACKEXCHANGE_HOSTS = {
    "stackoverflow.com": "stackoverflow",
    "superuser.com": "superuser",
    "serverfault.com": "serverfault",
    "askubuntu.com": "askubuntu",
    "stackapps.com": "stackapps",
    "mathoverflow.net": "mathoverflow",
}


def _stackexchange_target(url: str) -> tuple[str, str] | None:
    """Return ``(api_site, question_id)`` for a Stack Exchange question URL."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    site = _STACKEXCHANGE_HOSTS.get(host)
    if site is None and host.endswith(".stackexchange.com"):
        site = host.removesuffix(".stackexchange.com") or None
    if not site:
        return None
    match = re.match(r"^/questions/(\d+)(?:/|$)", parsed.path)
    if not match:
        return None
    return site, match.group(1)


async def _fetch_stackexchange_question(url: str) -> dict[str, Any] | None:
    """Read a Stack Exchange question through the public API.

    The HTML page returns 403 to non-browser clients (verified live
    2026-11-21), which made every Stack Overflow research source a fetch
    failure even though the search API had just found it. The API returns the
    question body without a key. Returns ``None`` on any failure so the caller
    falls back to the normal fetch path.
    """
    target = _stackexchange_target(url)
    if target is None:
        return None
    site, question_id = target
    try:
        client = _get_http_client(follow_redirects=False)
        response = await _request_with_retry(
            client,
            "GET",
            f"https://api.stackexchange.com/2.3/questions/{question_id}",
            params={"site": site, "filter": "withbody"},
        )
        items = response.json().get("items") or []
    except Exception as exc:  # noqa: BLE001 - caller falls back to HTML fetch
        logger.warning("Stack Exchange API fetch failed for %s: %s", url, exc)
        return None
    if not items:
        return None

    item = items[0]
    body_html = str(item.get("body") or "")
    soup = BeautifulSoup(body_html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, str(anchor["href"]))
        if href.startswith(("http://", "https://")) and href not in links:
            links.append(href)
        if len(links) >= 20:
            break

    created = item.get("creation_date")
    published_date = ""
    if isinstance(created, (int, float)) and created > 0:
        published_date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(created))

    return {
        "url": url,
        "title": str(item.get("title") or ""),
        "summary": text[:SUMMARY_MAX_CHARS],
        "content_length": len(text),
        "published_date": published_date,
        "images": _extract_images_bs4(body_html, url)[:MAX_IMAGES],
        "links": links,
        "status": "fetched_stackexchange",
    }


async def _fetch_via_jina(url: str) -> dict[str, Any] | None:
    """Try fetching via Jina AI Reader API."""
    if not remote_reader_enabled():
        return None
    url = normalize_public_http_url(url)
    jina_url = f"https://r.jina.ai/{url}"
    try:
        client = _get_http_client(follow_redirects=False)
        response = await _request_with_retry(client, "GET", jina_url)
        text = response.text
        lines = text.splitlines()
        title = ""
        published_date = ""
        content_lines: list[str] = []
        links: list[str] = []
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
                # Extract markdown links
                for match in re.finditer(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line):
                    links.append(match.group(2))
        content = "\n".join(content_lines)
        # Jina returns the whole page. The old code stored all of it as
        # ``summary``, which a single fetch could dump into the 6000-char
        # model budget. Keep the head, report the true length.
        summary = content[:SUMMARY_MAX_CHARS]
        images: list[dict[str, Any]] = []
        seen_images: set[str] = set()
        for match in _MARKDOWN_IMAGE_RE.finditer(content):
            image_url = _display_url(match.group(2))
            if image_url and image_url not in seen_images:
                seen_images.add(image_url)
                images.append(
                    {
                        "url": image_url,
                        "alt": match.group(1)[:300],
                        "title": "",
                        "source": url,
                    }
                )
            if len(images) >= MAX_IMAGES:
                break
        return {
            "url": url,
            "title": title,
            "summary": summary,
            "content_length": len(content),
            "published_date": published_date,
            "images": images,
            "links": links[:50],
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
        dict with keys: ``url``, ``title``, ``summary``, ``links``, ``images``,
        ``published_date``, ``status``. ``images`` holds absolute display URLs
        with alt text and their source page.
    """
    try:
        url = normalize_public_http_url(url)
    except ValueError as exc:
        return {
            "url": str(url)[:2000],
            "title": "",
            "summary": f"Error fetching URL: {exc}",
            "links": [],
            "images": [],
            "published_date": "",
            "status": "error",
        }

    # Validate before consulting the cache so a cached response cannot make an
    # unsupported scheme, local IP, or credential-bearing URL appear fetchable.
    cached = _cache_get(url)
    if cached:
        cached["status"] = "cache_hit"
        return cached

    # Stack Overflow pages reject browser-less fetches; its API does not.
    stackexchange_result = await _fetch_stackexchange_question(url)
    if stackexchange_result:
        _cache_set(url, stackexchange_result)
        return stackexchange_result

    # Try Jina AI first (fast, clean extraction)
    jina_result = await _fetch_via_jina(url)
    if jina_result:
        _cache_set(url, jina_result)
        return jina_result

    # Fallback to direct fetch + BeautifulSoup
    try:
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
        title, text, links = _extract_text_bs4(html, url)

        # Truncate summary to keep token counts reasonable
        summary = text[:SUMMARY_MAX_CHARS] if text else ""
        result = {
            "url": url,
            "title": title,
            "summary": summary,
            "content_length": len(text),
            "published_date": _extract_publish_date(html),
            "images": _extract_images_bs4(html, url),
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
            "images": [],
            "published_date": "",
            "status": "error",
        }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

register_tool(
    ToolSpec(
        name="fetch_and_summarize",
        description=(
            "Fetch one public HTTP(S) page and return title, cleaned summary, "
            "publish date, extracted links, and absolute image URLs with alt "
            "text and source page. Cached for one hour."
        ),
        when_to_use=(
            "Use to read a specific URL when you need its text, images and "
            "outbound links. Prefer fetch_content_v2 for the richer content "
            "field; both are cached and SSRF-guarded."
        ),
        schema={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to fetch"}},
            "required": ["url"],
        },
        handler=fetch_and_summarize,
    )
)
