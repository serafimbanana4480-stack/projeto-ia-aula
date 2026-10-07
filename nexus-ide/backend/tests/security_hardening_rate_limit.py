"""P0-2 — HTTP rate limiting was configured but never wired.

The audit found three limiters, none connected: ``default_limits=[]`` with no
middleware, a second orphaned ``Limiter`` in ``orchestrator/limiter.py``, and a
``TenantManager`` that was never instantiated.  ``RATE_LIMIT_ENABLED=true`` and
``RATE_LIMIT_REQUESTS_PER_MINUTE=60`` were read by nothing.

These tests prove the limiter is actually connected and that a client over the
budget receives **429**, that the six pre-existing ``@limiter.limit`` decorators
now function, and that ``TenantManager`` is live.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from backend.core import disk_guard
from backend.middleware import rate_limit as rl
from backend.middleware.rate_limit_middleware import NexusRateLimitMiddleware
from backend.pipeline.scalability import TenantConfig, TenantManager


@pytest.fixture(autouse=True)
def _no_disk_guard(monkeypatch):
    monkeypatch.setattr(disk_guard, "require_disk_headroom", lambda *_a, **_k: None)
    yield


# ---------------------------------------------------------------------------
# 1. The limiter is actually attached to the application
# ---------------------------------------------------------------------------
class TestWiring:
    def test_app_state_limiter_is_the_shared_instance(self) -> None:
        from backend.orchestrator.main import app

        assert isinstance(app.state.limiter, Limiter)
        # The same object the route decorators captured at import time, or the
        # decorators would be decorating a different limiter than the one that
        # enforces.
        assert app.state.limiter is rl.limiter

    def test_middleware_is_installed(self) -> None:
        from backend.orchestrator.main import app

        installed = {
            getattr(m, "cls", None) for m in app.user_middleware
        }
        assert NexusRateLimitMiddleware in installed

    def test_rate_limit_exceeded_handler_registered(self) -> None:
        from backend.orchestrator.main import app

        assert RateLimitExceeded in app.exception_handlers

    def test_orphaned_limiter_module_re_exports_the_same_object(self) -> None:
        from backend.orchestrator import limiter as orchestrator_limiter

        assert orchestrator_limiter.limiter is rl.limiter

    def test_default_limit_comes_from_the_env(self, monkeypatch) -> None:
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
        monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "17")
        assert rl.default_limit() == "17/minute"

    def test_disabling_removes_only_the_default(self, monkeypatch) -> None:
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
        assert rl.is_enabled() is False
        assert rl.default_limit() is None
        # The limiter object still exists so decorators keep working.
        assert isinstance(rl.limiter, Limiter)

    def test_disabling_does_not_break_construction(self, monkeypatch) -> None:
        """Regression: ``RATE_LIMIT_ENABLED=false`` must not break the import.

        An empty default-limit list once produced ``in_memory_fallback=None``,
        and slowapi iterates that argument inside ``Limiter.__init__`` — so the
        documented "turn the limiter off" switch raised ``TypeError`` at import
        time and took the whole application down.
        """
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
        built = rl.build_limiter()
        assert built.enabled is True, "the limiter itself must stay installed"
        assert list(built._default_limits) == []
        assert isinstance(built._in_memory_fallback, list)
        assert rl.build_limiter(default_limits=["5/minute"])._in_memory_fallback

    def test_fallback_limits_mirror_the_defaults(self, monkeypatch) -> None:
        monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "9")
        built = rl.build_limiter()
        assert built._in_memory_fallback_enabled is True
        assert len(built._in_memory_fallback) == 1

    def test_storage_honours_redis_url(self, monkeypatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://cache.internal:6379/2")
        assert rl.storage_uri() == "redis://cache.internal:6379/2"
        # cache.internal does not resolve here, so build_limiter must downgrade
        # to memory rather than leaving a limiter whose storage fails on every
        # request (which would silently disable the limit).
        built = rl.build_limiter(default_limits=["1/minute"])
        assert built._storage_uri == "memory://"

    def test_storage_falls_back_to_memory(self, monkeypatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert rl.storage_uri() == "memory://"

    def test_unreachable_redis_does_not_disable_limiting(self, monkeypatch) -> None:
        """A configured-but-dead REDIS_URL must not turn the limiter into a no-op.

        ``.env`` ships ``REDIS_URL=redis://localhost:6379`` on machines with no
        Redis running.  If the limiter kept the dead backend, every request
        would raise inside the storage layer and — with a naive "log and
        continue" — the limit would silently never apply.
        """
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1")
        assert rl.storage_is_reachable("redis://127.0.0.1:1") is False
        built = rl.build_limiter(default_limits=["1/minute"])
        assert built._storage_uri == "memory://"

    def test_storage_ignores_a_non_redis_url(self, monkeypatch) -> None:
        monkeypatch.setenv("REDIS_URL", "postgresql://db/nexus")
        assert rl.storage_uri() == "memory://"

    def test_endpoint_index_sees_included_routers(self) -> None:
        """The global limit must resolve endpoints that live in a router.

        FastAPI 0.140 nests included routers, which is exactly what defeated
        slowapi's own middleware and made every request exempt.
        """
        from backend.orchestrator.main import app

        index = rl.endpoint_index_for(app)
        assert "/api/health" in index
        assert "/api/improvement/stats" in index
        assert len(index) > 100

    def test_resolve_endpoint_matches_templated_paths(self) -> None:
        from backend.orchestrator.main import app

        index = rl.endpoint_index_for(app)
        endpoint = rl.resolve_endpoint(index, "/api/sessions/abc123/history")
        assert endpoint is not None


# ---------------------------------------------------------------------------
# 2. A client over the budget gets 429
# ---------------------------------------------------------------------------
def _budgeted_app(limit: str = "3/minute") -> FastAPI:
    application = FastAPI()
    # memory:// so the counting assertions do not depend on a reachable Redis
    # (backend/tests/conftest.py points REDIS_URL at a non-existent host, and
    # slowapi then swaps route limits for its in-memory fallback set).
    application.state.limiter = rl.build_limiter(
        default_limits=[limit], storage_uri_override="memory://"
    )
    application.state.rate_limit_endpoint_index = {}
    application.state.rate_limit_routes_seen = -1
    from slowapi import _rate_limit_exceeded_handler

    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    application.add_middleware(NexusRateLimitMiddleware, limiter=application.state.limiter)

    @application.get("/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "1"}

    return application


class TestReturns429:
    def test_exceeding_the_limit_returns_429(self) -> None:
        client = TestClient(_budgeted_app("3/minute"))
        codes = [client.get("/ping").status_code for _ in range(6)]
        assert codes[:3] == [200, 200, 200]
        assert 429 in codes, codes
        assert codes[3:] == [429, 429, 429], codes

    def test_429_body_and_headers_are_useful(self) -> None:
        client = TestClient(_budgeted_app("1/minute"))
        assert client.get("/ping").status_code == 200
        response = client.get("/ping")
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.text
        assert response.headers.get("Retry-After")
        assert response.headers.get("X-RateLimit-Limit") == "1"

    def test_quota_headers_are_injected_on_success(self) -> None:
        client = TestClient(_budgeted_app("5/minute"))
        response = client.get("/ping")
        assert response.status_code == 200
        assert response.headers.get("X-RateLimit-Limit") == "5"
        assert response.headers.get("X-RateLimit-Remaining") == "4"

    def test_routes_with_their_own_decorator_are_not_double_counted(self) -> None:
        """A decorated route is limited by its decorator, not by the global one."""
        # The decorator and app.state.limiter must be the *same* object, which
        # is what attach_to_app() guarantees in the real application.
        application = _budgeted_app("2/minute")
        decorator_limiter = application.state.limiter

        @application.get("/own")
        @decorator_limiter.limit("1/minute")
        async def own(request: Request) -> dict[str, str]:
            return {"ok": "1"}

        client = TestClient(application)
        codes = [client.get("/own").status_code for _ in range(3)]
        # First passes the 1/minute route limit; the rest are 429 — proving the
        # decorator is live (the 2/minute global limit would have allowed two).
        assert codes[0] == 200
        assert codes[1] == 429 and codes[2] == 429


# ---------------------------------------------------------------------------
# 3. The six pre-existing decorators are live
# ---------------------------------------------------------------------------
class TestExistingDecorators:
    EXPECTED = {
        "backend.core.routes.improvement.get_stats": "60 per 1 minute",
        "backend.core.routes.improvement.list_proposals": "60 per 1 minute",
        "backend.core.routes.improvement.get_proposal": "60 per 1 minute",
        "backend.core.routes.improvement.apply_proposal": "30 per 1 minute",
        "backend.core.routes.improvement.reject_proposal": "30 per 1 minute",
        "backend.core.routes.improvement.run_now": "10 per 1 minute",
    }

    def test_all_six_decorators_registered_on_the_shared_limiter(self) -> None:
        import backend.core.routes.improvement  # noqa: F401  (registers them)
        import backend.orchestrator.main  # noqa: F401

        route_limits = rl.limiter._route_limits
        for name, limit in self.EXPECTED.items():
            assert name in route_limits, f"{name} has no limit registered"
            assert str(route_limits[name][0].limit) == limit

    def test_decorated_route_returns_429_when_exceeded(self) -> None:
        """End-to-end proof through the real app and the real 30/minute limit.

        The global limit is 60/minute (from ``.env``), so 33 requests cross the
        route's own 30/minute budget first — the 429 can only come from the
        ``@limiter.limit("30/minute")`` decorator on
        ``/api/improvement/proposals/{id}/apply``.
        """
        from backend.middleware.auth import create_access_token
        from backend.orchestrator.main import app

        token = create_access_token({"sub": "rl", "email": "rl@example.test"})
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
        codes = [
            client.post("/api/improvement/proposals/nope/apply").status_code
            for _ in range(33)
        ]
        last = client.post("/api/improvement/proposals/nope/apply")

        assert codes[:30] == [400] * 30, "route behaved unexpectedly before the limit"
        assert codes[30:] == [429, 429, 429]
        assert "Rate limit exceeded: 30 per 1 minute" in last.text

    def test_decorated_dict_endpoint_does_not_500(self) -> None:
        """Regression: slowapi's header injection 500s on dict-returning routes.

        Every improvement route returns a plain ``dict`` and declares no
        ``response: Response`` parameter, so the stock ``_inject_headers`` raised
        ``Exception("parameter 'response' must be an instance of
        starlette.responses.Response")`` and the request became a 500 the moment
        the limiter went live.  The limiter must degrade to a no-op instead.
        """
        from starlette.responses import JSONResponse

        limiter = rl.NexusLimiter(
            key_func=lambda: "k",
            default_limits=["1/minute"],
            headers_enabled=True,
            storage_uri="memory://",
        )
        # Non-Response: must be a no-op, not an exception.
        assert limiter._inject_headers(None, None) is None
        # A real Response still gets its headers.
        response = JSONResponse({"a": 1})
        item = next(iter(limiter._default_limits[0])).limit
        assert limiter._inject_headers(response, (item, ["k"])) is response
        assert response.headers.get("X-RateLimit-Limit") == "1"

    def test_dict_returning_decorated_route_answers_normally(self) -> None:
        """End-to-end: a decorated route returning a dict must not become a 500."""
        application = FastAPI()
        limiter = rl.build_limiter(default_limits=[], storage_uri_override="memory://")
        application.state.limiter = limiter
        application.state.rate_limit_endpoint_index = {}
        application.state.rate_limit_routes_seen = -1
        from slowapi import _rate_limit_exceeded_handler

        application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        application.add_middleware(NexusRateLimitMiddleware, limiter=limiter)

        @application.get("/dict")
        @limiter.limit("5/minute")
        async def as_dict(request: Request) -> dict[str, str]:
            return {"runs_total": "0"}

        client = TestClient(application)
        response = client.get("/dict")
        assert response.status_code == 200
        assert response.json() == {"runs_total": "0"}


# ---------------------------------------------------------------------------
# 4. TenantManager is no longer dead code
# ---------------------------------------------------------------------------
class TestTenantManager:
    def test_singleton_is_instantiated(self) -> None:
        rl.reset_tenant_manager()
        manager = rl.get_tenant_manager()
        assert isinstance(manager, TenantManager)
        assert rl.get_tenant_manager() is manager

    def test_default_tenant_is_registered(self) -> None:
        rl.reset_tenant_manager()
        manager = rl.get_tenant_manager()
        assert manager.get(rl.DEFAULT_TENANT_ID) is not None

    def test_tenant_limit_is_enforced(self) -> None:
        rl.reset_tenant_manager()
        manager = rl.get_tenant_manager()
        manager.register(
            TenantConfig(tenant_id="acme", name="acme", rate_limit_per_minute=2)
        )
        assert manager.check_rate_limit("acme") is True
        assert manager.check_rate_limit("acme") is True
        assert manager.check_rate_limit("acme") is False

    def test_unknown_tenant_is_blocked(self) -> None:
        rl.reset_tenant_manager()
        assert rl.get_tenant_manager().check_rate_limit("ghost") is False

    def test_helper_uses_the_default_tenant(self, monkeypatch) -> None:
        rl.reset_tenant_manager()
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
        monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "2")
        rl.reset_tenant_manager()
        results = [rl.check_tenant_rate_limit() for _ in range(4)]
        assert results == [True, True, False, False]
        assert rl.tenant_usage()["rate_limit_used"] == 2

    def test_helper_is_a_noop_when_disabled(self, monkeypatch) -> None:
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
        assert all(rl.check_tenant_rate_limit() for _ in range(100))
        rl.reset_tenant_manager()


# ---------------------------------------------------------------------------
# 5. The policy catalogue
# ---------------------------------------------------------------------------
class TestConfigCatalogue:
    def test_all_endpoint_classes_present(self) -> None:
        config = rl.get_rate_limit_config()
        for key in ("auth", "chat", "llm", "files", "terminal", "tests", "default"):
            assert key in config

    def test_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_RATE_LIMIT_AUTH", "2/minute")
        assert rl.get_rate_limit_config()["auth"] == "2/minute"

    def test_auth_is_stricter_than_default(self) -> None:
        config = rl.get_rate_limit_config()
        assert config["auth"] != config["default"]
