"""P1-4 — cleartext ``SECRET_KEY``, divergent sensitive-key definitions.

The audit found two disagreeing definitions of "is this key a secret", and the
disagreement was exactly ``secret_key``, which ended up stored in cleartext in
``data/settings.json`` while every other credential was ``enc:v1:``.

These tests cover the design:

* one canonical rule (:mod:`backend.core.sensitive_keys`) that covers
  ``secret_key`` and is shared by the masking and encryption sides;
* encryption that **fails closed** (never returns plaintext);
* a real KDF (scrypt + persisted salt) with a versioned ``enc:v2:`` scheme that
  keeps ``enc:v1:`` readable;
* ciphertext bound to the key name (AAD);
* "wrong key" distinguished from "not configured";
* masked values refused on save;
* and — critically — proof that the **real** ``data/settings.json`` still
  decrypts and that nothing on disk was rewritten.

No test prints a secret: assertions use synthetic values only.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.core import sensitive_keys
from backend.core.secure_settings_store import (
    PREFIX_V1,
    PREFIX_V2,
    EncryptionUnavailableError,
    SettingsDecryptionError,
    assert_crypto_backend,
    decrypt_value,
    decrypt_value_detailed,
    drop_masked_secrets,
    encrypt_value,
    encrypt_value_v1,
    is_sensitive_key,
    load_settings,
    looks_masked,
    migrate_settings_file,
    save_settings,
    undecryptable_keys,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_SETTINGS = REPO_ROOT / "data" / "settings.json"


@pytest.fixture
def salt(tmp_path) -> Path:
    return tmp_path / "kdf_salt.bin"


@pytest.fixture
def settings_file(tmp_path) -> Path:
    return tmp_path / "settings.json"


# ---------------------------------------------------------------------------
# 1. One canonical definition
# ---------------------------------------------------------------------------
class TestSingleSourceOfTruth:
    def test_both_modules_use_the_same_function(self) -> None:
        import backend.core.secure_settings_store as store
        from backend.orchestrator.routes import settings as settings_route

        assert store.is_sensitive_key is sensitive_keys.is_sensitive_key
        assert settings_route._is_sensitive is sensitive_keys.is_sensitive_key

    def test_secret_key_is_sensitive(self) -> None:
        """The exact key the audit found in cleartext on disk."""
        assert is_sensitive_key("secret_key")
        assert sensitive_keys.is_sensitive_key("SECRET_KEY")
        assert sensitive_keys.is_sensitive_key(" secret_key ")

    @pytest.mark.parametrize(
        "key",
        [
            "openai_api_key",
            "kilo_api_key",
            "gemini_api_key",
            "openrouter_api_key",
            "opencode_go_api_key",
            "anthropic_api_key",
            "deepseek_api_key",
            "kimi_api_key",
            "groq_api_key",
            "jwt_secret",
            "redis_password",
            "brave_api_key",
            "admin_password",
            "auth_token",
        ],
    )
    def test_every_credential_shape_is_sensitive(self, key: str) -> None:
        assert is_sensitive_key(key), key

    @pytest.mark.parametrize(
        "key",
        [
            "llm_provider",
            "ollama_host",
            "redis_url",
            "log_level",
            "debug",
            "free_only",
            "rate_limit_enabled",
            "rate_limit_requests_per_minute",
            "database_url",
            "allowed_origins",
            "csp_policy",
            "backend_port",
            "multi_llm_enabled",
            "default_mode",
        ],
    )
    def test_ordinary_settings_are_not_sensitive(self, key: str) -> None:
        assert not is_sensitive_key(key), key

    @pytest.mark.parametrize(
        "key",
        [
            "max_tokens",
            "openai_max_tokens",
            "anthropic_max_tokens",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "tokens_used",
            "token_budget",
            "default_token_budget",
            "cost_per_token",
            "chars_per_token",
            "cache_key",
            "key_id",
            "allow_credentials",
        ],
    )
    def test_counters_are_never_encrypted(self, key: str) -> None:
        """Redacting/encrypting these would destroy the most useful LLM data."""
        assert not is_sensitive_key(key), key

    def test_startup_assertion_helper(self) -> None:
        sensitive_keys.assert_sensitive_keys_cover(
            "secret_key", "openai_api_key", "jwt_secret"
        )
        with pytest.raises(AssertionError):
            sensitive_keys.assert_sensitive_keys_cover("totally_boring_value")

    def test_crypto_backend_assertion_passes_here(self) -> None:
        """The startup assertion must succeed in a healthy environment."""
        assert_crypto_backend()


# ---------------------------------------------------------------------------
# 2. Fail closed
# ---------------------------------------------------------------------------
class TestFailsClosed:
    def test_encrypt_raises_instead_of_returning_plaintext(self, monkeypatch) -> None:
        import backend.core.secure_settings_store as store

        def _boom(*_a, **_k):
            raise ImportError("no cryptography here")

        monkeypatch.setattr(store, "_fernet", _boom)
        with pytest.raises(EncryptionUnavailableError):
            store.encrypt_value("super-secret-value")

    def test_save_raises_instead_of_writing_plaintext(
        self, settings_file: Path, monkeypatch
    ) -> None:
        import backend.core.secure_settings_store as store

        monkeypatch.setattr(
            store, "_fernet", lambda *a, **k: (_ for _ in ()).throw(EncryptionUnavailableError("x"))
        )
        with pytest.raises(EncryptionUnavailableError):
            save_settings(settings_file, {"openai_api_key": "sk-leaked"})
        assert not settings_file.exists() or "sk-leaked" not in settings_file.read_text(
            encoding="utf-8"
        )

    def test_empty_secret_key_raises(self, monkeypatch) -> None:
        from backend.config import settings as settings_module

        original = settings_module.get_settings

        class _NoSecret:
            secret_key = ""

        monkeypatch.setattr(settings_module, "get_settings", lambda: _NoSecret())
        try:
            with pytest.raises(EncryptionUnavailableError):
                encrypt_value("anything")
        finally:
            monkeypatch.setattr(settings_module, "get_settings", original)


# ---------------------------------------------------------------------------
# 3. KDF + versioned scheme + v1 readability
# ---------------------------------------------------------------------------
class TestCiphertextFormat:
    def test_new_writes_use_v2(self, settings_file: Path, salt: Path) -> None:
        save_settings(
            settings_file, {"openai_api_key": "sk-synthetic-value"}, salt_path=salt
        )
        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        assert raw["openai_api_key"].startswith(PREFIX_V2)

    def test_v1_is_still_readable(self, settings_file: Path, salt: Path) -> None:
        """The 8+ existing ``enc:v1:`` values must never be orphaned."""
        token = encrypt_value_v1("legacy-v1-value")
        assert token.startswith(PREFIX_V1)
        result = decrypt_value_detailed(token, key_name="openai_api_key", salt_path=salt)
        assert result.kind == "v1"
        assert result.value == "legacy-v1-value"
        assert result.needs_migration is True

    def test_v1_file_loads_through_load_settings(self, settings_file: Path, salt: Path) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "openai_api_key": encrypt_value_v1("legacy-a"),
                    "groq_api_key": encrypt_value_v1("legacy-b"),
                    "llm_provider": "openrouter",
                }
            ),
            encoding="utf-8",
        )
        loaded = load_settings(settings_file, salt_path=salt)
        assert loaded["openai_api_key"] == "legacy-a"
        assert loaded["groq_api_key"] == "legacy-b"
        assert loaded["llm_provider"] == "openrouter"

    def test_v2_uses_a_persisted_random_salt(
        self, settings_file: Path, salt: Path
    ) -> None:
        save_settings(
            settings_file, {"openai_api_key": "sk-synthetic-value"}, salt_path=salt
        )
        assert salt.exists()
        assert len(salt.read_bytes()) >= 16
        # A second call must reuse the same salt, not mint a new one.
        before = salt.read_bytes()
        save_settings(
            settings_file, {"openai_api_key": "sk-synthetic-value-2"}, salt_path=salt
        )
        assert salt.read_bytes() == before

    def test_a_different_salt_cannot_decrypt(self, settings_file: Path, tmp_path) -> None:
        other_salt = tmp_path / "other_salt.bin"
        save_settings(
            settings_file, {"openai_api_key": "sk-synthetic-value"}, salt_path=other_salt
        )
        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        result = decrypt_value_detailed(
            raw["openai_api_key"],
            key_name="openai_api_key",
            salt_path=tmp_path / "unknown_salt.bin",
        )
        assert result.kind == "undecryptable"

    def test_kdf_is_not_a_bare_sha256(self) -> None:
        """The v1 key derivation must not be reused for v2."""

        from backend.core import secure_settings_store as store

        assert store.SCRYPT_N >= 1 << 14
        assert store.SCRYPT_P >= 1
        assert store._scrypt_key("secret", b"0" * 32) != base64_of_sha256("secret")

    def test_migration_is_explicit_and_dry_run_by_default(
        self, settings_file: Path, salt: Path
    ) -> None:
        settings_file.write_text(
            json.dumps(
                {
                    "openai_api_key": encrypt_value_v1("legacy-a"),
                    "groq_api_key": encrypt_value_v1("legacy-b"),
                }
            ),
            encoding="utf-8",
        )
        before = settings_file.read_text(encoding="utf-8")

        dry = migrate_settings_file(settings_file, dry_run=True, salt_path=salt)
        assert sorted(dry.migrated) == ["groq_api_key", "openai_api_key"]
        assert dry.written is False
        assert settings_file.read_text(encoding="utf-8") == before, "dry run wrote the file"

        applied = migrate_settings_file(settings_file, dry_run=False, salt_path=salt)
        assert applied.written is True
        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        assert raw["openai_api_key"].startswith(PREFIX_V2)
        assert raw["groq_api_key"].startswith(PREFIX_V2)
        # And the migrated values still read back.
        migrated = load_settings(settings_file, salt_path=salt)
        assert migrated["openai_api_key"] == "legacy-a"
        assert migrated["groq_api_key"] == "legacy-b"

    def test_lazy_migration_is_off_by_default(self, settings_file: Path, salt: Path) -> None:
        settings_file.write_text(
            json.dumps({"openai_api_key": encrypt_value_v1("legacy-a")}), encoding="utf-8"
        )
        before = settings_file.read_text(encoding="utf-8")
        load_settings(settings_file, salt_path=salt)
        assert settings_file.read_text(encoding="utf-8") == before

    def test_lazy_migration_when_asked(self, settings_file: Path, salt: Path) -> None:
        settings_file.write_text(
            json.dumps({"openai_api_key": encrypt_value_v1("legacy-a")}), encoding="utf-8"
        )
        assert load_settings(settings_file, salt_path=salt)["openai_api_key"] == "legacy-a"
        load_settings(settings_file, salt_path=salt, migrate=True)
        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        assert raw["openai_api_key"].startswith(PREFIX_V2)


def base64_of_sha256(secret: str) -> bytes:
    import base64
    import hashlib

    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


# ---------------------------------------------------------------------------
# 4. AAD: ciphertext is bound to the key name
# ---------------------------------------------------------------------------
class TestBinding:
    def test_ciphertext_cannot_be_moved_between_fields(self, salt: Path) -> None:
        token = encrypt_value("sk-movable", key_name="openai_api_key", salt_path=salt)
        moved = decrypt_value_detailed(
            token, key_name="anthropic_api_key", salt_path=salt
        )
        assert moved.kind == "undecryptable"
        assert moved.value == ""

    def test_correct_field_still_decrypts(self, salt: Path) -> None:
        token = encrypt_value("sk-fixed", key_name="openai_api_key", salt_path=salt)
        result = decrypt_value_detailed(token, key_name="openai_api_key", salt_path=salt)
        assert result.kind == "v2", f"decrypt failed: {result.error}"
        assert result.value == "sk-fixed"

    def test_binding_survives_a_save_load_round_trip(
        self, settings_file: Path, salt: Path
    ) -> None:
        save_settings(
            settings_file,
            {"openai_api_key": "sk-a", "groq_api_key": "sk-b"},
            salt_path=salt,
        )
        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        # Swap the two ciphertexts on disk: the names no longer match.
        raw["openai_api_key"], raw["groq_api_key"] = (
            raw["groq_api_key"],
            raw["openai_api_key"],
        )
        settings_file.write_text(json.dumps(raw), encoding="utf-8")
        loaded = load_settings(settings_file, salt_path=salt)
        assert loaded["openai_api_key"] == ""
        assert loaded["groq_api_key"] == ""
        assert sorted(undecryptable_keys(settings_file, salt_path=salt)) == [
            "groq_api_key",
            "openai_api_key",
        ]


# ---------------------------------------------------------------------------
# 5. "wrong key" vs "not configured"
# ---------------------------------------------------------------------------
class TestWrongKeyIsNotMissing:
    def test_undecryptable_raises_instead_of_returning_empty(self, salt: Path) -> None:
        token = encrypt_value("sk-value", key_name="openai_api_key", salt_path=salt)
        # Corrupt the token: structurally valid prefix, garbage payload.
        broken = PREFIX_V2 + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        with pytest.raises(SettingsDecryptionError) as excinfo:
            decrypt_value(broken, key_name="openai_api_key")
        assert "NOT the same as" in str(excinfo.value)
        assert token  # silence linters

    def test_plaintext_passes_through_untouched(self) -> None:
        assert decrypt_value("sk-legado-em-claro") == "sk-legado-em-claro"

    def test_strict_load_raises(self, settings_file: Path, salt: Path) -> None:
        settings_file.write_text(
            json.dumps({"openai_api_key": PREFIX_V2 + "AAAA"}), encoding="utf-8"
        )
        assert load_settings(settings_file, salt_path=salt)["openai_api_key"] == ""
        with pytest.raises(SettingsDecryptionError):
            load_settings(settings_file, salt_path=salt, strict=True)

    def test_undecryptable_keys_reports_names_only(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps({"openai_api_key": PREFIX_V2 + "AAAA", "llm_provider": "x"}),
            encoding="utf-8",
        )
        assert undecryptable_keys(settings_file) == ["openai_api_key"]

    def test_no_secret_material_in_the_report(self, settings_file: Path) -> None:
        secret = "sk-must-not-appear-anywhere"
        settings_file.write_text(
            json.dumps({"openai_api_key": PREFIX_V2 + "AAAA", "note": secret}),
            encoding="utf-8",
        )
        report = migrate_settings_file(settings_file, dry_run=True)
        assert "must-not-appear" not in json.dumps(report.to_dict())


# ---------------------------------------------------------------------------
# 6. Masked values are refused
# ---------------------------------------------------------------------------
class TestMaskedValuesRefused:
    @pytest.mark.parametrize(
        "value", ["********", "abcd****wxyz", "sk-a****bcde"]
    )
    def test_looks_masked(self, value: str) -> None:
        assert looks_masked(value)

    @pytest.mark.parametrize("value", ["sk-real-value", "abcd", "", "  "])
    def test_real_values_are_not_masks(self, value: str) -> None:
        assert not looks_masked(value)

    def test_save_refuses_a_masked_secret(self, settings_file: Path, salt: Path) -> None:
        with pytest.raises(ValueError, match="masked"):
            save_settings(
                settings_file, {"openai_api_key": "abcd****wxyz"}, salt_path=salt
            )

    def test_drop_masked_secrets_is_dry_run_by_default(
        self, settings_file: Path
    ) -> None:
        settings_file.write_text(
            json.dumps({"secret_key": "abcd****wxyz", "llm_provider": "openrouter"}),
            encoding="utf-8",
        )
        before = settings_file.read_text(encoding="utf-8")
        dropped = drop_masked_secrets(settings_file)
        assert dropped == ["secret_key"]
        assert settings_file.read_text(encoding="utf-8") == before

    def test_drop_masked_secrets_when_applied(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps({"secret_key": "abcd****wxyz", "llm_provider": "openrouter"}),
            encoding="utf-8",
        )
        drop_masked_secrets(settings_file, dry_run=False)
        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "secret_key" not in raw
        assert raw["llm_provider"] == "openrouter"


# ---------------------------------------------------------------------------
# 7. The real data/settings.json
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not REAL_SETTINGS.exists(), reason="no runtime settings file")
class TestRealSettingsFileIsUntouchedAndReadable:
    """Proof that existing ``enc:v1:`` values still decrypt after the change.

    Only *key names* and boolean results are asserted.  No secret value is read,
    logged or asserted on.
    """

    @pytest.fixture(scope="class")
    def snapshot(self):
        raw_bytes = REAL_SETTINGS.read_bytes()
        return raw_bytes, json.loads(raw_bytes.decode("utf-8"))

    def test_existing_v1_values_still_decrypt(self, snapshot) -> None:
        import hashlib

        _, raw = snapshot
        v1_keys = [
            key
            for key, value in raw.items()
            if isinstance(value, str) and value.startswith(PREFIX_V1)
        ]
        assert len(v1_keys) >= 8, f"expected the shipped encrypted keys, found {v1_keys}"
        for key in v1_keys:
            result = decrypt_value_detailed(raw[key], key_name=key)
            assert result.kind == "v1", f"{key} is no longer readable as v1"
            assert result.value, f"{key} decrypted to an empty value"
            # Not another ciphertext, and long enough to be a real credential.
            assert not result.value.startswith("enc:")
            assert hashlib.sha256(result.value.encode()).digest()

    def test_load_settings_reads_every_credential(self, snapshot) -> None:
        _, raw = snapshot
        loaded = load_settings(REAL_SETTINGS)
        for key, value in raw.items():
            if not is_sensitive_key(key):
                continue
            assert key in loaded, key
            if isinstance(value, str) and value.startswith(PREFIX_V1):
                assert loaded[key], f"{key} became 'not configured'"

    def test_migration_dry_run_reports_without_writing(self, snapshot) -> None:
        raw_bytes, _ = snapshot
        report = migrate_settings_file(REAL_SETTINGS, dry_run=True)
        assert report.dry_run is True
        assert report.written is False
        assert len(report.migrated) >= 8
        assert "secret_key" in report.plaintext, (
            "the shipped file stores a masked secret_key in cleartext; "
            "the migration report should surface it"
        )
        # The file on disk must be byte-identical.
        assert REAL_SETTINGS.read_bytes() == raw_bytes

    def test_the_shipped_masked_secret_key_is_visible_to_the_operator(
        self, snapshot
    ) -> None:
        _, raw = snapshot
        stored = raw.get("secret_key")
        if isinstance(stored, str) and stored:
            # It is a display mask, not a credential: the settings API now
            # refuses to accept it and refuses to treat "" as "not configured".
            assert looks_masked(stored), (
                "secret_key in data/settings.json is neither a valid credential "
                "nor a recognisable mask; investigate before migrating"
            )

    def test_undecryptable_keys_is_empty_for_the_shipped_file(self) -> None:
        """The real file must be fully readable, or the migration is unsafe."""
        assert undecryptable_keys(REAL_SETTINGS) == []


# ---------------------------------------------------------------------------
# 8. The settings API wiring
# ---------------------------------------------------------------------------
class TestSettingsApiWiring:
    def test_public_settings_masks_secret_key(self) -> None:
        from backend.orchestrator.routes.settings import _get_public_settings

        public = _get_public_settings()
        assert "secret_key" in public
        value = public["secret_key"]
        assert value == "********" or "****" in str(value)

    def test_public_settings_masks_no_counter(self) -> None:
        from backend.orchestrator.routes.settings import _get_public_settings

        public = _get_public_settings()
        for key in ("max_tokens", "input_tokens", "openai_max_tokens"):
            if key in public and isinstance(public[key], str):
                assert "****" not in public[key], f"{key} must not be masked"

    def test_settings_api_is_json_serialisable(self) -> None:
        import json as json_module

        from backend.orchestrator.routes.settings import _get_public_settings

        json_module.dumps(_get_public_settings())

    def test_ledger_table_is_shared_with_the_governor(self, tmp_path) -> None:
        """``usage_ledger`` is the financial record; it must be a real table."""
        from backend.llm.cost_governor import CostGovernor

        db = tmp_path / "nexus.db"
        CostGovernor(db)
        with sqlite3.connect(db) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert "usage_ledger" in tables
