"""Authorization contracts for the runtime settings API.

PUT /api/settings writes process-wide state: the provider credentials, the
endpoints every tenant's model traffic goes to, and the cost policy the LLM
factory reads before the ``NEXUS_FREE_ONLY`` environment default. These tests
pin the promises that keep that state operator-only:

- a non-admin authenticated user is refused (403);
- an admin still cannot weaken the free-model policy from HTTP (400);
- an admin cannot smuggle an unknown key into data/settings.json (400), while a
  real provider key still saves;
- the operator-only cryptographic/session-identity keys are refused (400);
- every key ``GET /api/settings`` exposes - ``Settings`` fields AND
  data/settings.json runtime keys - is writable, operator-controlled or
  operator-only, which is the invariant whose original violation shipped the
  P0 regression.
"""

from __future__ import annotations

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.middleware import auth as auth_module  # noqa: E402
from backend.orchestrator.main import app  # noqa: E402
from backend.orchestrator.routes import settings as settings_routes  # noqa: E402


# Override require_auth/require_admin so tests don't depend on JWT signature secrets
async def _fake_user() -> dict:
    return {"user_id": "test", "email": "t@t"}


async def _other_fake_user() -> dict:
    return {"user_id": "other", "email": "other@t"}


class _StubClient:
    """Stands in for the provider client the settings route rebuilds."""

    async def aclose(self) -> None:
        return None


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Function-scoped client with a fresh, isolated SQLite database."""
    import importlib
    import os

    # Force a per-test DB location
    os.environ["NEXUS_DB_PATH"] = str(tmp_path / "test_nexus.db")
    # Reload the persistence module to pick up the new path
    import backend.persistence.db as db_mod

    importlib.reload(db_mod)
    # Re-point DB_PATH and the connection pool
    db_mod.DB_PATH = tmp_path / "test_nexus.db"
    db_mod._connection_pool = None  # reset the global pool

    # Never touch the developer's real data/settings.json, and never dial a
    # provider: the route only needs a client object it can swap in.
    monkeypatch.setattr(settings_routes, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("backend.llm.factory.create_llm_client", lambda **_kwargs: _StubClient())
    monkeypatch.setattr("backend.llm.model_catalog.schedule_provider_catalog_refresh", lambda *_: None)

    app.dependency_overrides[auth_module.require_auth] = _fake_user
    app.dependency_overrides[auth_module.require_admin] = _fake_user
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(auth_module.require_auth, None)
        app.dependency_overrides.pop(auth_module.require_admin, None)


AUTH = {"Authorization": "Bearer test-bypass"}


def test_non_admin_cannot_write_runtime_settings(client) -> None:
    """A plain authenticated user must not touch process-wide settings."""
    # Drop the admin override so the real RBAC dependency runs against a user
    # that holds no admin role.
    client.app.dependency_overrides.pop(auth_module.require_admin)

    response = client.put(
        "/api/settings",
        json={"settings": {"free_only": "false", "openai_api_key": "sk-attacker-0123456789"}},
        headers=AUTH,
    )

    assert response.status_code == 403, response.text
    assert "admin" in response.json()["detail"].lower()
    assert not settings_routes.SETTINGS_FILE.exists()


def test_admin_cannot_weaken_the_free_model_policy(client) -> None:
    """data/settings.json is read before NEXUS_FREE_ONLY, so 'off' is refused."""
    for falsy in ("false", "False", "0", "no", "off", ""):
        response = client.put(
            "/api/settings", json={"settings": {"free_only": falsy}}, headers=AUTH
        )
        assert response.status_code == 400, (falsy, response.text)
        detail = response.json()["detail"]
        assert "operator-controlled" in detail
        assert "free_only" in detail
    assert not settings_routes.SETTINGS_FILE.exists()


def test_admin_may_reassert_the_free_model_policy(client) -> None:
    """Only the weakening direction is refused; the safe value still saves."""
    response = client.put("/api/settings", json={"settings": {"free_only": "true"}}, headers=AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "saved"
    assert settings_routes._load_runtime_settings()["free_only"] == "true"


def test_admin_cannot_write_an_unknown_setting_key(client) -> None:
    """Unknown keys are a loud 400, never a silent write to the settings file."""
    for unknown in ("attacker_model", "attacker_api_key", "attacker_base_url", "attacker_host"):
        response = client.put(
            "/api/settings", json={"settings": {unknown: "value"}}, headers=AUTH
        )
        assert response.status_code == 400, (unknown, response.text)
        assert unknown in response.json()["detail"]
    assert not settings_routes.SETTINGS_FILE.exists()


def test_admin_can_save_a_legitimate_provider_key(client) -> None:
    """The supported save path still works, and still masks the secret back."""
    response = client.put(
        "/api/settings",
        json={"settings": {"openai_api_key": "sk-nexus-test-0123456789"}},
        headers=AUTH,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "saved"
    assert body["llm_reloaded"] is True
    assert "****" in body["settings"]["openai_api_key"]
    assert settings_routes._load_runtime_settings()["openai_api_key"] == "sk-nexus-test-0123456789"


#: Runtime keys that live in data/settings.json and are NOT ``Settings`` fields.
#: They are the second population ``GET /api/settings`` returns, and the reason
#: the original allowlist (derived from ``Settings.model_fields`` alone) shipped
#: the P0 regression: the Settings UI read-modify-writes the whole object, so
#: PUT has to accept them.
RUNTIME_ONLY_KEYS = ("default_mode", "default_model", "enable_telemetry")


def test_every_exposed_setting_key_is_writable_or_operator_owned(client) -> None:
    """The real read/write invariant: GET must not expose a key PUT refuses.

    ``GET /api/settings`` returns TWO populations - every ``Settings`` field
    plus every key present in data/settings.json - so ``Settings.model_fields``
    alone models the wrong set. This seeds a runtime-only key and asserts the
    invariant the route itself enforces (``_assert_read_write_parity``): every
    exposed key is writable, operator-controlled, or operator-only.
    """
    settings_routes._save_runtime_settings(
        {key: "auto" for key in RUNTIME_ONLY_KEYS}
    )
    settings_routes._RUNTIME_SETTING_KEYS = None

    exposed = set(settings_routes._get_public_settings())

    # Non-vacuous: both populations are actually represented here.
    assert exposed, "the read surface must not be empty"
    assert set(RUNTIME_ONLY_KEYS) <= exposed, sorted(set(RUNTIME_ONLY_KEYS) - exposed)

    unwritable = (
        exposed
        - settings_routes._writable_setting_keys()
        - settings_routes.OPERATOR_CONTROLLED_KEYS
        - settings_routes.OPERATOR_ONLY_KEYS
    )
    assert not unwritable, f"GET exposes keys PUT refuses: {sorted(unwritable)}"

    # The route's own executable form of the same rule must agree.
    settings_routes._assert_read_write_parity()


def test_operator_only_keys_are_refused(client) -> None:
    """Cryptographic / session-identity keys are never writable over HTTP."""
    for key in sorted(settings_routes.OPERATOR_ONLY_KEYS):
        response = client.put(
            "/api/settings", json={"settings": {key: "attacker-value"}}, headers=AUTH
        )
        assert response.status_code == 400, (key, response.text)
        detail = response.json()["detail"]
        assert "operator-only" in detail, (key, detail)
        assert key in detail, (key, detail)
    assert not settings_routes.SETTINGS_FILE.exists()


def test_provider_and_non_provider_setting_keys_are_known() -> None:
    """The allowlist still covers the provider and non-provider surface."""
    for key in (
        "openai_api_key",
        "anthropic_api_key",
        "gemini_base_url",
        "openrouter_api_key",
        "kilo_base_url",
        "ollama_host",
        "lmstudio_api_key",
        "brave_api_key",
    ):
        assert settings_routes._is_known_setting_key(key), key
    for key in ("llm_provider", "log_level", "nexus_enable_ollama", "openai_max_tokens"):
        assert settings_routes._is_known_setting_key(key), key
    # ``free_only`` is operator-controlled: it is not *writable*, but it must
    # still be *known* so the caller gets the accurate "operator-controlled"
    # refusal instead of "unknown setting". Only the weakening direction is
    # rejected -- the safe value can be re-asserted
    # (see test_admin_may_reassert_the_free_model_policy).
    assert "free_only" in settings_routes.OPERATOR_CONTROLLED_KEYS
    assert settings_routes._is_known_setting_key("free_only")
    assert "free_only" not in settings_routes._writable_setting_keys()
    assert not settings_routes._is_policy_weakening("true")
    assert settings_routes._is_policy_weakening("false")
    for key in ("", "   ", "anything_else", "openai_secret"):
        assert not settings_routes._is_known_setting_key(key), key
