"""Security headers middleware for NEXUS IDE."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders

from backend.config.settings import get_settings

# Default Content-Security-Policy used when ``CSP_POLICY`` is not set and
# ``CSP_ENABLED`` is true (default).
#
# Pragmatic production CSP tuned for the NEXUS IDE frontend stack:
#   - Next.js 15 (hydration injects inline scripts/styles)
#   - Monaco editor (web workers spawned from blob URLs + eval-based AMD loader)
#   - Tailwind (inline styles) / recharts / xterm
#
# ``'unsafe-eval'`` and ``'unsafe-inline'`` are required for Monaco/Next to
# function. In a stricter production setup these would be replaced by
# per-request nonces (``'nonce-<random>'``) generated server-side and applied
# to whitelisted <script>/<style> tags. That is documented as a follow-up; the
# current policy is intentionally permissive-but-bounded.
#
# Note on ``frame-ancestors 'none'`` vs ``X-Frame-Options: DENY``:
#   In modern browsers CSP ``frame-ancestors`` takes precedence and
#   ``X-Frame-Options`` is ignored when both are present. We keep
#   ``X-Frame-Options: DENY`` purely for legacy browsers (old IE / old
#   Safari) that do not implement CSP frame-ancestors.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


class SecurityHeadersMiddleware:
    """ASGI middleware to add security headers to all responses.

    Adds headers for:
    - Content Security Policy (CSP) — configurable via ``CSP_ENABLED`` / ``CSP_POLICY``
    - X-Frame-Options
    - X-Content-Type-Options
    - X-XSS-Protection
    - Strict-Transport-Security (production only)
    - Referrer-Policy
    - Permissions-Policy
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)

                settings = get_settings()
                is_prod = getattr(settings, "environment", "development") == "production"

                # Content Security Policy — only apply to HTML/document responses.
                # API responses do not render documents, so CSP there is unnecessary
                # and can interfere with the frontend's own CSP via browser
                # response-header inheritance in some engines.
                csp_enabled = bool(getattr(settings, "csp_enabled", True))
                if csp_enabled:
                    accept_header = ""
                    for key, value in scope.get("headers", []):
                        if key.lower() == b"accept":
                            accept_header = value.decode("latin-1", errors="ignore")
                            break
                    # Browsers send ``text/html`` for document navigations;
                    # lightweight ASGI clients (and the health/root smoke
                    # probes) commonly send ``*/*``.  Treat the wildcard as
                    # document-compatible while still avoiding CSP on callers
                    # that explicitly request another representation.
                    is_html = not accept_header or "text/html" in accept_header or "*/*" in accept_header
                    if is_html:
                        csp_policy = getattr(settings, "csp_policy", "") or ""
                        csp = csp_policy.strip() if csp_policy.strip() else DEFAULT_CSP
                        if is_prod:
                            csp = csp + "; upgrade-insecure-requests"
                        headers["Content-Security-Policy"] = csp

                # X-Frame-Options - Prevent clickjacking (legacy browsers).
                # CSP frame-ancestors 'none' takes precedence in modern browsers.
                headers["X-Frame-Options"] = "DENY"

                # X-Content-Type-Options - Prevent MIME type sniffing
                headers["X-Content-Type-Options"] = "nosniff"

                # X-XSS-Protection - Enable XSS filter
                headers["X-XSS-Protection"] = "1; mode=block"

                # Strict-Transport-Security - Force HTTPS in production
                if getattr(settings, "require_https", False) or is_prod:
                    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

                # Referrer-Policy - Control referrer information
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

                # Permissions-Policy - Restrict browser features
                permissions_policy = (
                    "geolocation=(), "
                    "microphone=(), "
                    "camera=(), "
                    "payment=(), "
                    "usb=(), "
                    "magnetometer=(), "
                    "gyroscope=(), "
                    "accelerometer=()"
                )
                headers["Permissions-Policy"] = permissions_policy

                # Remove server information
                headers["Server"] = "NEXUS-IDE"

            await send(message)

        await self.app(scope, receive, send_with_headers)
