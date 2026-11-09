"""The signing secret must never be a value the repository publishes.

The defect this file pins down
------------------------------
``.env`` shipped ``JWT_SECRET=change-this-secret-in-production-use-env-var``,
byte-identical to the value in ``.env.example``.  ``validate_configuration``
only refused a *different* placeholder string, so the misconfiguration went
unnoticed and a token signed with that publicly known secret was accepted as
the admin.

The rule now: a secret that is published, that looks like a placeholder, or
that is too short to be a secret stops the startup -- the API refuses to come
up rather than sign tokens with a key everybody can read.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import backend.config.settings as settings_module
from backend.config.settings import (
    MIN_SECRET_LENGTH,
    REPO_ROOT,
    _bootstrap_secrets,
    _read_env_value,
    describe_secret_problem,
    get_settings,
    validate_configuration,
)

#: The value ``.env.example`` ships for ``JWT_SECRET``.
EXAMPLE_JWT_SECRET = "change-this-secret-in-production-use-env-var"

#: The value the code used to accept as "the development default".
LEGACY_DEFAULT_JWT_SECRET = "development-jwt-secret-change-in-production"


def _published_example_secret() -> str:
    """The ``JWT_SECRET`` value the example file actually ships."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    return _read_env_value(example, "JWT_SECRET")


def _reset_settings_cache() -> None:
    """Drop the cached settings so the next read re-resolves them."""
    settings_module._settings_instance = None
    get_settings.cache_clear()


def _errors_for(secret: str) -> list[str]:
    """The validation errors reported for a given ``JWT_SECRET``."""
    previous = os.environ.get("JWT_SECRET")
    os.environ["JWT_SECRET"] = secret
    _reset_settings_cache()
    try:
        return validate_configuration()
    finally:
        if previous is None:
            os.environ.pop("JWT_SECRET", None)
        else:
            os.environ["JWT_SECRET"] = previous
        _reset_settings_cache()


def test_validate_configuration_rejects_example_jwt_secret() -> None:
    """The value published in ``.env.example`` must stop the startup.

    This is the exact value the live ``.env`` carried, and the reason an
    attacker could mint an admin token.
    """
    published = _published_example_secret()
    # ``.env.example`` may ship with ``JWT_SECRET=`` empty; the historical
    # published placeholder is still refused (regression for the live defect).
    secret_under_test = published or EXAMPLE_JWT_SECRET
    assert secret_under_test, "no JWT placeholder to validate"

    errors = _errors_for(secret_under_test)

    assert errors, "a secret published in .env.example must be refused"
    assert any("JWT_SECRET" in error for error in errors), errors
    assert any(".env.example" in error for error in errors), errors


def test_validate_configuration_rejects_low_entropy_secret() -> None:
    """A secret too short to be a secret must stop the startup."""
    errors = _errors_for("abc123xyz")

    assert errors, "a short secret must be refused"
    assert any("JWT_SECRET" in error for error in errors), errors
    assert any("too weak" in error for error in errors), errors


def test_validate_configuration_rejects_placeholder_like_secret() -> None:
    """A value that merely *looks* like a placeholder must be refused too.

    The published example value is only the first case; an operator who
    writes "change-me" or "your-secret-here" is just as unsafe.
    """
    errors = _errors_for("please-change-this-to-a-real-secret-value")

    assert errors, "a placeholder-looking secret must be refused"
    assert any("JWT_SECRET" in error for error in errors), errors
    assert any("placeholder" in error for error in errors), errors


def test_validate_configuration_accepts_a_strong_secret() -> None:
    """The gate must not fire on a real secret."""
    assert describe_secret_problem("JWT_SECRET", "k" * 48) is None


def test_bootstrap_secrets_replaces_placeholder_secret(tmp_path: Path) -> None:
    """The bootstrap must not keep a published placeholder in ``.env``.

    A placeholder is treated exactly like a missing secret: a strong value is
    generated and put in its place, because "the file still holds a value
    everyone can read" is the same failure as "the file holds no value".
    """
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# local config\nSECRET_KEY=keep-this-one\nJWT_SECRET=" + EXAMPLE_JWT_SECRET + "\n",
        encoding="utf-8",
    )

    _bootstrap_secrets(env_path)

    content = env_path.read_text(encoding="utf-8")
    assert EXAMPLE_JWT_SECRET not in content, "the published placeholder survived the bootstrap"

    generated = _read_env_value(content, "JWT_SECRET")
    assert generated, "the bootstrap must leave a usable JWT_SECRET behind"
    assert generated != EXAMPLE_JWT_SECRET
    assert len(generated) >= MIN_SECRET_LENGTH
    assert describe_secret_problem("JWT_SECRET", generated) is None

    # A secret that is already real is left exactly as it was.
    assert _read_env_value(content, "SECRET_KEY") == "keep-this-one"


def test_bootstrap_secrets_leaves_a_real_secret_alone(tmp_path: Path) -> None:
    """The bootstrap must not rewrite a secret the operator chose."""
    env_path = tmp_path / ".env"
    original = "SECRET_KEY=keep-this-one\nJWT_SECRET=" + ("k" * 48) + "\n"
    env_path.write_text(original, encoding="utf-8")

    _bootstrap_secrets(env_path)

    assert env_path.read_text(encoding="utf-8") == original


def test_bootstrap_secrets_appends_a_secret_when_none_is_set(tmp_path: Path) -> None:
    """A missing secret is still generated and appended (first-start path)."""
    env_path = tmp_path / ".env"
    env_path.write_text("SECRET_KEY=keep-this-one\n", encoding="utf-8")

    _bootstrap_secrets(env_path)

    generated = _read_env_value(env_path.read_text(encoding="utf-8"), "JWT_SECRET")
    assert generated
    assert len(generated) >= MIN_SECRET_LENGTH


def test_legacy_default_secret_is_also_refused() -> None:
    """The placeholder the validator used to check is still refused."""
    errors = _errors_for(LEGACY_DEFAULT_JWT_SECRET)

    assert errors
    assert any("JWT_SECRET" in error for error in errors), errors


def test_secret_key_is_guarded_too() -> None:
    """``SECRET_KEY`` signs session material, so it gets the same gate."""
    previous = os.environ.get("SECRET_KEY")
    os.environ["SECRET_KEY"] = EXAMPLE_JWT_SECRET
    _reset_settings_cache()
    try:
        errors = validate_configuration()
    finally:
        if previous is None:
            os.environ.pop("SECRET_KEY", None)
        else:
            os.environ["SECRET_KEY"] = previous
        _reset_settings_cache()

    assert any("SECRET_KEY" in error for error in errors), errors


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_a_published_secret_is_refused_in_every_environment(environment: str) -> None:
    """The gate does not soften itself outside development."""
    previous = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = environment
    _reset_settings_cache()
    try:
        errors = _errors_for(EXAMPLE_JWT_SECRET)
    finally:
        if previous is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = previous
        _reset_settings_cache()

    assert any("JWT_SECRET" in error for error in errors), errors
