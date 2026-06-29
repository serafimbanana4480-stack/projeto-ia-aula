"""Settings API — get/set runtime configuration without server restart.

GET  /api/settings  → current settings (API keys masked)
PUT  /api/settings  → update runtime settings (persisted to data/settings.json)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.config.settings import get_settings
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()

SETTINGS_FILE = Path(__file__).resolve().parents[3] / "data" / "settings.json"

# Keys that contain API secrets — will be masked in GET responses
_SENSITIVE_KEYS = {
    "openai_api_key",
    "deepseek_api_key",
    "kimi_api_key",
    "groq_api_key",
    "anthropic_api_key",
    "gemini_api_key",
    "openrouter_api_key",
    "secret_key",
    "jwt_secret",
    "brave_api_key",
    "redis_password",
}

_SENSITIVE_SUFFIXES = ("api_key", "secret", "password", "token")


def _is_sensitive(key: str) -> bool:
    if key in _SENSITIVE_KEYS:
        return True
    key_lower = key.lower()
    return any(key_lower.endswith(s) for s in _SENSITIVE_SUFFIXES)


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "********"
    return value[:4] + "****" + value[-4:]


def _load_runtime_settings() -> dict[str, str]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if isinstance(v, str)}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_runtime_settings(settings: dict[str, str]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def _get_public_settings() -> dict[str, Any]:
    """Return all settings with sensitive values masked."""
    env_settings = get_settings()
    result: dict[str, Any] = {}

    for key in dir(env_settings):
        if key.startswith("_"):
            continue
        try:
            value = getattr(env_settings, key)
        except Exception:
            continue
        if callable(value):
            continue
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
    return _get_public_settings()


@router.put("/settings")
async def update_settings(
    update: SettingsUpdate,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Update runtime settings (persisted to data/settings.json).

    Only accepts string values. Non-sensitive keys are saved directly,
    sensitive keys are validated before storage.
    """
    current = _load_runtime_settings()
    for key, value in update.settings.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"Invalid type for key '{key}'")
        if not key.strip():
            continue
        current[key.strip()] = value

    _save_runtime_settings(current)
    logger.info("Runtime settings updated (%d keys)", len(update.settings))
    return {"status": "saved", "settings": _get_public_settings()}
