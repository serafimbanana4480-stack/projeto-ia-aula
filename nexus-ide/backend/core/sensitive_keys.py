"""Canonical definition of *which settings keys are secrets*.

Audit P1-4 found two divergent definitions in the codebase:

* ``backend/orchestrator/routes/settings.py`` listed 11 explicit names
  **including** ``secret_key`` plus a suffix list, and used it to decide what to
  mask in ``GET /api/settings``;
* ``backend/core/secure_settings_store.py`` had only the suffix list, so
  ``is_sensitive_key("secret_key")`` was **False** (``"secret_key".endswith(
  "api_key"|"secret"|"password"|"token")`` is false for all four) and
  ``SECRET_KEY`` was written to ``data/settings.json`` in cleartext while every
  other credential was ``enc:v1:``.

A mask/encrypt decision that depends on which module you ask is a vulnerability,
so this module is now the only place the rule lives.  Both call sites import
from here:

* masking in the settings API — a secret must be masked, always;
* encryption at rest — a secret must be encrypted, always.

The rule is deliberately **inclusive**: the suffix patterns are the historical
behaviour (so nothing that used to be protected becomes exposed) and the exact
names cover the ones the suffix rule provably missed.  Adding a credential means
adding it here once.
"""

from __future__ import annotations

import re

#: Suffix patterns.  Historical behaviour of ``is_sensitive_key``; kept intact
#: so the change is strictly additive.
SENSITIVE_SUFFIXES: tuple[str, ...] = ("api_key", "secret", "password", "token")

#: Exact key names.  ``secret_key`` is the important one: it is the key the
#: Fernet key itself is derived from and it matched none of the suffixes above.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "secret_key",
        "jwt_secret",
        "redis_password",
        "encryption_key",
        "master_key",
        "signing_key",
        "fernet_key",
        "encryption_salt",
        "admin_password",
        "db_password",
        "brave_api_key",
    }
)

#: Keys that look secret by the suffix rules but are counters/knobs.  Without
#: this, ``max_tokens=2048`` and ``input_tokens=1500`` would be encrypted at
#: rest, which would be both useless and destructive.
NON_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "allow_credentials",
        "key_id",
        "key_ids",
        "key_func",
        "token_counter",
        "tokens",
    }
)

_NON_SECRET_PATTERNS: tuple[str, ...] = (
    r"(?:^|[_\-.])per(?:[_\-.]|$)",
    (
        r"(?:^|[_\-.])(?:max|min|total|num|count|counter|used|remaining|left"
        r"|input|output|prompt|completion|cached|cache|reasoning|budget|limit|limits"
        r"|avg|average|estimated|estimate|active|before|final|alt|new|effective"
        r"|default|history|since|per)(?:[_\-.]|$)"
    ),
)

#: Name shapes that contain a secret-ish word but are counters/units.  Without
#: these, ``cost_per_token=0.003`` and ``chars_per_token=4`` — the two most
#: useful numbers in a spend log — would be encrypted at rest.
_NON_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:^|[_\-.])per(?:[_\-.]|$)"),
    re.compile(
        r"(?:^|[_\-.])(?:max|min|total|num|count|counter|used|remaining|left"
        r"|input|output|prompt|completion|cached|cache|reasoning|budget|limit|limits"
        r"|avg|average|estimated|estimate|active|before|final|alt|new|effective"
        r"|default|history|since|per)(?:[_\-.]|$)"
    ),
)

_SEGMENT_RULES = (
    frozenset(
        {
            "secret",
            "secrets",
            "password",
            "passwd",
            "pwd",
            "passphrase",
            "credential",
            "credentials",
            "apikey",
        }
    ),
    frozenset({"key", "keys"}),
    frozenset({"api", "access", "private", "secret"}),
)


def is_sensitive_key(key: str) -> bool:
    """Whether *key* names a credential that must be masked and encrypted.

    Segment-based rather than a bare ``endswith``: ``secret_key`` must be
    sensitive while ``max_tokens``/``input_tokens``/``cost_per_token`` must not.
    """
    name = str(key).strip().strip("\"'").lower()
    if not name:
        return False
    if name in NON_SENSITIVE_KEYS:
        return False
    if any(pattern.search(name) for pattern in _NON_SENSITIVE_PATTERNS):
        return False
    if name in SENSITIVE_KEYS:
        return True
    segments = {
        part for part in name.replace("-", "_").replace(".", "_").split("_") if part
    }
    if name.endswith(SENSITIVE_SUFFIXES):
        # ``tokens``/``max_tokens`` are counters; a *singular* ``token`` or an
        # explicit credential word is not.
        if _SEGMENT_RULES[0] & segments:
            return True
        if name.endswith("token"):
            return True
    if _SEGMENT_RULES[0] & segments:
        return True
    return bool(_SEGMENT_RULES[1] & segments and _SEGMENT_RULES[2] & segments)


def assert_sensitive_keys_cover(*keys: str) -> None:
    """Startup assertion helper: raise if a credential is not classified.

    Used by :func:`backend.core.secure_settings_store.assert_crypto_backend`
    together with a small list of names that must never be written in cleartext.
    """
    missing = [key for key in keys if not is_sensitive_key(key)]
    if missing:
        raise AssertionError(
            "These credential-shaped keys are not classified as sensitive by "
            f"backend.core.sensitive_keys: {sorted(missing)}"
        )
