"""Tests for security middleware."""

from types import SimpleNamespace

import httpx
import pytest

from backend.middleware import security as security_module
from backend.middleware.security import SecurityHeadersMiddleware


def _make_app():
    """Build a minimal ASGI app wrapped by SecurityHeadersMiddleware."""

    async def mock_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return SecurityHeadersMiddleware(mock_app)


def _settings(**overrides):
    """Build a fake settings object with sensible defaults for tests."""
    base = dict(
        environment="development",
        require_https=False,
        csp_enabled=True,
        csp_policy="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def patch_settings(monkeypatch):
    """Patch ``get_settings`` used by the middleware; returns a setter callable."""

    def _apply(**overrides):
        monkeypatch.setattr(security_module, "get_settings", lambda: _settings(**overrides))

    return _apply


class TestSecurityHeadersMiddleware:
    """Test security headers middleware via httpx ASGI transport (no network)."""

    @pytest.mark.asyncio
    async def test_adds_security_headers(self, patch_settings) -> None:
        """Middleware adds all security headers."""
        patch_settings()
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        assert resp.status_code == 200
        assert "content-security-policy" in resp.headers
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-xss-protection"] == "1; mode=block"
        assert "referrer-policy" in resp.headers
        assert "permissions-policy" in resp.headers
        assert resp.headers["server"] == "NEXUS-IDE"

    @pytest.mark.asyncio
    async def test_csp_default_directives(self, patch_settings) -> None:
        """Default CSP contains all expected directives for the NEXUS stack."""
        patch_settings()
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        csp = resp.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self' 'unsafe-eval' 'unsafe-inline'" in csp
        assert "style-src 'self' 'unsafe-inline'" in csp
        assert "img-src 'self' data: blob:" in csp
        assert "font-src 'self' data:" in csp
        assert "connect-src 'self'" in csp
        assert "worker-src 'self' blob:" in csp
        assert "frame-ancestors 'none'" in csp
        assert "base-uri 'self'" in csp
        assert "object-src 'none'" in csp

    @pytest.mark.asyncio
    async def test_csp_disabled_omits_header(self, patch_settings) -> None:
        """CSP_ENABLED=false omits the Content-Security-Policy header."""
        patch_settings(csp_enabled=False)
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        assert "content-security-policy" not in resp.headers
        # Other headers are still present.
        assert resp.headers["x-frame-options"] == "DENY"

    @pytest.mark.asyncio
    async def test_csp_policy_override(self, patch_settings) -> None:
        """CSP_POLICY env var overrides the default CSP verbatim."""
        custom = "default-src 'none'; script-src 'self'"
        patch_settings(csp_policy=custom)
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        csp = resp.headers["content-security-policy"]
        assert csp.startswith(custom)
        assert "worker-src" not in csp

    @pytest.mark.asyncio
    async def test_csp_production_adds_upgrade(self, patch_settings) -> None:
        """In production, upgrade-insecure-requests is appended."""
        patch_settings(environment="production")
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        csp = resp.headers["content-security-policy"]
        assert "upgrade-insecure-requests" in csp

    @pytest.mark.asyncio
    async def test_x_frame_options_deny(self, patch_settings) -> None:
        """X-Frame-Options is set to DENY (legacy browsers)."""
        patch_settings()
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        assert resp.headers["x-frame-options"] == "DENY"

    @pytest.mark.asyncio
    async def test_x_content_type_options_nosniff(self, patch_settings) -> None:
        """X-Content-Type-Options is set to nosniff."""
        patch_settings()
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        assert resp.headers["x-content-type-options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_referrer_policy(self, patch_settings) -> None:
        """Referrer-Policy is set correctly."""
        patch_settings()
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_permissions_policy(self, patch_settings) -> None:
        """Permissions-Policy restricts features."""
        patch_settings()
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        permissions = resp.headers["permissions-policy"]
        assert "geolocation=()" in permissions
        assert "microphone=()" in permissions
        assert "camera=()" in permissions
        assert "payment=()" in permissions

    @pytest.mark.asyncio
    async def test_server_header_customized(self, patch_settings) -> None:
        """Server header is customized."""
        patch_settings()
        app = _make_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            resp = await client.get("http://testserver/")

        assert resp.headers["server"] == "NEXUS-IDE"
