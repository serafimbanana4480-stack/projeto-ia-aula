"""HTTP API tester tool — make HTTP requests with rate limiting.

Provides a single ``api_request`` tool that supports GET/POST/PUT/PATCH/DELETE
with custom headers, body, and timeout. Rate-limited per session to prevent
abuse. The body is JSON-serialised when content-type is application/json.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
import time
from collections import defaultdict, deque
from typing import Any
from urllib.parse import urlparse

import aiohttp

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting: 100 req/min per session (sliding window)
# ---------------------------------------------------------------------------
_REQUEST_HISTORY: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT_MAX = 100
_RATE_LIMIT_WINDOW_S = 60.0
_RATE_LOCK = asyncio.Lock()

# ---------------------------------------------------------------------------
# SSRF protection: block requests to private/loopback IPs (unless explicitly allowed)
# ---------------------------------------------------------------------------
_ALLOW_PRIVATE_NETWORKS = False  # set to True in trusted environments

# Hard cap on response size to prevent memory exhaustion
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB


def _check_rate_limit(session_id: str | None) -> tuple[bool, str | None]:
    """Check if a session is rate-limited. Returns (allowed, error_msg)."""
    if not session_id:
        return True, None
    now = time.monotonic()
    history = _REQUEST_HISTORY[session_id]
    # Drop expired entries
    while history and (now - history[0]) > _RATE_LIMIT_WINDOW_S:
        history.popleft()
    if len(history) >= _RATE_LIMIT_MAX:
        return False, f"Rate limit exceeded ({_RATE_LIMIT_MAX} req/{_RATE_LIMIT_WINDOW_S}s)"
    history.append(now)
    return True, None


def _validate_url(url: str) -> tuple[bool, str | None]:
    """Validate URL and prevent SSRF to private networks.

    Returns (ok, error_msg).
    """
    try:
        parsed = urlparse(url)
    except Exception as e:  # noqa: BLE001
        return False, f"Invalid URL: {e}"

    if parsed.scheme not in ("http", "https"):
        return False, f"URL scheme must be http or https (got '{parsed.scheme}')"

    if not parsed.hostname:
        return False, "URL has no hostname"

    if _ALLOW_PRIVATE_NETWORKS:
        return True, None

    # Resolve hostname → IP to block private ranges
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        return False, f"Could not resolve hostname '{parsed.hostname}'"

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                return False, f"Refusing to call private/loopback IP {ip_str} (SSRF protection)"
        except ValueError:
            continue
    return True, None


async def api_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any = None,
    timeout: int = 30,
    session_id: str | None = None,
) -> dict:
    """Make an HTTP request.

    Args:
        url: Target URL (http or https only).
        method: HTTP method (GET/POST/PUT/PATCH/DELETE).
        headers: Optional headers dict.
        body: Optional request body. If content-type is application/json, will be
              JSON-serialised. Otherwise will be sent as text.
        timeout: Request timeout in seconds (default 30, max 120).
        session_id: Optional session ID for rate limiting.

    Returns:
        dict with status, headers, body (parsed if JSON), and metadata.
    """
    method = method.upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        return {"error": f"Unsupported HTTP method '{method}'"}

    timeout = min(max(timeout, 1), 120)  # clamp to [1, 120]

    # Rate limit check
    allowed, err = _check_rate_limit(session_id)
    if not allowed:
        return {"error": err}

    # SSRF protection
    ok, err = _validate_url(url)
    if not ok:
        return {"error": err}

    # Build headers
    req_headers = dict(headers or {})
    is_json = body is not None and (
        "application/json" in req_headers.get("Content-Type", "").lower()
        or "application/json" in req_headers.get("content-type", "").lower()
        or isinstance(body, (dict, list))
    )
    if is_json and "Content-Type" not in req_headers and "content-type" not in req_headers:
        req_headers["Content-Type"] = "application/json"

    # Build body
    data: str | None = None
    if body is not None:
        if isinstance(body, (dict, list)) or is_json:
            try:
                data = json.dumps(body)
            except (TypeError, ValueError) as e:
                return {"error": f"Cannot JSON-serialise body: {e}"}
        elif isinstance(body, str):
            data = body
        else:
            data = str(body)

    # Execute
    timeout_obj = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout_obj) as session, session.request(
            method=method, url=url, headers=req_headers, data=data
        ) as resp:
            # Read body with size cap
            raw = await resp.content.read(_MAX_RESPONSE_BYTES + 1)
            truncated = len(raw) > _MAX_RESPONSE_BYTES
            if truncated:
                raw = raw[:_MAX_RESPONSE_BYTES]
            text = raw.decode(errors="replace")
            # Try parse JSON
            parsed: Any = None
            parse_error: str | None = None
            if text:
                try:
                    parsed = json.loads(text)
                except (json.JSONDecodeError, ValueError) as e:
                    parse_error = str(e)
            # Truncate header values
            resp_headers = {k: v[:500] for k, v in resp.headers.items()}
            return {
                "status": resp.status,
                "headers": resp_headers,
                "body": text,
                "parsed": parsed,
                "parse_error": parse_error,
                "truncated": truncated,
                "url": str(resp.url),
                "method": method,
            }
    except TimeoutError:
        return {"error": f"Timeout after {timeout}s", "url": url, "method": method}
    except aiohttp.ClientError as e:
        return {"error": f"HTTP error: {e}", "url": url, "method": method}
    except Exception as e:  # noqa: BLE001
        logger.exception("api_request failed")
        return {"error": str(e), "url": url, "method": method}


register_tool(
    ToolSpec(
        name="api_request",
        description=(
            "Make an HTTP request to a URL. Supports GET/POST/PUT/PATCH/DELETE. "
            "Body is auto-JSON-serialised for dicts/lists. Rate-limited to 100 req/min "
            "per session. SSRF-protected (no private/loopback IPs). Response capped at 5MB."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL (http or https)"},
                "method": {"type": "string", "description": "HTTP method", "default": "GET", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]},
                "headers": {"type": "object", "description": "Custom headers", "additionalProperties": {"type": "string"}},
                "body": {"description": "Request body (auto-serialised to JSON if dict/list)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (1-120)", "default": 30},
                "session_id": {"type": "string", "description": "Session ID for rate limiting"},
            },
            "required": ["url"],
        },
        handler=api_request,
    )
)
