"""Settings API — get/set runtime configuration without server restart.

GET  /api/settings  → current settings (API keys masked)
PUT  /api/settings  → update runtime settings (persisted to data/settings.json)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.config.settings import Settings, get_settings
from backend.middleware.auth import require_admin, require_auth

logger = logging.getLogger(__name__)
router = APIRouter()

SETTINGS_FILE = Path(__file__).resolve().parents[3] / "data" / "settings.json"

# Canonical sensitive-key rule (audit P1-4).  This module used to keep its own
# copy of the list, which disagreed with
# ``backend/core/secure_settings_store.py`` on exactly one name — ``secret_key``
# — and that disagreement is what put a cleartext SECRET_KEY on disk while every
# other credential was encrypted.  One source of truth now: masking and
# encryption cannot drift apart again.
from backend.core.secure_settings_store import (  # noqa: E402
    EncryptionUnavailableError,
    assert_crypto_backend,
    looks_masked,
)
from backend.core.sensitive_keys import is_sensitive_key  # noqa: E402

# Startup assertion: never write secrets without a working crypto backend.
# Import-time so a broken ``cryptography`` install or an empty SECRET_KEY is a
# loud failure, not a silent cleartext write on the first PUT.
assert_crypto_backend()


#: Backwards-compatible alias (tests import it).  Bound to the canonical
#: function object, not a wrapper, so "is this masked" and "is this encrypted"
#: can never diverge again.
_is_sensitive = is_sensitive_key


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "********"
    return value[:4] + "****" + value[-4:]


def _is_masked_secret(value: str) -> bool:
    """Recognise values produced by this API's masking contract.

    Delegates to the store's canonical :func:`looks_masked` so the accept and
    the reject cannot diverge either.
    """
    return looks_masked(value)


# ---------------------------------------------------------------------------
# Write policy for PUT /api/settings
#
# Two rules, both enforced on the HTTP surface:
#
# 1. Operator policy is not a tenant preference.  ``free_only`` is resolved by
#    ``backend.llm.factory._free_only_enabled`` from ``data/settings.json``
#    *before* the ``NEXUS_FREE_ONLY`` environment default, so a saved ``false``
#    turned the zero-cost operator invariant off for every tenant at once.  Only
#    the weakening direction is refused; re-asserting the safe value is allowed.
# 2. Every key is allowlisted.  The save loop used to accept an arbitrary
#    string key, which let any caller write a credential, an endpoint or a
#    policy flag into the file the LLM factory reads - and the response then
#    replaced the process-wide ``llm_client``, repointing every tenant's model
#    traffic.  Unknown keys are now a loud 400 instead of a silent write.
# ---------------------------------------------------------------------------

#: Keys that only the operator may change, and only through environment /
#: configuration.  Values that would weaken them are refused (see
#: :func:`_is_policy_weakening`).
OPERATOR_CONTROLLED_KEYS: frozenset[str] = frozenset({"free_only"})

#: Cryptographic / session-identity keys.  These are read from the operator's
#: environment and never from data/settings.json, so accepting them here would
#: store a value that silently does nothing while appearing to take effect.
#: Unlike :data:`OPERATOR_CONTROLLED_KEYS` these are refused outright, because
#: there is no value an HTTP caller could legitimately send.
OPERATOR_ONLY_KEYS: frozenset[str] = frozenset(
    {"secret_key", "jwt_secret", "jwt_algorithm", "jwt_expiration_minutes"}
)

#: Provider credentials and endpoints the LLM factory knows how to build a
#: client from.  Explicit rather than derived from a suffix rule: a submitted
#: ``*_api_key`` / ``*_base_url`` / ``*_host`` key that is not in this set is a
#: rejected credential/endpoint, not a saved one.  Adding a provider means
#: adding its keys here and to ``backend.config.settings``.
PROVIDER_SETTING_KEYS: frozenset[str] = frozenset(
    {
        # Local / OpenAI-compatible servers
        "ollama_host",
        "ollama_dashboard_host",
        "lmstudio_host",
        "lmstudio_api_key",
        # Cloud providers
        "openai_api_key",
        "deepseek_api_key",
        "deepseek_base_url",
        "kimi_api_key",
        "groq_api_key",
        "anthropic_api_key",
        "gemini_api_key",
        "gemini_base_url",
        "openrouter_api_key",
        "openrouter_base_url",
        "opencode_go_api_key",
        "opencode_go_base_url",
        "kilo_api_key",
        "kilo_base_url",
        # Web search
        "brave_api_key",
    }
)

#: Suffixes that mark a key as a provider credential / endpoint.
_PROVIDER_KEY_SUFFIXES: tuple[str, ...] = ("_api_key", "_base_url", "_host")

#: Everything PUT /api/settings may write.
#:
#: ``GET /api/settings`` returns two populations: every ``Settings`` field, plus
#: whatever keys exist in data/settings.json (runtime overrides). The Settings
#: page does a read-modify-write of the whole object, so PUT must accept
#: everything GET returns or the Save button 400s on keys the user never typed.
#: Deriving the allowlist from both populations -- rather than from the
#: ``Settings`` class alone -- makes that asymmetry structurally impossible to
#: reintroduce. ``_assert_read_write_parity`` is the executable form of the rule.
#: Keys in data/settings.json that are not ``Settings`` fields. Populated lazily
#: because the file is read at request time, not at import time.
_RUNTIME_SETTING_KEYS: frozenset[str] | None = None


def _writable_setting_keys() -> frozenset[str]:
    """Everything PUT /api/settings may write.

    ``GET /api/settings`` returns two populations: every ``Settings`` field, plus
    whatever keys exist in data/settings.json (runtime overrides). The Settings
    page does a read-modify-write of the whole object, so PUT must accept
    everything GET returns or the Save button 400s on keys the user never typed.
    Deriving the allowlist from both populations -- rather than from the
    ``Settings`` class alone -- makes that asymmetry structurally impossible to
    reintroduce. :func:`_assert_read_write_parity` is the executable form.
    """
    global _RUNTIME_SETTING_KEYS
    if _RUNTIME_SETTING_KEYS is None:
        _RUNTIME_SETTING_KEYS = frozenset(_load_runtime_settings())
    return (
        frozenset(Settings.model_fields)
        | PROVIDER_SETTING_KEYS
        | _RUNTIME_SETTING_KEYS
    ) - OPERATOR_ONLY_KEYS - OPERATOR_CONTROLLED_KEYS


def _assert_read_write_parity() -> None:
    """Fail loudly if GET ever exposes a key PUT refuses.

    Without this the only symptom is a 400 on a Settings Save that the user
    cannot diagnose, which is exactly how the original allowlist broke.
    """
    exposed = set(_get_public_settings())
    unwritable = exposed - _writable_setting_keys() - OPERATOR_CONTROLLED_KEYS - OPERATOR_ONLY_KEYS
    if unwritable:
        raise RuntimeError(
            "GET /api/settings exposes keys PUT /api/settings refuses: "
            f"{sorted(unwritable)}"
        )

#: Affirmative spellings, mirroring ``backend.llm.factory._as_bool``.  Anything
#: else parses as "off" in the factory, so it must be refused here too.
_TRUTHY_SETTING_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def _is_policy_weakening(value: Any) -> bool:
    """Whether *value* would switch an operator-controlled policy off."""
    if isinstance(value, str):
        return value.strip().lower() not in _TRUTHY_SETTING_VALUES
    return not value


def _is_known_setting_key(key: str) -> bool:
    """Whether PUT /api/settings may write *key*.

    Provider-shaped keys (``*_api_key`` / ``*_base_url`` / ``*_host``) must be
    named in :data:`PROVIDER_SETTING_KEYS`; everything else must be a real
    setting field, so an unknown key is reported to the caller instead of being
    persisted and silently ignored.

    :data:`OPERATOR_CONTROLLED_KEYS` counts as known even though it is not
    writable: ``free_only=true`` re-asserts the safe value and must be accepted,
    while the weakening direction is refused earlier by its own guard. Being
    "known" here only means the caller gets the accurate message instead of
    being told the key does not exist.
    """
    if not key:
        return False
    if key in OPERATOR_CONTROLLED_KEYS:
        return True
    if key in PROVIDER_SETTING_KEYS:
        return True
    if key.endswith(_PROVIDER_KEY_SUFFIXES):
        return False
    return key in _writable_setting_keys()


def _validate_brave_api_key(value: str) -> str:
    """Normalize a Brave token without logging or exposing the secret.

    Brave does not publish a stable token length contract. Validate only the
    shape needed for safe storage and HTTP header use; provider acceptance is
    verified by an actual search request, never claimed by settings save.
    """
    normalized = value.strip()
    if (
        not normalized
        or not normalized.isascii()
        or len(normalized) > 512
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in normalized
        )
    ):
        raise HTTPException(
            status_code=400,
            detail="The Brave Search API key has an invalid format.",
        )
    return normalized


def _load_runtime_settings() -> dict[str, str]:
    # B7: valores sensíveis são desencriptados de forma transparente.
    from backend.core.secure_settings_store import load_settings

    return {
        k: v
        for k, v in load_settings(SETTINGS_FILE).items()
        if isinstance(v, str)
    }


def _save_runtime_settings(settings: dict[str, str]) -> None:
    # B7: chaves/segredos são encriptados em repouso (enc:v2:…, scrypt + AAD).
    from backend.core.secure_settings_store import save_settings

    global _RUNTIME_SETTING_KEYS
    _RUNTIME_SETTING_KEYS = None
    save_settings(SETTINGS_FILE, settings)


def _get_public_settings() -> dict[str, Any]:
    """Return all settings with sensitive values masked."""
    env_settings = get_settings()
    result: dict[str, Any] = {}

    # ``dir(BaseSettings)`` also exposes Pydantic metadata such as
    # ``model_fields`` whose values contain ``FieldInfo`` objects.  FastAPI
    # cannot serialize those and GET /api/settings returned HTTP 500.
    # ``model_dump()`` is the supported JSON-oriented view; the small fallback
    # keeps this helper usable by integrations/tests that inject a namespace.
    if hasattr(env_settings, "model_dump"):
        raw_settings = env_settings.model_dump(mode="json")
    elif hasattr(env_settings, "dict") and callable(env_settings.dict):
        raw_settings = env_settings.dict()
    else:
        raw_settings = vars(env_settings) if hasattr(env_settings, "__dict__") else {}
    for key, value in raw_settings.items():
        if _is_sensitive(key) and isinstance(value, str) and value:
            result[key] = _mask(value)
        else:
            result[key] = value

    # Merge runtime overrides
    runtime = _load_runtime_settings()
    for key, value in runtime.items():
        if _is_sensitive(key):
            result[key] = _mask(value)
        else:
            result[key] = value

    return result


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


@router.get("/settings")
async def get_settings_endpoint(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Return current application settings (API keys masked)."""
    # The Settings UI reads this whole object back and PUTs it verbatim, so any
    # key returned here must be accepted by update_settings below.
    _assert_read_write_parity()
    return _get_public_settings()


@router.put("/settings")
async def update_settings(
    update: SettingsUpdate,
    request: Request,
    _user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Update runtime settings (persisted to data/settings.json).

    Admin-only: these values are process-wide, so a save by one tenant would
    change every tenant's credentials, endpoint and cost policy.

    Only accepts string values. Non-sensitive keys are saved directly,
    sensitive keys are validated before storage, operator-controlled keys are
    refused, and unknown keys are rejected instead of silently persisted.
    """
    # Policy guards first: a request that would weaken an operator invariant or
    # smuggle an unknown key must never reach the file the LLM factory reads.
    for raw_key, raw_value in update.settings.items():
        normalized_key = raw_key.strip() if isinstance(raw_key, str) else ""
        if not normalized_key:
            continue
        if normalized_key in OPERATOR_CONTROLLED_KEYS and _is_policy_weakening(raw_value):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{normalized_key}' is operator-controlled and cannot be changed "
                    "through this endpoint. Set it via environment/configuration "
                    "instead."
                ),
            )
        if normalized_key in OPERATOR_ONLY_KEYS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{normalized_key}' is operator-only and cannot be written "
                    "through this endpoint. Set it via environment/configuration."
                ),
            )
        if not _is_known_setting_key(normalized_key):
            raise HTTPException(
                status_code=400,
                detail=f"Unknown setting '{normalized_key}'",
            )

    # P1-4 cascade guard: if the stored ciphertexts cannot be read with the
    # current SECRET_KEY, a save would rebuild the LLM client from an empty
    # credential set and every provider would silently become "not configured".
    from backend.core.secure_settings_store import undecryptable_keys

    broken = undecryptable_keys(SETTINGS_FILE)
    if broken:
        logger.error(
            "Refusing to save settings: %d stored secret(s) cannot be decrypted with the "
            "current SECRET_KEY (%s)",
            len(broken),
            ", ".join(sorted(broken)),
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Stored secrets cannot be decrypted with the current SECRET_KEY. "
                f"Restore the original SECRET_KEY or re-enter these keys: {sorted(broken)}"
            ),
        )

    current = _load_runtime_settings()
    env_settings = get_settings()
    for key, value in update.settings.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"Invalid type for key '{key}'")
        if not key.strip():
            continue
        normalized_key = key.strip()
        if _is_sensitive(normalized_key) and _is_masked_secret(value):
            # GET /api/settings and older clients expose masked secrets.  Keep
            # the real value from runtime overrides/.env, or reject the
            # request explicitly when no value exists to preserve.
            existing = current.get(normalized_key) or getattr(env_settings, normalized_key, "")
            if existing:
                continue
            raise HTTPException(
                status_code=400,
                detail=f"A masked value cannot be saved for '{normalized_key}'; send the new secret explicitly.",
            )
        # Settings UI forms intentionally submit empty password fields for
        # providers that were not edited. Do not erase an existing secret just
        # because another provider was saved.
        if normalized_key.endswith("_api_key") and not value.strip() and (
            current.get(normalized_key) or getattr(env_settings, normalized_key, "")
        ):
            continue
        current[normalized_key] = (
            _validate_brave_api_key(value)
            if normalized_key == "brave_api_key" and value.strip()
            else value
        )

    changed_providers = {
        "ollama" if key == "ollama_host" else key.removesuffix("_api_key").removesuffix("_base_url")
        for key in update.settings
        if key.endswith(("_api_key", "_base_url", "_host")) and key != "brave_api_key"
    }
    # Build the replacement before persisting it.  A malformed provider
    # configuration must not leave the saved settings pointing at a client
    # that could not be initialized.
    try:
        from backend.llm.factory import create_llm_client

        replacement_client = create_llm_client(**current)
    except Exception as exc:
        logger.warning("Rejected runtime LLM settings update: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="The supplied LLM settings could not be initialized.",
        ) from exc

    try:
        _save_runtime_settings(current)
    except EncryptionUnavailableError as exc:
        # Fail LOUD, never store plaintext: a broken crypto backend must not
        # silently downgrade every credential in the file to cleartext.
        close = getattr(replacement_client, "aclose", None)
        if callable(close):
            await close()
        logger.error("Refusing to save settings without a working crypto backend: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Settings cannot be stored securely right now (crypto backend unavailable).",
        ) from exc
    except ValueError as exc:
        close = getattr(replacement_client, "aclose", None)
        if callable(close):
            await close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        close = getattr(replacement_client, "aclose", None)
        if callable(close):
            await close()
        raise HTTPException(status_code=500, detail="Could not save runtime settings.") from exc

    previous_client = getattr(request.app.state, "llm_client", None)
    request.app.state.llm_client = replacement_client
    lifecycle = getattr(request.app.state, "agent_lifecycle", None)
    if lifecycle is not None and hasattr(lifecycle, "_llm_client"):
        lifecycle._llm_client = replacement_client

    # Existing SSE responses keep their captured client until completion;
    # retire_llm_client closes it immediately only when no stream uses it.
    from backend.orchestrator.llm_client_lifecycle import retire_llm_client

    if previous_client is not replacement_client:
        await retire_llm_client(request.app, previous_client)

    # Refresh catalogs after a successful rebuild — never invalidate before
    # rebuild, which wiped disk cache and left chat with an empty catalog (QA C2).
    if changed_providers:
        from backend.llm.model_catalog import schedule_provider_catalog_refresh

        for provider in changed_providers:
            schedule_provider_catalog_refresh(request.app, provider)

    logger.info("Runtime settings updated (%d keys)", len(update.settings))
    return {
        "status": "saved",
        "llm_reloaded": True,
        "settings": _get_public_settings(),
    }
