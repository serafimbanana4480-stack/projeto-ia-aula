"""Bound and redact the additional child-tool details recorded in run journals.

This is a best-effort filter, not a detector for every possible secret. Files
with credential-shaped names receive a stronger rule: their tool results are
not copied into the activity journal at all.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from backend.observability.logging_config import REDACTION, is_secret_key_name, redact_text

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----[\s\S]*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE,
)
_URL_USERINFO = re.compile(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@")
_MAX_TEXT = 8_000
_MAX_ITEMS = 100
_MAX_DEPTH = 6


def redact_activity(value: Any, *, depth: int = 0) -> Any:
    """Return a JSON-compatible, bounded copy for display and persistence."""
    if depth >= _MAX_DEPTH:
        return "[detalhe omitido: profundidade]"
    if isinstance(value, str):
        text = _PRIVATE_KEY.sub(REDACTION, value)
        text = _URL_USERINFO.sub(r"\1" + REDACTION + "@", text)
        text = redact_text(text)
        return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + "\n[truncado]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:_MAX_ITEMS]:
            name = str(key)
            result[name] = (
                REDACTION if is_secret_key_name(name) or name.lower() in {"authorization", "cookie"}
                else redact_activity(item, depth=depth + 1)
            )
        if len(value) > _MAX_ITEMS:
            result["_truncated"] = True
        return result
    if isinstance(value, (list, tuple)):
        result_list = [redact_activity(item, depth=depth + 1) for item in value[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            result_list.append("[itens adicionais omitidos]")
        return result_list
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_activity(str(value), depth=depth + 1)


def is_sensitive_file_request(args: dict[str, Any]) -> bool:
    """Do not journal the content of common credential files."""
    paths: list[str] = []
    for key in ("path", "file_path", "filename", "file", "paths", "files"):
        value = args.get(key)
        if isinstance(value, str):
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(item for item in value if isinstance(item, str))
    for value in paths:
        name = PurePosixPath(value.replace("\\", "/")).name.lower()
        if (name == ".env" or name.startswith(".env.") or
                name.endswith((".pem", ".key", ".p12", ".pfx", ".keystore")) or
                name in {"credentials", "credentials.json", "id_rsa", "id_ed25519"}):
            return True
    return False
