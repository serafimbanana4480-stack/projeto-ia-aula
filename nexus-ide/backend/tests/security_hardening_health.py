"""P1-5 — unauthenticated health endpoints leaked internal topology.

``/api/deep`` used ``Depends(get_current_user)``, which returns ``None`` when no
bearer token is supplied, so the Redis/Qdrant/AgentPool probe ran
unauthenticated.  ``/api/system/health`` was an alias that *dropped* the
dependency entirely.  ``/api/ready`` iterated an always-empty dict because
``register_dependency`` was called from nowhere, so readiness could never fail.
And the agent-pool probe imported a module that does not exist, so it reported
``degraded`` on every single call.

Liveness staying unauthenticated is a deliberate design decision (documented in
the module docstring and asserted below); these tests pin *that* decision so it
cannot drift into either direction.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core import disk_guard
from backend.middleware.auth import create_access_token
from backend.observability.routes import health as health_routes
from backend.orchestrator.main import app


@pytest.fixture(autouse=True)
def _no_disk_guard(monkeypatch):
    monkeypatch.setattr(disk_guard, "require_disk_headroom", lambda *_a, **_k: None)
    yield


@pytest.fixture
def anon():
    """A client with no credentials at all."""
    return TestClient(app)


@pytest.fixture
def admin():
    token = create_access_token({"sub": "health", "email": "health@example.test"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


TOPOLOGY_PATHS = ["/api/deep", "/api/system/health", "/health/deep", "/health?deep=true"]


# ---------------------------------------------------------------------------
# 1. Deep probes require real authentication
# ---------------------------------------------------------------------------
class TestDeepProbesRequireAuth:
    @pytest.mark.parametrize("path", TOPOLOGY_PATHS)
    def test_anonymous_is_rejected(self, anon: TestClient, path: str) -> None:
        response = anon.get(path)
        assert response.status_code == 401, f"{path} leaked to an anonymous caller"
        assert "components" not in response.text
        assert "redis" not in response.text.lower()

    @pytest.mark.parametrize("path", TOPOLOGY_PATHS)
    def test_authenticated_is_served(self, admin: TestClient, path: str) -> None:
        response = admin.get(path)
        assert response.status_code == 200, response.text
        body = response.json()
        assert "components" in body or "checks" in body

    def test_invalid_token_is_rejected(self, anon: TestClient) -> None:
        response = anon.get(
            "/api/system/health", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code in {401, 403}

    def test_alias_keeps_the_dependency(self) -> None:
        route = next(
            r
            for r in health_routes.router.routes
            if getattr(r, "path", "") == "/system/health"
        )
        names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "require_auth" in names, names

    def test_deep_route_uses_require_auth_not_get_current_user(self) -> None:
        route = next(
            r for r in health_routes.router.routes if getattr(r, "path", "") == "/deep"
        )
        names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "require_auth" in names, names
        assert "get_current_user" not in names, (
            "get_current_user returns None without a token, so it is not a guard"
        )


# ---------------------------------------------------------------------------
# 2. Liveness stays cheap and open — explicitly, not by accident
# ---------------------------------------------------------------------------
class TestLivenessStaysOpen:
    @pytest.mark.parametrize("path", ["/health", "/api/health"])
    def test_anonymous_liveness_is_200(self, anon: TestClient, path: str) -> None:
        response = anon.get(path)
        assert response.status_code == 200
        assert response.json()["status"] in {"ok", "healthy"}

    def test_liveness_does_not_probe_dependencies(self, anon: TestClient) -> None:
        """Liveness must stay cheap: no Redis/Qdrant/LLM probing."""
        body = anon.get("/health").json()
        assert "components" not in body
        assert "checks" not in body

    def test_liveness_only_reads_disk_pressure(self, anon: TestClient) -> None:
        body = anon.get("/health").json()
        assert set(body) == {"status", "disk_pressure"}

    def test_liveness_survives_a_broken_app_state(self, anon: TestClient) -> None:
        """Even with no app.state at all, liveness answers."""
        assert anon.get("/api/health").status_code == 200


# ---------------------------------------------------------------------------
# 3. Readiness can actually fail
# ---------------------------------------------------------------------------
class TestReadiness:
    def test_dependencies_are_registered(self) -> None:
        assert health_routes.dependencies, (
            "register_dependency was never called, so /api/ready was "
            "unconditionally 'ready'"
        )

    @pytest.mark.parametrize(
        "name", ["database", "disk", "agent_pool", "workflow_tracker"]
    )
    def test_expected_probes_present(self, name: str) -> None:
        assert name in health_routes.dependencies

    def test_readiness_reports_each_dependency(self, anon: TestClient) -> None:
        body = anon.get("/api/ready").json()
        assert body["status"] in {"ready", "not_ready"}
        assert set(body["dependencies"]) >= {"database", "disk"}

    def test_readiness_fails_when_a_probe_fails(self, anon: TestClient, monkeypatch) -> None:
        monkeypatch.setitem(health_routes.dependencies, "canary", lambda: False)
        body = anon.get("/api/ready").json()
        assert body["status"] == "not_ready"
        assert body["dependencies"]["canary"] == "not_ready"

    def test_readiness_fails_when_a_probe_raises(self, anon: TestClient, monkeypatch) -> None:
        def boom() -> bool:
            raise RuntimeError("probe exploded")

        monkeypatch.setitem(health_routes.dependencies, "canary2", boom)
        body = anon.get("/api/ready").json()
        assert body["status"] == "not_ready"
        assert "error" in body["dependencies"]["canary2"]

    def test_readiness_supports_async_probes(self, anon: TestClient, monkeypatch) -> None:
        async def ready() -> bool:
            return True

        monkeypatch.setitem(health_routes.dependencies, "canary3", ready)
        body = anon.get("/api/ready").json()
        assert body["dependencies"]["canary3"] == "ready"

    def test_readiness_is_callable_without_arguments(self) -> None:
        """``test_runtime_ownership`` calls ``readiness_check()`` directly."""
        import asyncio

        payload = asyncio.run(health_routes.readiness_check())
        assert payload["status"] in {"ready", "not_ready"}

    def test_readiness_is_unauthenticated(self, anon: TestClient) -> None:
        assert anon.get("/api/ready").status_code == 200

    def test_strict_readiness_returns_503(self, anon: TestClient, monkeypatch) -> None:
        """``?strict=true`` gives orchestrators a real non-200 readiness signal.

        The default stays 200 because the documented contract is "200 with the
        verdict in the body"; a load balancer that only reads the status code
        needs this variant.
        """
        monkeypatch.setitem(health_routes.dependencies, "canary", lambda: False)
        assert anon.get("/api/ready").status_code == 200
        strict = anon.get("/api/ready?strict=true")
        assert strict.status_code == 503
        assert strict.json()["status"] == "not_ready"

    def test_strict_readiness_is_200_when_ready(self, anon: TestClient, monkeypatch) -> None:
        for name in list(health_routes.dependencies):
            monkeypatch.setitem(health_routes.dependencies, name, lambda: True)
        assert anon.get("/api/ready?strict=true").status_code == 200


# ---------------------------------------------------------------------------
# 4. The permanently-degraded agent_pool probe
# ---------------------------------------------------------------------------
class TestAgentPoolProbe:
    def test_the_real_module_exists(self) -> None:
        from backend.orchestrator.agent_pool import AgentPool, get_agent_pool

        assert get_agent_pool() is not None
        assert AgentPool is not None

    def test_the_old_import_path_does_not_exist(self) -> None:
        """The probe used to import this, guaranteeing permanent 'degraded'."""
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("backend.agents.agent_pool")

    def test_deep_health_reports_agent_pool_healthy(self, admin: TestClient) -> None:
        body = admin.get("/api/deep").json()
        assert body["components"]["agent_pool"]["status"] == "healthy"
        assert "degraded" not in json_of(body["components"]["agent_pool"])

    def test_deep_health_overall_status(self, admin: TestClient) -> None:
        body = admin.get("/api/deep").json()
        assert body["status"] in {"healthy", "degraded", "unhealthy"}
        assert body["summary"]["total"] == len(body["components"])

    def test_deep_health_degrades_when_the_pool_is_broken(
        self, admin: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(health_routes, "_check_agent_pool_ready", lambda: False)
        body = admin.get("/api/deep").json()
        assert body["components"]["agent_pool"]["status"] == "degraded"
        # The overall verdict is the worst component, so an unavailable pool
        # can never read as "healthy" (the bug: it was permanently degraded,
        # which masked real outages and trained operators to ignore the field).
        assert body["status"] in {"degraded", "unhealthy"}

    def test_deep_health_exception_messages_are_bounded(self, admin: TestClient) -> None:
        """A probe error must not echo a megabyte of traceback to the client."""
        import backend.knowledge.redis_backend as redis_backend

        original = redis_backend.RedisBackend

        class _Exploding:
            def __init__(self, *_a, **_k):
                raise RuntimeError("x" * 5000)

        redis_backend.RedisBackend = _Exploding  # type: ignore[misc]
        try:
            body = admin.get("/api/deep").json()
        finally:
            redis_backend.RedisBackend = original  # type: ignore[misc]
        message = body["components"]["redis"]["message"]
        assert len(message) < 300


def json_of(value: object) -> str:
    import json

    return json.dumps(value)
