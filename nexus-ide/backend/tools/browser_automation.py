"""Browser automation tool using Playwright async API.

Maintains a simple context pool keyed by session_id so multiple
conversations can drive independent browser sessions.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, BrowserContext, Page

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30_000  # 30 seconds in ms
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# In-memory pool: session_id -> {"context": BrowserContext, "page": Page, "playwright": Playwright, "browser": Browser}
_pool: dict[str, dict[str, Any]] = {}


def _screenshot_dir() -> Path:
    path = Path(__file__).resolve().parent.parent.parent / "data" / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _get_or_create_session(session_id: str) -> dict[str, Any]:
    """Return an existing session or launch a new headless browser context."""
    if session_id in _pool:
        return _pool[session_id]

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(user_agent=_USER_AGENT)
    page = await context.new_page()
    await page.set_default_timeout(_DEFAULT_TIMEOUT)

    session = {
        "playwright": pw,
        "browser": browser,
        "context": context,
        "page": page,
    }
    _pool[session_id] = session
    logger.info("Browser session created: %s", session_id)
    return session


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


async def browser_navigate(url: str, session_id: str = "default") -> dict[str, Any]:
    """Navigate to a URL in the given browser session.

    Returns the page title and current URL.
    """
    try:
        page = await _ensure_page(session_id)
        response = await page.goto(url, wait_until="domcontentloaded")
        title = await page.title()
        current_url = page.url
        status = response.status if response else None
        return _result(
            success=True,
            title=title,
            url=current_url,
            status=status,
            session_id=session_id,
        )
    except Exception as exc:
        logger.error("browser_navigate failed for %s: %s", url, exc)
        return _result(success=False, error=str(exc), url=url, session_id=session_id)


async def browser_click(selector: str, session_id: str = "default") -> dict[str, Any]:
    """Click an element identified by a CSS selector."""
    try:
        page = await _ensure_page(session_id)
        await page.click(selector)
        return _result(success=True, selector=selector, session_id=session_id)
    except Exception as exc:
        logger.error("browser_click failed for %s: %s", selector, exc)
        return _result(success=False, error=str(exc), selector=selector, session_id=session_id)


async def browser_fill(selector: str, text: str, session_id: str = "default") -> dict[str, Any]:
    """Fill a form field identified by a CSS selector."""
    try:
        page = await _ensure_page(session_id)
        await page.fill(selector, text)
        return _result(success=True, selector=selector, text=text, session_id=session_id)
    except Exception as exc:
        logger.error("browser_fill failed for %s: %s", selector, exc)
        return _result(success=False, error=str(exc), selector=selector, session_id=session_id)


async def browser_extract_text(selector: str | None = None, session_id: str = "default") -> dict[str, Any]:
    """Extract text from the page or from a specific CSS selector."""
    try:
        page = await _ensure_page(session_id)
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
                session_id=session_id,
            )
        else:
            body = await page.query_selector("body")
            text = await body.text_content() if body else ""
            return _result(
                success=True,
                text=(text or "").strip(),
                session_id=session_id,
            )
    except Exception as exc:
        logger.error("browser_extract_text failed: %s", exc)
        return _result(success=False, error=str(exc), selector=selector, session_id=session_id)


async def browser_screenshot(session_id: str = "default", full_page: bool = False) -> dict[str, Any]:
    """Take a screenshot and save it to data/screenshots/."""
    try:
        page = await _ensure_page(session_id)
        filename = f"screenshot_{session_id}_{int(time.time())}.png"
        path = _screenshot_dir() / filename
        await page.screenshot(path=str(path), full_page=full_page)
        return _result(success=True, path=str(path), full_page=full_page, session_id=session_id)
    except Exception as exc:
        logger.error("browser_screenshot failed: %s", exc)
        return _result(success=False, error=str(exc), session_id=session_id)


async def browser_get_links(session_id: str = "default") -> dict[str, Any]:
    """Return all unique links (href + text) on the current page."""
    try:
        page = await _ensure_page(session_id)
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
        return _result(success=True, links=unique, count=len(unique), session_id=session_id)
    except Exception as exc:
        logger.error("browser_get_links failed: %s", exc)
        return _result(success=False, error=str(exc), session_id=session_id)


async def browser_close(session_id: str = "default") -> dict[str, Any]:
    """Close the browser context for a session and remove it from the pool."""
    session = _pool.pop(session_id, None)
    if not session:
        return _result(success=True, message="Session not found, nothing to close", session_id=session_id)

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
        logger.warning("browser_close partial failure for %s: %s", session_id, "; ".join(errors))
        return _result(success=False, error="; ".join(errors), session_id=session_id)

    logger.info("Browser session closed: %s", session_id)
    return _result(success=True, message="Session closed", session_id=session_id)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

register_tool(
    ToolSpec(
        name="browser_navigate",
        description="Navigate to a URL in a headless browser and return the page title and current URL.",
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
                "session_id": {"type": "string", "default": "default", "description": "Browser session identifier"},
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
                "selector": {"type": "string", "description": "CSS selector of the element to click"},
                "session_id": {"type": "string", "default": "default", "description": "Browser session identifier"},
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
                "session_id": {"type": "string", "default": "default", "description": "Browser session identifier"},
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
                "selector": {"type": "string", "description": "Optional CSS selector to restrict extraction"},
                "session_id": {"type": "string", "default": "default", "description": "Browser session identifier"},
            },
            "required": [],
        },
        handler=browser_extract_text,
    )
)

register_tool(
    ToolSpec(
        name="browser_screenshot",
        description="Take a screenshot of the current page and save it to data/screenshots/. Returns the file path.",
        schema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "default": "default", "description": "Browser session identifier"},
                "full_page": {"type": "boolean", "default": False, "description": "Capture the full scrollable page"},
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
                "session_id": {"type": "string", "default": "default", "description": "Browser session identifier"},
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
                "session_id": {"type": "string", "default": "default", "description": "Browser session identifier"},
            },
            "required": [],
        },
        handler=browser_close,
    )
)
