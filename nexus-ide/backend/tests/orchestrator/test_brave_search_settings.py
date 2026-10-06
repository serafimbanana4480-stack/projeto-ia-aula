"""Brave Search credentials use the existing masked, encrypted settings path."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.orchestrator.routes import settings as settings_routes
from backend.tools import web_search


def test_brave_key_resolves_runtime_override_then_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_routes, "_load_runtime_settings", lambda: {"brave_api_key": "runtime-test-key"})
    monkeypatch.setattr(web_search, "get_settings", lambda: SimpleNamespace(brave_api_key="environment-test-key"))
    assert web_search.get_brave_api_key() == "runtime-test-key"

    monkeypatch.setattr(settings_routes, "_load_runtime_settings", lambda: {})
    assert web_search.get_brave_api_key() == "environment-test-key"


def test_public_settings_masks_brave_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_routes,
        "get_settings",
        lambda: SimpleNamespace(model_dump=lambda **_kwargs: {"brave_api_key": "brave-test-key-1234"}),
    )
    monkeypatch.setattr(settings_routes, "_load_runtime_settings", lambda: {})

    public = settings_routes._get_public_settings()

    assert public["brave_api_key"] != "brave-test-key-1234"
    assert "****" in public["brave_api_key"]


@pytest.mark.asyncio
async def test_invalid_brave_key_is_rejected_before_runtime_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    target = tmp_path / "settings.json"
    monkeypatch.setattr(settings_routes, "SETTINGS_FILE", target)
    monkeypatch.setattr(settings_routes, "get_settings", lambda: SimpleNamespace(brave_api_key=""))
    monkeypatch.setattr(settings_routes, "_get_public_settings", lambda: {})
    builds: list[bool] = []
    monkeypatch.setattr("backend.llm.factory.create_llm_client", lambda **_kwargs: builds.append(True))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(HTTPException) as error:
        await settings_routes.update_settings(
            settings_routes.SettingsUpdate(settings={"brave_api_key": "key with spaces"}),
            request=request,
            _user={"user_id": "test"},
        )

    assert error.value.status_code == 400
    assert "invalid format" in str(error.value.detail).lower()
    assert builds == []
    assert not target.exists()


@pytest.mark.asyncio
async def test_non_ascii_brave_key_is_rejected_without_replacing_saved_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    target = tmp_path / "settings.json"
    monkeypatch.setattr(settings_routes, "SETTINGS_FILE", target)
    settings_routes._save_runtime_settings({"brave_api_key": "existing-valid-test-key"})
    original_contents = target.read_bytes()
    monkeypatch.setattr(settings_routes, "get_settings", lambda: SimpleNamespace(brave_api_key=""))
    monkeypatch.setattr(
        "backend.llm.factory.create_llm_client",
        lambda **_kwargs: pytest.fail("must not rebuild"),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(HTTPException) as error:
        await settings_routes.update_settings(
            settings_routes.SettingsUpdate(settings={"brave_api_key": "chavé-brave"}),
            request=request,
            _user={"user_id": "test"},
        )

    assert error.value.status_code == 400
    assert "invalid format" in str(error.value.detail).lower()
    assert target.read_bytes() == original_contents
    assert settings_routes._load_runtime_settings()["brave_api_key"] == "existing-valid-test-key"


def test_runtime_settings_encrypt_brave_key_at_rest(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    target = tmp_path / "settings.json"
    monkeypatch.setattr(settings_routes, "SETTINGS_FILE", target)

    settings_routes._save_runtime_settings({"brave_api_key": "brave-test-key-1234"})

    raw = target.read_text(encoding="utf-8")
    assert "brave-test-key-1234" not in raw
    assert settings_routes._load_runtime_settings()["brave_api_key"] == "brave-test-key-1234"
