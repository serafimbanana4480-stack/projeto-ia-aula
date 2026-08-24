"""Encrypted-at-rest storage for ``data/settings.json`` (audit 2026-08-24, B7).

API keys used to be persisted as plaintext JSON. This module wraps the file
I/O with transparent, symmetric encryption:

* Sensitive values are stored as ``enc:v1:<fernet-token>``.
* The Fernet key is derived from the application ``SECRET_KEY`` via SHA-256,
  so no extra secret needs managing; rotating SECRET_KEY invalidates stored
  ciphertexts (operators must re-enter keys — acceptable and documented).
* Reading accepts both encrypted **and** legacy plaintext values, so existing
  files keep working and are re-encrypted on the next save.

Design constraint: this must NEVER break settings loading. If
``cryptography`` is unavailable or decryption fails, values fall back to
their raw form with a warning instead of raising.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"
_SENSITIVE_SUFFIXES = ("api_key", "secret", "password", "token")


def is_sensitive_key(key: str) -> bool:
    key_lower = key.lower()
    return any(key_lower.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES)


def _fernet():
    try:
        from cryptography.fernet import Fernet

        from backend.config.settings import get_settings

        secret = str(getattr(get_settings(), "secret_key", "") or "")
        if not secret:
            raise ValueError("SECRET_KEY is empty")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))
    except Exception:  # noqa: BLE001 — never break settings I/O on crypto issues
        logger.warning("Encriptação de indisponível; a gravar em texto claro")
        return None


def encrypt_value(plain: str) -> str:
    f = _fernet()
    if f is None:
        return plain
    try:
        return _PREFIX + f.encrypt(plain.encode("utf-8")).decode("ascii")
    except Exception:  # noqa: BLE001
        logger.warning("Falha ao encriptar valor sensível; a gravar texto claro")
        return plain


def decrypt_value(value: str) -> str:
    """Decrypt ``enc:v1:…`` values; anything else passes through untouched."""
    if not value.startswith(_PREFIX):
        return value
    f = _fernet()
    if f is None:
        logger.error(
            "Valor encriptado encontrado mas criptografia indisponível — "
            "a devolver vazio para não vazar material"
        )
        return ""
    try:
        token = value[len(_PREFIX) :].encode("ascii")
        return f.decrypt(token).decode("utf-8")
    except Exception:  # noqa: BLE001 — wrong SECRET_KEY or corrupted value
        logger.error(
            "Não foi possível desencriptar um valor de settings "
            "(SECRET_KEY mudou?): devolve vazio."
        )
        return ""


def load_settings(path: Path | str) -> dict[str, Any]:
    """Load settings JSON with sensitive values decrypted."""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, str) and is_sensitive_key(key):
            out[key] = decrypt_value(value)
        else:
            out[key] = value
    return out


def save_settings(path: Path | str, data: dict[str, Any]) -> None:
    """Save settings JSON with sensitive values encrypted at rest."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str) and value and is_sensitive_key(key):
            payload[key] = encrypt_value(value)
        else:
            payload[key] = value
    with file_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
