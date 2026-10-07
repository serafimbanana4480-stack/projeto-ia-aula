"""Encrypted-at-rest storage for ``data/settings.json`` (audit 2026-08-24, B7).

API keys used to be persisted as plaintext JSON. This module wraps the file
I/O with transparent, symmetric encryption.

Ciphertext format
-----------------
``enc:v1:<fernet-token>``
    Legacy. Key = ``base64url(sha256(SECRET_KEY))``. No associated data.
``enc:v2:<fernet-token>``
    Current. Key = ``base64url(scrypt(SECRET_KEY, salt=<persisted random salt>))``
    and the settings *key name* is bound in as Fernet **AAD**, so a ciphertext
    cannot be moved between fields (or between files) without detection.
    ``scrypt`` is a memory-hard KDF, so a stolen ``data/settings.json`` no
    longer yields provider keys by GPU/CPU brute force the way a bare SHA-256
    did.

``enc:v1:`` stays **readable** forever. Migration is explicit — see
:func:`migrate_settings_file` — because the audit forbade silently rewriting the
operator's live settings file.

What this module refuses to do (audit P1-4)
-------------------------------------------
* **Fail open.**  The previous ``encrypt_value`` returned the *plaintext* when
  ``cryptography`` was missing or on any exception, i.e. a broken dependency
  silently downgraded every secret to cleartext.  It now raises
  :class:`EncryptionUnavailableError`.
* **Lose the distinction between "wrong key" and "no value"**.
  :func:`decrypt_value` returns ``""`` for both, so a rotated ``SECRET_KEY``
  made every API key look "not configured" with only a ``logger.error``.
  :func:`decrypt_value_detailed` distinguishes them.
* **Write a masked value back as a credential.**  :func:`looks_masked` is
  exported and used by the settings API.

The KDF salt is persisted next to the settings file (never inside it) so that
repairing ``secret_key`` through the UI cannot orphan the 8 existing
``enc:v1:`` values.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.core.sensitive_keys import (
    SENSITIVE_KEYS,
    SENSITIVE_SUFFIXES,
    is_sensitive_key,
)

logger = logging.getLogger(__name__)

PREFIX_V1 = "enc:v1:"
PREFIX_V2 = "enc:v2:"

#: Re-exported so callers have a single import for the canonical rule.
SENSITIVE_KEY_NAMES = SENSITIVE_KEYS
SENSITIVE_KEY_SUFFIXES = SENSITIVE_SUFFIXES

#: scrypt parameters.  ``n=2**15, r=8, p=1`` costs ~32 MiB and ~50-100 ms per
#: derivation — expensive for an attacker with a dictionary of SECRET_KEYs,
#: negligible for a handful of writes at startup.
SCRYPT_N = 1 << 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32

#: Default location of the KDF salt: a sibling of ``data/settings.json``.
SALT_FILENAME = ".settings_kdf_salt"

_salt_lock = threading.Lock()

#: ``{resolved salt path: salt bytes}`` for the process lifetime.  See
#: :func:`_load_or_create_salt` for why the file is not re-read every time.
_SALT_CACHE: dict[str, bytes] = {}


class EncryptionUnavailableError(RuntimeError):
    """The crypto backend or ``SECRET_KEY`` is unusable.

    Raised instead of writing plaintext.  Callers must surface it (HTTP 503)
    rather than degrade silently.
    """


class SettingsDecryptionError(RuntimeError):
    """A ciphertext exists but could not be decrypted with the current key.

    Distinguishes "wrong key / corrupted value" from "no value stored".
    """

    def __init__(self, message: str, *, key_name: str = "", prefix: str = "") -> None:
        super().__init__(message)
        self.key_name = key_name
        self.prefix = prefix


@dataclass
class DecryptResult:
    """Outcome of decrypting one stored value."""

    value: str
    #: ``"plaintext"`` | ``"v1"`` | ``"v2"`` | ``"undecryptable"``
    kind: str
    error: str = ""
    needs_migration: bool = False


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------
def _secret_key() -> str:
    from backend.config.settings import get_settings

    secret = str(getattr(get_settings(), "secret_key", "") or "")
    if not secret:
        raise EncryptionUnavailableError(
            "SECRET_KEY is empty; refusing to encrypt or decrypt settings secrets"
        )
    return secret


#: Length of the persisted KDF salt.  A salt whose length differs is corrupt:
#: silently accepting it would make the derived key depend on how much of the
#: file happened to parse as salt.
SALT_BYTES = 32


def _load_or_create_salt(salt_path: Path) -> bytes:
    """Read the persisted KDF salt, creating it (0600) on first use.

    The salt is cached per resolved path for the process lifetime.  Re-reading
    the file on every single encrypt/decrypt is both wasteful and fragile: a
    truncated or partially-written read would derive a *different* key from the
    one that produced the ciphertext, and every ``enc:v2:`` value would become
    unreadable with no way to tell why.
    """
    key = str(salt_path)
    cached = _SALT_CACHE.get(key)
    if cached is not None:
        return cached

    salt = _read_or_create_salt_uncached(salt_path)
    with _salt_lock:
        _SALT_CACHE.setdefault(key, salt)
        return _SALT_CACHE[key]


def _read_or_create_salt_uncached(salt_path: Path) -> bytes:
    try:
        raw = salt_path.read_bytes()
    except OSError:
        raw = b""
    if len(raw) == SALT_BYTES:
        return raw
    if raw:
        raise EncryptionUnavailableError(
            f"KDF salt file {salt_path.name} is {len(raw)} bytes, expected "
            f"{SALT_BYTES}. Refusing to guess: a different salt would make every "
            "enc:v2: value undecryptable. Restore the file from backup or delete "
            "it to mint a new one (v1 values are unaffected)."
        )
    with _salt_lock:
        try:
            existing = salt_path.read_bytes()
        except OSError:
            existing = b""
        if len(existing) == SALT_BYTES:
            return existing
        salt = secrets.token_bytes(SALT_BYTES)
        salt_path.parent.mkdir(parents=True, exist_ok=True)
        # Write via a temp file + atomic replace: a crash (or a concurrent
        # reader) must never observe a half-written salt.
        tmp = salt_path.with_name(salt_path.name + ".new")
        # Create with restrictive permissions where the platform allows it.
        fd = os.open(
            str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
        )
        try:
            os.write(fd, salt)
        finally:
            os.close(fd)
        os.replace(tmp, salt_path)
        logger.info("Created settings KDF salt at %s", salt_path)
        return salt


def _scrypt_key(secret: str, salt: bytes) -> bytes:
    derived = hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=256 * 1024 * 1024,
    )
    return base64.urlsafe_b64encode(derived)


def _v1_key(secret: str) -> Any:
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _v2_key(secret: str, salt_path: Path | None = None) -> Any:
    from cryptography.fernet import Fernet

    salt = _load_or_create_salt(salt_path or default_salt_path())
    return Fernet(_scrypt_key(secret, salt))


def default_salt_path() -> Path:
    """Where the KDF salt lives (sibling of ``data/settings.json``)."""
    override = os.environ.get("NEXUS_SETTINGS_SALT_FILE", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data" / SALT_FILENAME


def _fernet(version: int = 2, *, salt_path: Path | None = None) -> Any:
    """Return a Fernet instance, or raise :class:`EncryptionUnavailableError`.

    Note this **raises**; the historical "return None and write plaintext"
    behaviour is what put a cleartext ``secret_key`` on disk.
    """
    try:
        secret = _secret_key()
    except EncryptionUnavailableError:
        raise
    except Exception as exc:  # pragma: no cover - settings import failure
        raise EncryptionUnavailableError(f"Could not read SECRET_KEY: {exc}") from exc
    try:
        if version == 1:
            return _v1_key(secret)
        return _v2_key(secret, salt_path)
    except ImportError as exc:
        raise EncryptionUnavailableError(
            "The 'cryptography' package is required to protect settings secrets. "
            "Refusing to write them in cleartext."
        ) from exc
    except EncryptionUnavailableError:
        raise
    except Exception as exc:  # pragma: no cover - misconfigured salt/KDF
        raise EncryptionUnavailableError(f"Crypto backend unavailable: {exc}") from exc


def assert_crypto_backend() -> None:
    """Startup assertion: the crypto backend and SECRET_KEY must be usable.

    Called from the settings module so a deployment with a broken
    ``cryptography`` install or an empty ``SECRET_KEY`` fails loudly at import
    time instead of writing cleartext on the first ``PUT /api/settings``.
    """
    _fernet_or_raise(2)
    # Cheap self-test: encrypt/decrypt must round-trip, otherwise refuse.
    token = encrypt_value("nexus-crypto-self-test", key_name="__self_test__")
    if decrypt_value_detailed(token, key_name="__self_test__").value != "nexus-crypto-self-test":
        raise EncryptionUnavailableError("Settings crypto self-test failed (round-trip mismatch)")


# ---------------------------------------------------------------------------
# Value encryption / decryption
# ---------------------------------------------------------------------------
#: Separates the bound key name from the secret inside the ciphertext.
_AAD_SEP = b"\x00"


def _aad(key_name: str | None) -> bytes | None:
    if not key_name:
        return None
    return f"nexus-settings:{key_name}".encode()


def _fernet_supports_aad() -> bool:
    """Whether the installed ``cryptography`` exposes Fernet's ``a=`` parameter."""
    global _FERNET_SUPPORTS_AAD
    if _FERNET_SUPPORTS_AAD is None:
        try:
            import inspect

            from cryptography.fernet import Fernet

            _FERNET_SUPPORTS_AAD = "a" in inspect.signature(Fernet.encrypt).parameters
        except Exception:  # pragma: no cover - crypto missing
            _FERNET_SUPPORTS_AAD = False
    return _FERNET_SUPPORTS_AAD


_FERNET_SUPPORTS_AAD: bool | None = None


def _bind(key_name: str | None, plain: bytes) -> bytes:
    """Bind *key_name* to the plaintext so the ciphertext cannot be relocated.

    The installed ``cryptography`` build (49.0.0) has no Fernet ``a=``
    parameter, so the binding is done by placing the key name inside the
    authenticated ciphertext.  That is equivalent for this purpose: Fernet's
    HMAC authenticates the whole token, so moving a ciphertext to another field
    makes the prefix check fail.  When the library *does* support ``a=`` the
    value is passed as real associated data as well, so the binding holds under
    both mechanisms.
    """
    if not key_name:
        return plain
    return key_name.encode("utf-8") + _AAD_SEP + plain


def _unbind(key_name: str | None, blob: bytes) -> bytes:
    if not key_name:
        return blob
    prefix = key_name.encode("utf-8") + _AAD_SEP
    if not blob.startswith(prefix):
        raise SettingsDecryptionError(
            "ciphertext is not bound to this settings key (moved between fields?)",
            key_name=key_name,
        )
    return blob[len(prefix) :]


def _encrypt_with_binding(
    fernet: Any, plain: str, key_name: str | None
) -> str:
    blob = _bind(key_name, plain.encode("utf-8"))
    aad = _aad(key_name)
    if aad is not None and _fernet_supports_aad():
        token = fernet.encrypt(blob, aad)
    else:
        token = fernet.encrypt(blob)
    return token.decode("ascii")


def _decrypt_with_binding(
    fernet: Any, token: bytes, key_name: str | None
) -> str:
    aad = _aad(key_name)
    if aad is not None and _fernet_supports_aad():
        try:
            blob = fernet.decrypt(token, aad)
        except TypeError:  # pragma: no cover - older signature
            blob = fernet.decrypt(token)
    else:
        blob = fernet.decrypt(token)
    return _unbind(key_name, blob).decode("utf-8")


def encrypt_value(
    plain: str,
    *,
    key_name: str | None = None,
    salt_path: Path | None = None,
) -> str:
    """Encrypt *plain* as ``enc:v2:``.

    Args:
        plain: the secret value.
        key_name: settings key name.  When given, the ciphertext is bound to it
            so it cannot be relocated to another field.
        salt_path: override for the KDF salt (tests).

    Raises:
        EncryptionUnavailableError: never returns plaintext.
    """
    fernet = _fernet_or_raise(2, salt_path=salt_path)
    return PREFIX_V2 + _encrypt_with_binding(fernet, plain, key_name)


def _fernet_or_raise(version: int = 2, *, salt_path: Path | None = None) -> Any:
    """``_fernet`` with a total guarantee of :class:`EncryptionUnavailableError`.

    Fail *closed* means every failure mode is the typed error, not just the ones
    we anticipated: a caller catching ``EncryptionUnavailableError`` must never
    be surprised by a bare ``ImportError``/``TypeError`` — and, more to the
    point, no code path can end up returning the plaintext.
    """
    try:
        return _fernet(version, salt_path=salt_path)
    except EncryptionUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 — the point is to normalise *all* of them
        raise EncryptionUnavailableError(
            f"Settings crypto backend unavailable: {type(exc).__name__}: {exc}"
        ) from exc


def encrypt_value_v1(plain: str) -> str:
    """Encrypt with the *legacy* v1 scheme. Test/migration helper only."""
    return PREFIX_V1 + _fernet(1).encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_value_detailed(
    value: str,
    *,
    key_name: str | None = None,
    salt_path: Path | None = None,
) -> DecryptResult:
    """Decrypt one stored value, reporting *how* it was stored.

    ``enc:v1:`` is decrypted with the legacy key (no AAD) and flagged
    ``needs_migration``; ``enc:v2:`` is decrypted with the scrypt key and the
    key name as AAD.  An undecryptable ciphertext yields
    ``DecryptResult(value="", kind="undecryptable", error=...)`` **and** raises
    nothing — callers decide; :func:`decrypt_value` is the strict variant.
    """
    if not isinstance(value, str) or not value:
        return DecryptResult(value=value if isinstance(value, str) else "", kind="plaintext")
    if value.startswith(PREFIX_V2):
        version, token = 2, value[len(PREFIX_V2) :]
    elif value.startswith(PREFIX_V1):
        version, token = 1, value[len(PREFIX_V1) :]
    else:
        return DecryptResult(value=value, kind="plaintext")

    try:
        fernet = _fernet_or_raise(version, salt_path=salt_path)
    except EncryptionUnavailableError as exc:
        return DecryptResult(value="", kind="undecryptable", error=str(exc))

    try:
        if version == 1:
            # v1 was written without any binding; try with it anyway in case a
            # newer writer downgraded, but never *require* it.
            try:
                plain = _decrypt_with_binding(fernet, token.encode("ascii"), key_name)
            except Exception:
                plain = fernet.decrypt(token.encode("ascii")).decode("utf-8")
            return DecryptResult(
                value=plain,
                kind="v1",
                needs_migration=True,
            )
        plain = _decrypt_with_binding(fernet, token.encode("ascii"), key_name)
        return DecryptResult(value=plain, kind="v2")
    except EncryptionUnavailableError as exc:  # pragma: no cover - defensive
        return DecryptResult(value="", kind="undecryptable", error=str(exc))
    except SettingsDecryptionError as exc:
        return DecryptResult(value="", kind="undecryptable", error=str(exc))
    except Exception as exc:
        reason = type(exc).__name__
        hint = "wrong SECRET_KEY (rotated?) or corrupted value"
        return DecryptResult(
            value="",
            kind="undecryptable",
            error=f"{hint}: {reason}",
        )


def decrypt_value(value: str, *, key_name: str | None = None) -> str:
    """Decrypt ``enc:v1:``/``enc:v2:`` values; anything else passes through.

    Raises:
        SettingsDecryptionError: a stored ciphertext could not be decrypted.
            The previous behaviour returned ``""`` with a ``logger.error``,
            which made a rotated ``SECRET_KEY`` look like "every provider is
            simply not configured".
        EncryptionUnavailableError: no usable crypto backend.
    """
    result = decrypt_value_detailed(value, key_name=key_name)
    if result.kind == "undecryptable":
        raise SettingsDecryptionError(
            f"Stored settings secret could not be decrypted ({result.error}). "
            "It is NOT the same as 'not configured' — restore the original "
            "SECRET_KEY or re-enter the credential.",
            key_name=key_name or "",
            prefix=PREFIX_V2 if value.startswith(PREFIX_V2) else PREFIX_V1,
        )
    return result.value


def looks_masked(value: str) -> bool:
    """Whether *value* is a mask produced by the settings API, not a credential.

    Recognises exactly the two stable shapes the API emits (``********`` and
    ``abcd****wxyz``).  Saving one of these as a secret replaces a working
    credential with a string that can never authenticate.
    """
    candidate = str(value).strip()
    if not candidate:
        return False
    if candidate == "********":
        return True
    return (
        len(candidate) >= 12
        and candidate[4:8] == "****"
        and "*" not in candidate[:4]
        and "*" not in candidate[8:]
    )


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------
def load_settings(
    path: Path | str,
    *,
    salt_path: Path | None = None,
    strict: bool = False,
    migrate: bool = False,
) -> dict[str, Any]:
    """Load settings JSON with sensitive values decrypted.

    Args:
        path: settings file.
        salt_path: override for the KDF salt (tests).
        strict: raise :class:`SettingsDecryptionError` on an undecryptable
            value instead of returning ``""``.
        migrate: re-encrypt ``enc:v1:`` values as ``enc:v2:`` and write the
            file back.  **Off by default** so a load never mutates the
            operator's live settings; see :func:`migrate_settings_file`.
    """
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}

    out: dict[str, Any] = {}
    changed = False
    for key, value in raw.items():
        if isinstance(value, str) and is_sensitive_key(key):
            result = decrypt_value_detailed(value, key_name=key, salt_path=salt_path)
            if result.kind == "undecryptable":
                logger.error(
                    "Settings key %r holds a %s ciphertext that cannot be decrypted (%s). "
                    "It is NOT 'not configured' — restore the original SECRET_KEY or "
                    "re-enter the value.",
                    key,
                    PREFIX_V2 if value.startswith(PREFIX_V2) else PREFIX_V1,
                    result.error,
                )
                if strict:
                    raise SettingsDecryptionError(
                        f"Cannot decrypt settings key {key!r}: {result.error}",
                        key_name=key,
                    )
            out[key] = result.value
            if migrate and result.needs_migration and result.value:
                out[key] = result.value
                changed = True
        else:
            out[key] = value

    if migrate and changed:
        try:
            _write_settings(file_path, raw, out, salt_path=salt_path)
        except OSError as exc:  # pragma: no cover - read-only data dir
            logger.error("Could not persist settings migration: %s", exc)
    return out


def save_settings(
    path: Path | str,
    data: dict[str, Any],
    *,
    salt_path: Path | None = None,
) -> None:
    """Save settings JSON with sensitive values encrypted at rest (``enc:v2:``).

    Refuses to write a masked value: a mask is a display artefact, not a
    credential, and storing one silently breaks the provider.

    Raises:
        EncryptionUnavailableError: the crypto backend is unusable.  There is
            no plaintext fallback.
        ValueError: a masked value was supplied for a sensitive key.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    salt_path = salt_path or default_salt_path()
    payload: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str) and value and is_sensitive_key(key):
            if looks_masked(value):
                raise ValueError(
                    f"Refusing to store a masked value for sensitive key {key!r}; "
                    "send the real secret."
                )
            payload[key] = encrypt_value(value, key_name=key, salt_path=salt_path)
        else:
            payload[key] = value
    _write_settings(file_path, payload, None, salt_path=salt_path)


def _write_settings(
    file_path: Path,
    raw: dict[str, Any],
    decrypted: dict[str, Any] | None,
    *,
    salt_path: Path | None = None,
) -> None:
    """Atomic write of *raw* (already-encrypted) values."""
    if decrypted:
        payload = dict(raw)
        for key, value in decrypted.items():
            stored = raw.get(key)
            if (
                isinstance(value, str)
                and value
                and isinstance(stored, str)
                and stored.startswith((PREFIX_V1, PREFIX_V2))
            ):
                payload[key] = encrypt_value(value, key_name=key, salt_path=salt_path)
    else:
        payload = raw
    tmp = file_path.with_suffix(file_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, file_path)


# ---------------------------------------------------------------------------
# Operator-triggered migration
# ---------------------------------------------------------------------------
@dataclass
class MigrationReport:
    """Outcome of :func:`migrate_settings_file`."""

    total_sensitive: int = 0
    already_v2: int = 0
    migrated: list[str] = field(default_factory=list)
    plaintext: list[str] = field(default_factory=list)
    undecryptable: list[str] = field(default_factory=list)
    dry_run: bool = True
    written: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sensitive": self.total_sensitive,
            "already_v2": self.already_v2,
            "migrated": sorted(self.migrated),
            "plaintext": sorted(self.plaintext),
            "undecryptable": sorted(self.undecryptable),
            "dry_run": self.dry_run,
            "written": self.written,
        }


def migrate_settings_file(
    path: Path | str,
    *,
    dry_run: bool = True,
    salt_path: Path | None = None,
) -> MigrationReport:
    """Re-encrypt ``enc:v1:`` values as ``enc:v2:`` (KDF + AAD).

    Deliberately **operator-triggered** and ``dry_run`` by default: the audit
    forbade rewriting the live ``data/settings.json`` behind the operator's
    back.  The shipped file therefore keeps working unchanged — v1 remains
    readable — until someone runs this explicitly with ``dry_run=False``.

    Never prints or returns any secret material: only key *names* are reported.
    """
    file_path = Path(path)
    report = MigrationReport(dry_run=dry_run)
    if not file_path.exists():
        return report
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read {file_path.name}: {exc}") from exc

    decrypted: dict[str, Any] = {}
    for key, value in raw.items():
        if not (isinstance(value, str) and is_sensitive_key(key)):
            continue
        report.total_sensitive += 1
        if value.startswith(PREFIX_V2):
            report.already_v2 += 1
            continue
        if not value.startswith(PREFIX_V1):
            report.plaintext.append(key)
            continue
        result = decrypt_value_detailed(value, key_name=key, salt_path=salt_path)
        if result.kind == "undecryptable":
            report.undecryptable.append(key)
            logger.error(
                "Cannot migrate %r: %s. Restore the original SECRET_KEY first.",
                key,
                result.error,
            )
            continue
        decrypted[key] = result.value
        report.migrated.append(key)

    if dry_run or not decrypted:
        return report
    _write_settings(file_path, raw, decrypted, salt_path=salt_path)
    report.written = True
    logger.info(
        "Migrated %d settings secret(s) from %s to %s",
        len(decrypted),
        PREFIX_V1,
        PREFIX_V2,
    )
    return report


def drop_masked_secrets(
    path: Path | str,
    *,
    dry_run: bool = True,
) -> list[str]:
    """Remove sensitive keys whose stored value is a *mask*, not a credential.

    ``data/settings.json`` shipped with ``"secret_key": "ldph****ulvE"`` — a
    display mask written through an older revision of the settings API.  It is
    not a usable secret, and because the Fernet key is derived from
    ``SECRET_KEY`` it also means every ``enc:v1:`` value would stop decrypting
    if an operator "fixed" it through the UI.

    Removing the entry is safe: the app then falls back to the ``SECRET_KEY``
    from ``.env``/environment, which is what actually derives the keys today.
    Operator-triggered and ``dry_run`` by default, like
    :func:`migrate_settings_file`.

    Returns the key names that are (or would be) dropped.
    """
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read {file_path.name}: {exc}") from exc

    dropped = [
        key
        for key, value in raw.items()
        if isinstance(value, str) and is_sensitive_key(key) and looks_masked(value)
    ]
    if dry_run or not dropped:
        if dropped:
            logger.warning(
                "Masked settings secret(s) present in %s: %s — run with dry_run=False to drop them",
                file_path.name,
                ", ".join(sorted(dropped)),
            )
        return dropped

    payload = {key: value for key, value in raw.items() if key not in set(dropped)}
    _write_settings(file_path, payload, None)
    logger.info("Dropped masked settings secret(s): %s", ", ".join(sorted(dropped)))
    return dropped


def undecryptable_keys(
    path: Path | str,
    *,
    salt_path: Path | None = None,
) -> list[str]:
    """Key names stored as ciphertext that the current SECRET_KEY cannot read.

    Lets the settings API refuse a write instead of silently rebuilding an LLM
    client from an empty credential set (the P1-4 cascade: rotate SECRET_KEY →
    every API key becomes "not configured" with no visible error).
    """
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    broken: list[str] = []
    for key, value in raw.items():
        if not (isinstance(value, str) and is_sensitive_key(key)):
            continue
        if not value.startswith((PREFIX_V1, PREFIX_V2)):
            continue
        if decrypt_value_detailed(value, key_name=key, salt_path=salt_path).kind == "undecryptable":
            broken.append(key)
    return broken


def constant_time_equals(left: str, right: str) -> bool:
    """hmac.compare_digest wrapper (used by callers comparing key material)."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
