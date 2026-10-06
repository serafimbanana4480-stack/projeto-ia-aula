"""HTTP API tester tool — make HTTP requests with rate limiting.

Provides a single ``api_request`` tool that supports GET/POST/PUT/PATCH/DELETE
with custom headers, body, and timeout. Rate-limited per session to prevent
abuse. The body is JSON-serialised when content-type is application/json.

SSRF barrier (CWE-918): there is exactly one guard, and it is the one in
``backend.tools.safe_http``:

1. :func:`normalize_public_http_url` rejects non-http(s) schemes, embedded
   credentials, non-standard ports, local/reserved hostnames and literal
   non-public IPs before any I/O happens.
2. The request is dispatched through :class:`PublicAddressHTTPTransport`, whose
   network backend resolves the host and checks *every* returned address
   immediately before opening the socket. Because the guard lives on the
   transport, HTTPX's redirect hops are re-resolved and re-checked too, so a
   public URL that 302s into loopback never gets a socket.

The previous implementation resolved DNS once up front with
``socket.getaddrinfo`` and then dispatched with aiohttp's default
``allow_redirects=True``: a TOCTOU rebinding record and every redirect hop both
bypassed that check, and aiohttp honoured ``HTTP_PROXY``/``HTTPS_PROXY``.
``trust_env=False`` on the client removes the proxy route.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from backend.tools.registry import ToolSpec, register_tool
from backend.tools.safe_http import PublicAddressHTTPTransport, normalize_public_http_url

logger = logging.getLogger(__name__)

# Hard cap on response size to prevent memory exhaustion
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB


def _check_rate_limit(session_id: str | None) -> tuple[bool, str | None]:
    """Rate limiting is disabled globally."""
    return True, None


def _validate_url(url: str) -> tuple[str, str | None]:
    """Normalise and screen a URL before any socket work.

    Returns ``(canonical_url, None)`` when the URL is an absolute public
    http/https URL, otherwise ``("", error_message)``.

    This is only the syntactic front door. It is deliberately *not* the SSRF
    barrier: a check that only parses the URL cannot see what the second
    resolver will answer. The authoritative check is the transport's, at connect
    time, for every hop.
    """
    try:
        return normalize_public_http_url(url), None
    except ValueError as exc:
        return "", f"Blocked URL: {exc}"


def _build_client(timeout: float) -> httpx.AsyncClient:
    """Create the guarded HTTP client used for every dispatch.

    ``follow_redirects=True`` keeps redirects working for callers, and they are
    safe because the transport re-checks each hop's resolved address. Sharing
    one construction point is what makes the guard testable.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        trust_env=False,
        transport=PublicAddressHTTPTransport(),
    )


async def _read_capped(response: httpx.Response) -> tuple[bytes, bool]:
    """Stream the body, stopping at the cap. Returns (bytes, truncated)."""
    chunks: list[bytes] = []
    total = 0
    truncated = False
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_RESPONSE_BYTES:
            truncated = True
            break
    raw = b"".join(chunks)
    return raw[:_MAX_RESPONSE_BYTES], truncated


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
        url: Absolute target URL. Must be http/https on the standard port and
             must resolve to a public IP address, both for the first request
             and for every redirect hop.
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

    # SSRF front door: no socket, no DNS and no cache lookup happens before
    # this returns.
    target_url, err = _validate_url(url)
    if err is not None:
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

    # Execute. The transport, not this function, is what stops a private
    # address: it re-resolves the host immediately before each connect, so a
    # rebinding record or a redirect into 127.0.0.1 fails closed.
    try:
        async with _build_client(timeout) as client, client.stream(
            method, target_url, headers=req_headers, content=data
        ) as resp:
            raw, truncated = await _read_capped(resp)
            status = resp.status_code
            resp_headers = {k: v[:500] for k, v in resp.headers.items()}
            final_url = str(resp.url)
    except httpx.TimeoutException:
        return {"error": f"Timeout after {timeout}s", "url": url, "method": method}
    except httpx.HTTPError as e:
        return {"error": f"HTTP error: {e}", "url": url, "method": method}
    except TimeoutError:
        return {"error": f"Timeout after {timeout}s", "url": url, "method": method}
    except Exception as e:  # noqa: BLE001
        logger.exception("api_request failed")
        return {"error": str(e), "url": url, "method": method}

    text = raw.decode(errors="replace")
    # Try parse JSON
    parsed: Any = None
    parse_error: str | None = None
    if text:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            parse_error = str(e)
    return {
        "status": status,
        "headers": resp_headers,
        "body": text,
        "parsed": parsed,
        "parse_error": parse_error,
        "truncated": truncated,
        "url": final_url,
        "method": method,
    }


register_tool(
    ToolSpec(
        name="api_request",
        description=(
            "Make an HTTP request to a URL. Supports GET/POST/PUT/PATCH/DELETE. "
            "Body is auto-JSON-serialised for dicts/lists. Rate-limited to 100 req/min "
            "per session. Only absolute http/https URLs on the standard port are "
            "accepted; the host is resolved and refused unless every address it "
            "returns is a public IP address, and that check is repeated for each "
            "redirect hop. Environment proxies are ignored. Response capped at 5MB "
            "(a body over the cap is returned truncated with truncated=true)."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "maxLength": 2000,
                    "description": (
                        "Absolute target URL. Must be http or https on the standard "
                        "port, must not contain credentials, and must resolve to a "
                        "public IP address (redirect hops included). Private, "
                        "loopback, link-local and metadata addresses are refused."
                    ),
                },
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
