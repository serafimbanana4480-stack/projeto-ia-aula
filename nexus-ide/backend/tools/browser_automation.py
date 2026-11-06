"""Browser automation tool using Playwright async API.

Maintains a tenant-scoped context pool so multiple conversations have
independent browser sessions even when their session ids match.

Two hardening notes for this module:

* Every HTTP request, redirect and subresource is screened before Playwright
  continues it. Playwright resolves the hostname again after the check, so DNS
  rebinding remains a residual race until the browser socket can be pinned.
  WebSocket connections receive the same URL and DNS check.
* ``session_id`` is model/REST supplied and is used both as a pool key and as
  part of a screenshot filename, so it is constrained to a conservative
  character set by :func:`_normalize_session_id` before either use.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from backend.observability.optional_deps import optional_attribute
from backend.tools.registry import ToolSpec, register_tool
from backend.tools.safe_http import normalize_public_http_url, validate_public_http_url

# Playwright is an optional extra (``uv sync --extra browser``) because it also
# requires a ~150 MB browser download, and no path in main.py reaches this tool.
# Both names below are lazy stand-ins: this module imports (so the tool registry
# can describe the tool) without playwright installed, and the first real call
# raises a MissingOptionalDependency naming the extra.
if TYPE_CHECKING:
    # `Page` appears only in annotations, which PEP 563 leaves unevaluated, so
    # the runtime value is irrelevant to the type checker -- and a type checker
    # cannot resolve the real class either, because the extra is not installed in
    # the default environment. Naming it `Any` keeps the annotations honest about
    # that instead of pretending to a class it cannot see.
    type Page = Any
else:
    Page = optional_attribute("playwright.async_api", "Page", extra="browser", owner=__name__)

async_playwright = optional_attribute(
    "playwright.async_api", "async_playwright", extra="browser", owner=__name__
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30_000  # 30 seconds in ms
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# In-memory pool: opaque tenant-specific key -> browser handles.
_pool: dict[str, dict[str, Any]] = {}

#: Matches the REST layer's ``session_id`` bound in
#: ``backend/orchestrator/routes/browser.py`` so nothing that is valid over HTTP
#: becomes invalid at the tool boundary.
_SESSION_ID_MAX_LENGTH = 128

#: A session id becomes a dict key and a filename component, so it is limited to
#: a single conservative path segment: it must start with an alphanumeric (which
#: alone rules out "." and "..") and may then contain only alphanumerics, "_",
#: "." and "-". No separators, no whitespace, no control characters, no
#: traversal. Windows-reserved device names are refused separately, in
#: :func:`_is_windows_device_name`, because no regex over this alphabet can
#: express them.
_SESSION_ID_PATTERN = re.compile(
    rf"\A[A-Za-z0-9][A-Za-z0-9_.-]{{0,{_SESSION_ID_MAX_LENGTH - 1}}}\Z"
)
_SESSION_ID_SCHEMA_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"

#: Windows will not create a file whose name is one of these (ignoring any
#: extension) and resolves such a name to the device instead of to a file, so a
#: session id equal to one of them would silently target a device. The set is
#: checked case-insensitively and on the part before the first dot, so ``CON``,
#: ``con`` and ``con.txt`` are all covered.
_WINDOWS_RESERVED_DEVICE_NAMES: frozenset[str] = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


def _is_windows_device_name(value: str) -> bool:
    """Whether *value* is a Windows-reserved device name as a whole segment."""
    return value.split(".", 1)[0].lower() in _WINDOWS_RESERVED_DEVICE_NAMES


def _normalize_session_id(session_id: str | None) -> str:
    """Return a session id that is safe as a pool key and as a path segment.

    Raises:
        ValueError: if the value cannot be reduced to a safe single segment.
    """
    value = (session_id or "").strip()
    if not value:
        return "default"
    if not _SESSION_ID_PATTERN.match(value):
        raise ValueError(
            "session_id must be 1-"
            f"{_SESSION_ID_MAX_LENGTH} characters using only letters, digits, "
            "'.', '_' and '-', and must start with a letter or digit"
        )
    if _is_windows_device_name(value):
        raise ValueError(
            "session_id must not be a Windows-reserved device name "
            "(CON, PRN, AUX, NUL, COM1-COM9, LPT1-LPT9)"
        )
    return value


def _browser_pool_key(session_id: str | None, user_id: str) -> str:
    """Build a stable, tenant-specific key without exposing user identifiers."""
    owner = str(user_id or "").strip()
    if not owner:
        raise ValueError("A trusted authenticated user context is required")
    safe_session = _normalize_session_id(session_id)
    owner_key = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:16]
    session_key = hashlib.sha256(safe_session.encode("utf-8")).hexdigest()[:32]
    return f"{owner_key}_{session_key}"


def _screenshot_dir() -> Path:
    path = Path(__file__).resolve().parent.parent.parent / "data" / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _screenshot_path(session_id: str | None, owner_key: str = "unscoped") -> Path:
    """Build a screenshot path that is confined to the screenshot directory.

    Safe by construction: the only interpolated value is the output of
    :func:`_normalize_session_id`, which cannot contain a path separator or a
    leading dot. The containment assertion afterwards is deliberate belt-and-braces
    — a filename write outside the screenshots directory would be a silent file
    write anywhere on the host's filesystem, so it is checked rather than assumed.
    """
    safe_id = _normalize_session_id(session_id)
    if not re.fullmatch(r"[A-Fa-f0-9]{1,32}|unscoped", owner_key):
        raise ValueError("owner_key must be a short hexadecimal tenant digest")
    directory = _screenshot_dir()
    candidate = directory / f"screenshot_{owner_key}_{safe_id}_{int(time.time())}.png"
    resolved_dir = directory.resolve()
    resolved = candidate.resolve()
    if resolved.parent != resolved_dir:
        raise ValueError("Refusing to write a screenshot outside the screenshot directory")
    return resolved


async def _get_or_create_session(session_id: str) -> dict[str, Any]:
    """Return an existing session or launch a new headless browser context."""
    safe_id = _normalize_session_id(session_id)
    if safe_id in _pool:
        return _pool[safe_id]

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = None
    try:
        context = await browser.new_context(
            user_agent=_USER_AGENT,
            service_workers="block",
        )
        await context.route("**/*", _guard_browser_route)
        route_web_socket = getattr(context, "route_web_socket", None)
        if not callable(route_web_socket):
            raise RuntimeError(
                "Safe browser sessions require Playwright 1.48 or newer for WebSocket routing"
            )
        await route_web_socket("**/*", _guard_browser_websocket)
        page = await context.new_page()
        await page.set_default_timeout(_DEFAULT_TIMEOUT)
    except BaseException:
        if context is not None:
            try:
                await context.close()
            except Exception:
                logger.debug("Could not close partial browser context", exc_info=True)
        try:
            await browser.close()
        except Exception:
            logger.debug("Could not close partial browser process", exc_info=True)
        try:
            await pw.stop()
        except Exception:
            logger.debug("Could not stop partial Playwright instance", exc_info=True)
        raise

    session = {
        "playwright": pw,
        "browser": browser,
        "context": context,
        "page": page,
    }
    _pool[safe_id] = session
    logger.info("Browser session created: %s", safe_id)
    return session


async def _guard_browser_route(route: Any, request: Any) -> None:
    """Validate each browser network request before it reaches the socket.

    Playwright invokes the context route for navigation, redirects and page
    subresources. Service workers are disabled when the context is created so
    they cannot bypass this request hook. ``data:``, ``blob:`` and ``about:``
    are browser-local schemes and make no network connection.
    """
    request_url = str(getattr(request, "url", "") or "")
    scheme = request_url.split(":", 1)[0].lower()
    if scheme in {"data", "blob", "about"}:
        await route.continue_()
        return
    try:
        await validate_public_http_url(request_url)
    except Exception as exc:
        logger.warning("Blocked browser request to %r: %s", request_url, exc)
        await route.abort("blockedbyclient")
        return
    await route.continue_()


async def _guard_browser_websocket(websocket: Any) -> None:
    """Apply the public-host and DNS guard to a page-created WebSocket."""
    raw_url = str(getattr(websocket, "url", "") or "")
    try:
        parsed = urlsplit(raw_url)
        scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme.lower())
        if not scheme:
            raise ValueError("Only ws:// and wss:// WebSocket URLs are allowed")
        checked_url = urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, ""))
        await validate_public_http_url(checked_url)
    except Exception as exc:
        logger.warning("Blocked browser WebSocket to %r: %s", raw_url, exc)
        await websocket.close(code=1008, reason="destination is not public")
        return
    await websocket.connect_to_server()


async def _ensure_page(session_id: str) -> Page:
    """Return the page for a session, creating the session if necessary."""
    session = await _get_or_create_session(session_id)
    return session["page"]


def _result(**kwargs: Any) -> dict[str, Any]:
    """Standard result envelope."""
    return kwargs


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------


async def browser_navigate(
    url: str, session_id: str = "default", user_id: str = ""
) -> dict[str, Any]:
    """Navigate to a URL in the given browser session.

    The URL is screened first: only absolute http/https URLs on the standard
    port, with no credentials and a public (non loopback/private/link-local/
    reserved) host, are accepted. ``page.goto`` is never reached otherwise.

    Returns the page title and current URL.
    """
    try:
        target_url = normalize_public_http_url(url)
    except ValueError as exc:
        logger.warning("browser_navigate refused %r: %s", url, exc)
        return _result(success=False, error=f"Blocked URL: {exc}", url=url, session_id=session_id)
    try:
        safe_session_id = _normalize_session_id(session_id)
        pool_key = _browser_pool_key(safe_session_id, user_id)
    except ValueError as exc:
        return _result(success=False, error=str(exc), url=target_url, session_id=session_id)
    try:
        page = await _ensure_page(pool_key)
        response = await page.goto(target_url, wait_until="domcontentloaded")
        title = await page.title()
        current_url = page.url
        status = response.status if response else None
        return _result(
            success=True,
            title=title,
            url=current_url,
            status=status,
            session_id=safe_session_id,
        )
    except Exception as exc:
        logger.error("browser_navigate failed for %s: %s", target_url, exc)
        return _result(
            success=False, error=str(exc), url=target_url, session_id=safe_session_id
        )


async def browser_click(
    selector: str, session_id: str = "default", user_id: str = ""
) -> dict[str, Any]:
    """Click an element identified by a CSS selector."""
    try:
        safe_session_id = _normalize_session_id(session_id)
        page = await _ensure_page(_browser_pool_key(safe_session_id, user_id))
        await page.click(selector)
        return _result(success=True, selector=selector, session_id=safe_session_id)
    except Exception as exc:
        logger.error("browser_click failed for %s: %s", selector, exc)
        return _result(success=False, error=str(exc), selector=selector, session_id=session_id)


async def browser_fill(
    selector: str, text: str, session_id: str = "default", user_id: str = ""
) -> dict[str, Any]:
    """Fill a form field identified by a CSS selector."""
    try:
        safe_session_id = _normalize_session_id(session_id)
        page = await _ensure_page(_browser_pool_key(safe_session_id, user_id))
        await page.fill(selector, text)
        return _result(success=True, selector=selector, text=text, session_id=safe_session_id)
    except Exception as exc:
        logger.error("browser_fill failed for %s: %s", selector, exc)
        return _result(success=False, error=str(exc), selector=selector, session_id=session_id)


async def browser_extract_text(
    selector: str | None = None, session_id: str = "default", user_id: str = ""
) -> dict[str, Any]:
    """Extract text from the page or from a specific CSS selector."""
    try:
        safe_session_id = _normalize_session_id(session_id)
        page = await _ensure_page(_browser_pool_key(safe_session_id, user_id))
        if selector:
            elements = await page.query_selector_all(selector)
            texts = []
            for el in elements:
                text = await el.text_content()
                if text is not None:
                    texts.append(text.strip())
            return _result(
                success=True,
                selector=selector,
                texts=texts,
                count=len(texts),
                session_id=safe_session_id,
            )
        else:
            body = await page.query_selector("body")
            text = await body.text_content() if body else ""
            return _result(
                success=True,
                text=(text or "").strip(),
                session_id=safe_session_id,
            )
    except Exception as exc:
        logger.error("browser_extract_text failed: %s", exc)
        return _result(success=False, error=str(exc), selector=selector, session_id=session_id)


async def browser_screenshot(
    session_id: str = "default", full_page: bool = False, user_id: str = ""
) -> dict[str, Any]:
    """Take a screenshot and save it to data/screenshots/."""
    try:
        safe_session_id = _normalize_session_id(session_id)
        pool_key = _browser_pool_key(safe_session_id, user_id)
        page = await _ensure_page(pool_key)
        owner_key = pool_key.split("_", 1)[0]
        path = _screenshot_path(safe_session_id, owner_key)
        await page.screenshot(path=str(path), full_page=full_page)
        return _result(
            success=True, path=str(path), full_page=full_page, session_id=safe_session_id
        )
    except Exception as exc:
        logger.error("browser_screenshot failed: %s", exc)
        return _result(success=False, error=str(exc), session_id=session_id)


async def browser_get_links(session_id: str = "default", user_id: str = "") -> dict[str, Any]:
    """Return all unique links (href + text) on the current page."""
    try:
        safe_session_id = _normalize_session_id(session_id)
        page = await _ensure_page(_browser_pool_key(safe_session_id, user_id))
        links = await page.eval_on_selector_all(
            "a[href]",
            """elements => elements.map(el => ({
                href: el.href,
                text: (el.textContent || "").trim()
            }))""",
        )
        seen = set()
        unique = []
        for link in links:
            href = link.get("href", "")
            if href and href not in seen:
                seen.add(href)
                unique.append({"href": href, "text": link.get("text", "")})
        return _result(success=True, links=unique, count=len(unique), session_id=safe_session_id)
    except Exception as exc:
        logger.error("browser_get_links failed: %s", exc)
        return _result(success=False, error=str(exc), session_id=session_id)


async def browser_close(session_id: str = "default", user_id: str = "") -> dict[str, Any]:
    """Close the browser context for a session and remove it from the pool."""
    try:
        safe_session_id = _normalize_session_id(session_id)
        pool_key = _browser_pool_key(safe_session_id, user_id)
    except ValueError as exc:
        return _result(success=False, error=str(exc), session_id=session_id)
    session = _pool.pop(pool_key, None)
    if not session:
        return _result(
            success=True, message="Session not found, nothing to close", session_id=safe_session_id
        )

    errors = []
    try:
        await session["context"].close()
    except Exception as exc:
        errors.append(f"context close error: {exc}")
    try:
        await session["browser"].close()
    except Exception as exc:
        errors.append(f"browser close error: {exc}")
    try:
        await session["playwright"].stop()
    except Exception as exc:
        errors.append(f"playwright stop error: {exc}")

    if errors:
        logger.warning(
            "browser_close partial failure for %s: %s", safe_session_id, "; ".join(errors)
        )
        return _result(
            success=False, error="; ".join(errors), session_id=safe_session_id
        )

    logger.info("Browser session closed: %s", safe_session_id)
    return _result(success=True, message="Session closed", session_id=safe_session_id)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

register_tool(
    ToolSpec(
        name="browser_navigate",
        description=(
            "Navigate to a URL in a headless browser and return the page title and "
            "current URL. Only absolute http/https URLs on the standard port whose "
            "host is a public address are accepted; other schemes and private, "
            "loopback or link-local hosts are refused before the browser starts."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "maxLength": 2000,
                    "description": (
                        "Absolute URL to navigate to. http or https, standard port, "
                        "no credentials, public host required."
                    ),
                },
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "maxLength": _SESSION_ID_MAX_LENGTH,
                    "pattern": _SESSION_ID_SCHEMA_PATTERN,
                    "description": (
                        "Browser session identifier. 1-128 characters of letters, "
                        "digits, '.', '_' and '-', starting with a letter or digit. "
                        "Anything else is rejected: the value is used as a pool key "
                        "and as a screenshot filename."
                    ),
                },
            },
            "required": ["url"],
        },
        handler=browser_navigate,
    )
)

register_tool(
    ToolSpec(
        name="browser_click",
        description="Click an element on the current page using a CSS selector.",
        schema={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the element to click",
                },
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "maxLength": _SESSION_ID_MAX_LENGTH,
                    "pattern": _SESSION_ID_SCHEMA_PATTERN,
                    "description": (
                        "Browser session identifier. 1-128 characters of letters, "
                        "digits, '.', '_' and '-', starting with a letter or digit. "
                        "Anything else is rejected: the value is used as a pool key "
                        "and as a screenshot filename."
                    ),
                },
            },
            "required": ["selector"],
        },
        handler=browser_click,
    )
)

register_tool(
    ToolSpec(
        name="browser_fill",
        description="Fill a form field identified by a CSS selector with the given text.",
        schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of the input field"},
                "text": {"type": "string", "description": "Text to type into the field"},
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "maxLength": _SESSION_ID_MAX_LENGTH,
                    "pattern": _SESSION_ID_SCHEMA_PATTERN,
                    "description": (
                        "Browser session identifier. 1-128 characters of letters, "
                        "digits, '.', '_' and '-', starting with a letter or digit. "
                        "Anything else is rejected: the value is used as a pool key "
                        "and as a screenshot filename."
                    ),
                },
            },
            "required": ["selector", "text"],
        },
        handler=browser_fill,
    )
)

register_tool(
    ToolSpec(
        name="browser_extract_text",
        description="Extract text from the current page. If a CSS selector is provided, extracts text from matching elements only.",
        schema={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "Optional CSS selector to restrict extraction",
                },
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "maxLength": _SESSION_ID_MAX_LENGTH,
                    "pattern": _SESSION_ID_SCHEMA_PATTERN,
                    "description": (
                        "Browser session identifier. 1-128 characters of letters, "
                        "digits, '.', '_' and '-', starting with a letter or digit. "
                        "Anything else is rejected: the value is used as a pool key "
                        "and as a screenshot filename."
                    ),
                },
            },
            "required": [],
        },
        handler=browser_extract_text,
    )
)

register_tool(
    ToolSpec(
        name="browser_screenshot",
        description="Take a screenshot of the current page and save it to data/screenshots/. Returns the file path. The path is always inside that directory.",
        schema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "maxLength": _SESSION_ID_MAX_LENGTH,
                    "pattern": _SESSION_ID_SCHEMA_PATTERN,
                    "description": (
                        "Browser session identifier. 1-128 characters of letters, "
                        "digits, '.', '_' and '-', starting with a letter or digit. "
                        "Anything else is rejected: the value is used as a pool key "
                        "and as a screenshot filename."
                    ),
                },
                "full_page": {
                    "type": "boolean",
                    "default": False,
                    "description": "Capture the full scrollable page",
                },
            },
            "required": [],
        },
        handler=browser_screenshot,
    )
)

register_tool(
    ToolSpec(
        name="browser_get_links",
        description="Get all unique links (href and text) on the current page.",
        schema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "maxLength": _SESSION_ID_MAX_LENGTH,
                    "pattern": _SESSION_ID_SCHEMA_PATTERN,
                    "description": (
                        "Browser session identifier. 1-128 characters of letters, "
                        "digits, '.', '_' and '-', starting with a letter or digit. "
                        "Anything else is rejected: the value is used as a pool key "
                        "and as a screenshot filename."
                    ),
                },
            },
            "required": [],
        },
        handler=browser_get_links,
    )
)

register_tool(
    ToolSpec(
        name="browser_close",
        description="Close the browser context for a given session and free resources.",
        schema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "maxLength": _SESSION_ID_MAX_LENGTH,
                    "pattern": _SESSION_ID_SCHEMA_PATTERN,
                    "description": (
                        "Browser session identifier. 1-128 characters of letters, "
                        "digits, '.', '_' and '-', starting with a letter or digit. "
                        "Anything else is rejected: the value is used as a pool key "
                        "and as a screenshot filename."
                    ),
                },
            },
            "required": [],
        },
        handler=browser_close,
    )
)
