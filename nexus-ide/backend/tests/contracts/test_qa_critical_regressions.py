"""Regression contracts for the four CRITICAL findings of the QA audit.

Each test pins the *behaviour* that broke, not the implementation that fixed
it, so a future refactor is free to change the mechanism but not the promise:

C1  the catalog must not silently expire the chat ~10 min after boot
C2  saving Settings must never leave the chat with an empty catalog
C3  a full disk must not produce an unbootable backend in development
C4  a blocked tool must be reported as blocked, and the block must be fixable
"""

from __future__ import annotations

import inspect
import time
from types import SimpleNamespace

import pytest

from backend.llm import model_catalog
from backend.llm.free_policy import ProviderUnavailableError
from backend.llm.openrouter_provider import OpenRouterProvider


def _catalog_entry(validated_at: float) -> dict:
    return {
        "id": "openrouter/free",
        "provider": "openrouter",
        "input_price_per_1m": 0,
        "output_price_per_1m": 0,
        "quota_available": True,
        "validated_at": validated_at,
        "context_window": 128_000,
        "capabilities": ["tools", "json"],
        "latency_ms": 900,
    }


class TestC1CatalogExpiry:
    """The in-memory catalog TTL used to hard-fail every request after 600s."""

    def test_fresh_catalog_validates(self) -> None:
        provider = OpenRouterProvider(
            free_only=True, catalog=[_catalog_entry(time.time())]
        )
        assert provider.validate_model("openrouter/free") == "openrouter/free"

    def test_stale_catalog_still_serves_and_schedules_refresh(self) -> None:
        """A stale entry is a refresh trigger, not an outage."""
        provider = OpenRouterProvider(
            free_only=True,
            catalog=[_catalog_entry(time.time() - 10_000)],
            validation_ttl_seconds=600,
        )
        assert provider.validate_model("openrouter/free") == "openrouter/free"
        assert "stale" in provider.eligibility_reason

    def test_unknown_model_still_refuses(self) -> None:
        provider = OpenRouterProvider(free_only=True, catalog=[])
        with pytest.raises(ProviderUnavailableError):
            provider.validate_model("openrouter/free")

    def test_background_refresh_worker_exists(self) -> None:
        for name in (
            "start_catalog_refresh_worker",
            "stop_catalog_refresh_worker",
            "schedule_provider_catalog_refresh",
            "refresh_provider_catalog",
        ):
            assert callable(getattr(model_catalog, name)), name


class TestC2SettingsInvalidateOrder:
    """PUT /api/settings wiped the disk cache before rebuilding the client."""

    def test_source_never_invalidates_before_rebuild(self) -> None:
        from backend.orchestrator.routes import settings as settings_route

        source = inspect.getsource(settings_route.update_settings)
        invalidate = source.find("invalidate_cache")
        rebuild = source.find("create_llm_client")
        assert rebuild != -1, "settings update must rebuild the LLM client"
        if invalidate != -1:
            assert invalidate > rebuild, (
                "cache invalidation must not run before the client rebuild — "
                "that is exactly what emptied the catalog on save"
            )

    def test_successful_save_schedules_a_catalog_refresh(self) -> None:
        from backend.orchestrator.routes import settings as settings_route

        source = inspect.getsource(settings_route.update_settings)
        assert "schedule_provider_catalog_refresh" in source

    @pytest.mark.asyncio
    async def test_masked_secret_cannot_replace_environment_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.llm import factory
        from backend.llm import model_catalog
        from backend.orchestrator.routes import settings as settings_route

        saved: dict[str, str] = {}
        created: dict[str, str] = {}

        class _Client:
            async def aclose(self) -> None:
                return None

        monkeypatch.setattr(settings_route, "_load_runtime_settings", lambda: {})
        monkeypatch.setattr(settings_route, "_save_runtime_settings", saved.update)
        monkeypatch.setattr(
            settings_route,
            "get_settings",
            lambda: SimpleNamespace(openrouter_api_key="real-env-secret"),
        )

        def build(**values):
            created.update({key: str(value) for key, value in values.items()})
            return _Client()

        monkeypatch.setattr(factory, "create_llm_client", build)
        monkeypatch.setattr(model_catalog, "schedule_provider_catalog_refresh", lambda *_: None)

        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(llm_client=object()))
        )
        result = await settings_route.update_settings(
            settings_route.SettingsUpdate(
                settings={"openrouter_api_key": "real****cret"}
            ),
            request,
            _user={"id": "test"},
        )

        assert result["status"] == "saved"
        assert "openrouter_api_key" not in saved
        assert "openrouter_api_key" not in created


class TestC3DegradedStartup:
    """A 96%-full disk made the backend refuse to boot at all."""

    def test_env_opt_in_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.orchestrator import main

        monkeypatch.setenv("NEXUS_ALLOW_DEGRADED_STARTUP", "1")
        assert main._allow_degraded_startup() is True

    def test_development_defaults_to_degraded_rather_than_dead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.orchestrator import main

        monkeypatch.delenv("NEXUS_ALLOW_DEGRADED_STARTUP", raising=False)

        class _Settings:
            environment = "development"

        monkeypatch.setattr(main, "get_settings", lambda: _Settings())
        assert main._allow_degraded_startup() is True

    def test_production_stays_fail_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.orchestrator import main

        monkeypatch.delenv("NEXUS_ALLOW_DEGRADED_STARTUP", raising=False)

        class _Settings:
            environment = "production"

        monkeypatch.setattr(main, "get_settings", lambda: _Settings())
        assert main._allow_degraded_startup() is False


class TestC4ToolsBlockedButFixable:
    """write_file refused every write with no reachable way to grant trust."""

    @pytest.mark.asyncio
    async def test_untrusted_write_is_refused_even_with_a_session(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from backend.persistence import db
        from backend.tools import file_ops

        monkeypatch.setattr(
            db,
            "get_project_by_path",
            lambda path: {
                "id": "proj-1",
                "name": "nexus",
                "path": path,
                "trust": 0,
            },
        )
        result = await file_ops.write_file(
            "note.txt",
            "hello",
            project_path=str(tmp_path),
            session_id="an-interactive-session",
        )
        assert "error" in result
        assert result.get("requires_trust") is True
        assert result.get("project_id") == "proj-1"
        assert not (tmp_path / "note.txt").exists()

    @pytest.mark.asyncio
    async def test_trusted_write_succeeds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from backend.persistence import db
        from backend.tools import file_ops

        monkeypatch.setattr(
            db,
            "get_project_by_path",
            lambda path: {"id": "p", "name": "nexus", "path": path, "trust": 1},
        )
        result = await file_ops.write_file(
            "note.txt", "hello", project_path=str(tmp_path)
        )
        assert "error" not in result, result
        assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hello"

    def test_trust_toggle_payload_is_accepted_by_the_api_model(self) -> None:
        """The edit modal submits path+trust; extra=forbid used to 422 it."""
        from backend.models.api import ProjectUpdateRequest

        req = ProjectUpdateRequest(
            name="nexus",
            path="C:/Users/rodri/Desktop/nexus",
            description="",
            mode="auto",
            preferred_model="",
            trust=True,
        )
        assert req.trust is True
        assert req.path == "C:/Users/rodri/Desktop/nexus"

    def test_windows_path_in_code_is_not_a_sandbox_syntax_error(self) -> None:
        from backend.core.workspace_security import _check_python_sandbox

        ok, reason = _check_python_sandbox('open("C:\\Users\\rodri\\x.txt")')
        assert ok or "raw string" in reason.lower(), reason
