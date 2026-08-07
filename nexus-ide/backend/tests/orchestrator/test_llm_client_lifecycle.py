"""Tests for safe hot-reloading of the application LLM client."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.orchestrator.llm_client_lifecycle import (
    acquire_llm_client,
    close_all_llm_clients,
    release_llm_client,
    retire_llm_client,
)
from backend.orchestrator.routes import settings as settings_routes


class _Client:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


def _app(client: _Client) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(llm_client=client))


@pytest.mark.asyncio
async def test_retired_client_waits_for_its_active_stream() -> None:
    old_client = _Client()
    app = _app(old_client)

    acquire_llm_client(app, old_client)
    await retire_llm_client(app, old_client)
    assert old_client.close_calls == 0

    await release_llm_client(app, old_client)
    assert old_client.close_calls == 1


@pytest.mark.asyncio
async def test_shutdown_closes_each_live_client_once() -> None:
    current = _Client()
    retired = _Client()
    app = _app(current)
    acquire_llm_client(app, retired)
    await retire_llm_client(app, retired)

    await close_all_llm_clients(app)

    assert current.close_calls == 1
    assert retired.close_calls == 1


@pytest.mark.asyncio
async def test_settings_update_replaces_the_client_and_persists_string_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    old_client = _Client()
    new_client = _Client()
    app = _app(old_client)
    app.state.agent_lifecycle = SimpleNamespace(_llm_client=old_client)
    request = SimpleNamespace(app=app)
    captured: dict[str, object] = {}

    def build_client(**overrides: object) -> _Client:
        captured.update(overrides)
        return new_client

    monkeypatch.setattr(settings_routes, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("backend.llm.factory.create_llm_client", build_client)
    monkeypatch.setattr(settings_routes, "get_settings", lambda: SimpleNamespace())

    result = await settings_routes.update_settings(
        settings_routes.SettingsUpdate(
            settings={"llm_provider": "openai", "openai_api_key": "runtime-key"}
        ),
        request=request,
        _user={"sub": "tester"},
    )

    assert captured["llm_provider"] == "openai"
    assert app.state.llm_client is new_client
    assert app.state.agent_lifecycle._llm_client is new_client
    assert old_client.close_calls == 1
    assert result["llm_reloaded"] is True
    assert settings_routes._load_runtime_settings()["openai_api_key"] == "runtime-key"
