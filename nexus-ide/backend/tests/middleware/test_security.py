"""Tests for security middleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request, Response

from backend.middleware.security import SecurityHeadersMiddleware


class TestSecurityHeadersMiddleware:
    """Test security headers middleware."""

    @pytest.mark.asyncio
    async def test_adds_security_headers(self) -> None:
        """Test that middleware adds all security headers."""
        middleware = SecurityHeadersMiddleware()

        # Create mock request and response
        request = MagicMock(spec=Request)
        response = MagicMock(spec=Response)
        response.headers = {}

        # Mock call_next
        async def call_next(req: Request) -> Response:
            return response

        # Call middleware
        result = await middleware(request, call_next)

        # Verify headers were added
        assert "Content-Security-Policy" in result.headers
        assert "X-Frame-Options" in result.headers
        assert "X-Content-Type-Options" in result.headers
        assert "X-XSS-Protection" in result.headers
        assert "Referrer-Policy" in result.headers
        assert "Permissions-Policy" in result.headers
        assert "Server" in result.headers

    @pytest.mark.asyncio
    async def test_csp_header_value(self) -> None:
        """Test that CSP header has correct value."""
        middleware = SecurityHeadersMiddleware()

        request = MagicMock(spec=Request)
        response = MagicMock(spec=Response)
        response.headers = {}

        async def call_next(req: Request) -> Response:
            return response

        result = await middleware(request, call_next)

        csp = result.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_x_frame_options_deny(self) -> None:
        """Test that X-Frame-Options is set to DENY."""
        middleware = SecurityHeadersMiddleware()

        request = MagicMock(spec=Request)
        response = MagicMock(spec=Response)
        response.headers = {}

        async def call_next(req: Request) -> Response:
            return response

        result = await middleware(request, call_next)

        assert result.headers["X-Frame-Options"] == "DENY"

    @pytest.mark.asyncio
    async def test_x_content_type_options_nosniff(self) -> None:
        """Test that X-Content-Type-Options is set to nosniff."""
        middleware = SecurityHeadersMiddleware()

        request = MagicMock(spec=Request)
        response = MagicMock(spec=Response)
        response.headers = {}

        async def call_next(req: Request) -> Response:
            return response

        result = await middleware(request, call_next)

        assert result.headers["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_x_xss_protection(self) -> None:
        """Test that X-XSS-Protection is set correctly."""
        middleware = SecurityHeadersMiddleware()

        request = MagicMock(spec=Request)
        response = MagicMock(spec=Response)
        response.headers = {}

        async def call_next(req: Request) -> Response:
            return response

        result = await middleware(request, call_next)

        assert result.headers["X-XSS-Protection"] == "1; mode=block"

    @pytest.mark.asyncio
    async def test_referrer_policy(self) -> None:
        """Test that Referrer-Policy is set correctly."""
        middleware = SecurityHeadersMiddleware()

        request = MagicMock(spec=Request)
        response = MagicMock(spec=Response)
        response.headers = {}

        async def call_next(req: Request) -> Response:
            return response

        result = await middleware(request, call_next)

        assert (
            result.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        )

    @pytest.mark.asyncio
    async def test_permissions_policy(self) -> None:
        """Test that Permissions-Policy restricts features."""
        middleware = SecurityHeadersMiddleware()

        request = MagicMock(spec=Request)
        response = MagicMock(spec=Response)
        response.headers = {}

        async def call_next(req: Request) -> Response:
            return response

        result = await middleware(request, call_next)

        permissions = result.headers["Permissions-Policy"]
        assert "geolocation=()" in permissions
        assert "microphone=()" in permissions
        assert "camera=()" in permissions
        assert "payment=()" in permissions

    @pytest.mark.asyncio
    async def test_server_header_customized(self) -> None:
        """Test that Server header is customized."""
        middleware = SecurityHeadersMiddleware()

        request = MagicMock(spec=Request)
        response = MagicMock(spec=Response)
        response.headers = {}

        async def call_next(req: Request) -> Response:
            return response

        result = await middleware(request, call_next)

        assert result.headers["Server"] == "NEXUS-IDE"