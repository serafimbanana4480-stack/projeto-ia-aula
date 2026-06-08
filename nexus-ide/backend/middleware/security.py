"""Security headers middleware for NEXUS IDE."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders

from backend.config.settings import get_settings


class SecurityHeadersMiddleware:
    """ASGI middleware to add security headers to all responses.

    Adds headers for:
    - Content Security Policy (CSP)
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

                # Content Security Policy - Restricts sources of content
                settings = get_settings()
                is_prod = getattr(settings, "environment", "development") == "production"

                # In production we drop 'unsafe-eval' and tighten connect-src.
                # 'unsafe-inline' is kept because Next.js hydration requires it.
                script_src = "script-src 'self' 'unsafe-inline'" + ("" if is_prod else " 'unsafe-eval'")
                connect_src = (
                    "connect-src 'self' ws: wss:"
                    if is_prod
                    else "connect-src 'self' http://localhost:* ws://localhost:* ws: wss:"
                )
                csp_parts = [
                    "default-src 'self'",
                    script_src,
                    "style-src 'self' 'unsafe-inline'",
                    "img-src 'self' data: https:",
                    "font-src 'self' data:",
                    connect_src,
                    "frame-ancestors 'none'",
                    "base-uri 'self'",
                    "form-action 'self'",
                    "object-src 'none'",
                ]
                if is_prod:
                    csp_parts.append("upgrade-insecure-requests")
                headers["Content-Security-Policy"] = "; ".join(csp_parts) + ";"

                # X-Frame-Options - Prevent clickjacking
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
