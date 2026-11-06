"""The auth routes: rotation, revocation and who may register.

Three defects are pinned down here.

* ``POST /api/auth/refresh`` minted a new refresh token and left the old one
  valid forever -- the same refresh token was accepted twice.
* ``POST /api/auth/logout`` was an explicit no-op -- the token still worked
  afterwards.
* ``POST /api/auth/register`` was a public route in every environment, so
  anyone who could reach the API could create an account and then call the
  tool-execution endpoints.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import backend.config.settings as settings_module
from backend.orchestrator.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client for the auth routes (no lifespan: the routes are the subject).

    The rate limiter is suspended for the duration: the budget is per client
    address, so it is shared with every other test in the session, and a 429
    would say nothing about the behaviour under test.
    """
    limiter = getattr(app.state, "limiter", None)
    original = getattr(limiter, "enabled", None)
    if limiter is not None:
        limiter.enabled = False
    try:
        yield TestClient(app)
    finally:
        if limiter is not None and original is not None:
            limiter.enabled = original


def _register(client: TestClient) -> dict[str, Any]:
    """Create a user and return the token payload."""
    email = f"auth-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Passw0rd!23", "full_name": "Auth Test"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_environment(name: str, value: str) -> None:
    """Change an environment variable and re-resolve the settings."""
    os.environ[name] = value
    settings_module._settings_instance = None
    settings_module.get_settings.cache_clear()


def test_refresh_token_is_rotated_and_old_one_rejected(client: TestClient) -> None:
    """A refresh token is single-use: the exchange spends the old one."""
    tokens = _register(client)
    original_refresh_token = tokens["refresh_token"]

    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": original_refresh_token},
    )
    assert response.status_code == 200, response.text
    rotated = response.json()
    assert rotated["refresh_token"], "the exchange must issue a new refresh token"
    assert rotated["refresh_token"] != original_refresh_token
    assert rotated["access_token"]

    # The spent token is refused: the replay that used to succeed.
    replay = client.post(
        "/api/auth/refresh",
        json={"refresh_token": original_refresh_token},
    )
    assert replay.status_code == 401, replay.text
    assert replay.json()["detail"] == "Token has been revoked"

    # The new one works, and can itself be rotated.
    second = client.post(
        "/api/auth/refresh",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["refresh_token"] != rotated["refresh_token"]


def test_refresh_retry_recovers_the_same_pair_after_revocation_store_restart(
    client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost response can be recovered durably, but only with its same key."""
    from backend.auth.service import get_revocation_store

    monkeypatch.setenv("NEXUS_SETTINGS_SALT_FILE", str(tmp_path / "refresh-kdf-salt"))
    tokens = _register(client)
    refresh_token = tokens["refresh_token"]
    headers = {"Idempotency-Key": f"refresh-{uuid.uuid4().hex}"}

    first = client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    # The old refresh JTI is also tracked in SQLite, so clearing the
    # process-local revocation store models a backend restart for this path.
    get_revocation_store().clear()
    retried = client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
        headers=headers,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json() == first.json()

    replayed = client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
        headers={"Idempotency-Key": f"refresh-{uuid.uuid4().hex}"},
    )
    assert replayed.status_code == 401
    assert replayed.json()["detail"] == "Token has been revoked"


def test_logout_revokes_the_token(client: TestClient) -> None:
    """After a logout the presented token is refused."""
    tokens = _register(client)
    access_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    before = client.get("/api/auth/me", headers=headers)
    assert before.status_code == 200, before.text

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 200, logout.text

    after = client.get("/api/auth/me", headers=headers)
    assert after.status_code == 401, after.text
    assert after.json()["detail"] == "Token has been revoked"


def test_logout_revocation_survives_backend_restart(client: TestClient) -> None:
    """SQLite keeps a logged-out access token and login session revoked."""
    from backend.auth.service import get_revocation_store

    tokens = _register(client)
    logout = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert logout.status_code == 200, logout.text

    # Clearing this process-local cache simulates a restart; SQLite remains.
    get_revocation_store().clear()

    access_after_restart = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    refresh_after_restart = client.post(
        "/api/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert access_after_restart.status_code == 401
    assert access_after_restart.json()["detail"] == "Token has been revoked"
    assert refresh_after_restart.status_code == 401
    assert refresh_after_restart.json()["detail"] == "Session has been revoked"


def test_logout_also_ends_the_refresh_token_of_that_login(client: TestClient) -> None:
    """A logged-out session cannot be renewed with its refresh token."""
    tokens = _register(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 200, logout.text

    refresh = client.post(
        "/api/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh.status_code == 401, refresh.text


def test_registration_disabled_outside_development(client: TestClient) -> None:
    """Outside development, an open registration endpoint is a hole.

    Anyone who can reach the API could create an account and then call the
    tool-execution endpoints with it.
    """
    previous = os.environ.get("ENVIRONMENT")
    _set_environment("ENVIRONMENT", "production")
    try:
        response = client.post(
            "/api/auth/register",
            json={
                "email": f"blocked-{uuid.uuid4().hex[:10]}@example.com",
                "password": "Passw0rd!23",
                "full_name": "Blocked",
            },
        )
    finally:
        if previous is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = previous
        settings_module._settings_instance = None
        settings_module.get_settings.cache_clear()

    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert "registration" in detail.lower()
    assert "disabled" in detail.lower()


def test_registration_is_enabled_in_development(client: TestClient) -> None:
    """The development default keeps working (the repo depends on it)."""
    previous = os.environ.get("ENVIRONMENT")
    _set_environment("ENVIRONMENT", "development")
    try:
        response = client.post(
            "/api/auth/register",
            json={
                "email": f"dev-{uuid.uuid4().hex[:10]}@example.com",
                "password": "Passw0rd!23",
                "full_name": "Dev User",
            },
        )
    finally:
        if previous is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = previous
        settings_module._settings_instance = None
        settings_module.get_settings.cache_clear()

    assert response.status_code == 201, response.text
    assert response.json()["access_token"]


def test_a_refresh_token_cannot_be_used_as_a_bearer_credential(client: TestClient) -> None:
    """The 7-day refresh token must not authenticate a request."""
    tokens = _register(client)

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "Invalid token type"
