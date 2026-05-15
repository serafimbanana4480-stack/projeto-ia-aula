"""Tests for security middleware."""

from unittest.mock import MagicMock

import pytest

from backend.middleware.security import SecurityHeadersMiddleware


def _make_middleware():
    """Build a SecurityHeadersMiddleware wired to a mock ASGI app."""

    async def mock_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return SecurityHeadersMiddleware(mock_app)


class TestSecurityHeadersMiddleware:
    """Test security headers middleware."""

    @pytest.mark.asyncio
    async def test_adds_security_headers(self) -> None:
        """Test that middleware adds all security headers."""
        middleware = _make_middleware()

        captured_headers = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured_headers.extend(message["headers"])
            # Do NOT forward to real send in tests

        scope = {"type": "http"}
        await middleware(scope, None, capture_send)

        headers = dict(captured_headers)
        assert b"content-security-policy" in headers
        assert b"x-frame-options" in headers
        assert b"x-content-type-options" in headers
        assert b"x-xss-protection" in headers
        assert b"referrer-policy" in headers
        assert b"permissions-policy" in headers
        assert b"server" in headers

    @pytest.mark.asyncio
    async def test_csp_header_value(self) -> None:
        """Test that CSP header has correct value."""
        middleware = _make_middleware()

        captured_headers = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured_headers.extend(message["headers"])

        await middleware({"type": "http"}, None, capture_send)
        headers = dict(captured_headers)
        csp = headers[b"content-security-policy"].decode()
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_x_frame_options_deny(self) -> None:
        """Test that X-Frame-Options is set to DENY."""
        middleware = _make_middleware()

        captured_headers = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured_headers.extend(message["headers"])

        await middleware({"type": "http"}, None, capture_send)
        headers = dict(captured_headers)
        assert headers[b"x-frame-options"] == b"DENY"

    @pytest.mark.asyncio
    async def test_x_content_type_options_nosniff(self) -> None:
        """Test that X-Content-Type-Options is set to nosniff."""
        middleware = _make_middleware()

        captured_headers = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured_headers.extend(message["headers"])

        await middleware({"type": "http"}, None, capture_send)
        headers = dict(captured_headers)
        assert headers[b"x-content-type-options"] == b"nosniff"

    @pytest.mark.asyncio
    async def test_x_xss_protection(self) -> None:
        """Test that X-XSS-Protection is set correctly."""
        middleware = _make_middleware()

        captured_headers = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured_headers.extend(message["headers"])

        await middleware({"type": "http"}, None, capture_send)
        headers = dict(captured_headers)
        assert headers[b"x-xss-protection"] == b"1; mode=block"

    @pytest.mark.asyncio
    async def test_referrer_policy(self) -> None:
        """Test that Referrer-Policy is set correctly."""
        middleware = _make_middleware()

        captured_headers = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured_headers.extend(message["headers"])

        await middleware({"type": "http"}, None, capture_send)
        headers = dict(captured_headers)
        assert headers[b"referrer-policy"] == b"strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_permissions_policy(self) -> None:
        """Test that Permissions-Policy restricts features."""
        middleware = _make_middleware()

        captured_headers = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured_headers.extend(message["headers"])

        await middleware({"type": "http"}, None, capture_send)
        headers = dict(captured_headers)
        permissions = headers[b"permissions-policy"].decode()
        assert "geolocation=()" in permissions
        assert "microphone=()" in permissions
        assert "camera=()" in permissions
        assert "payment=()" in permissions

    @pytest.mark.asyncio
    async def test_server_header_customized(self) -> None:
        """Test that Server header is customized."""
        middleware = _make_middleware()

        captured_headers = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                captured_headers.extend(message["headers"])

        await middleware({"type": "http"}, None, capture_send)
        headers = dict(captured_headers)
        assert headers[b"server"] == b"NEXUS-IDE"