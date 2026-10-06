"""B7: chaves encriptadas em repouso em data/settings.json."""

from __future__ import annotations

import json
import re

import pytest

from backend.core.secure_settings_store import (
    PREFIX_V1,
    decrypt_value,
    encrypt_value,
    encrypt_value_v1,
    is_sensitive_key,
    load_settings,
    save_settings,
)
from backend.llm.cost_governor import reset_cost_governor

# Matches any `enc:vN:` envelope. Deliberately NOT a pinned version: the write
# format moved from enc:v1: to enc:v2: (key-binding via scrypt, see
# secure_settings_store.py) while v1 stays readable forever, and these two
# tests failed on that bump even though the behaviour under test -- ciphertext
# at rest, no plaintext on disk -- did not change. What matters is that the
# value is an encrypted envelope, not which generation produced it.
ENCRYPTED = re.compile(r"^enc:v\d+:")


class TestSecureSettingsStore:
    def test_sensitive_keys_encrypted_at_rest(self, tmp_path) -> None:
        target = tmp_path / "settings.json"
        save_settings(
            target,
            {
                "openrouter_api_key": "sk-or-v1-SUPERSECRETA",
                "llm_provider": "openrouter",
                "free_only": "true",
            },
        )
        raw = json.loads(target.read_text(encoding="utf-8"))
        # AUDIT P1-4 (2026-09-26): the storage format deliberately changed from
        # ``enc:v1:`` (bare SHA-256, no AAD) to ``enc:v2:`` (scrypt with a
        # persisted salt + the settings key name bound in). The assertion was
        # updated on purpose; ``enc:v1:`` values stay readable, which
        # backend/tests/security_hardening_secrets.py proves against the real
        # data/settings.json.
        assert raw["openrouter_api_key"].startswith("enc:v2:")
        assert "SUPERSECRETA" not in target.read_text(encoding="utf-8")
        # ...but valores não sensíveis continuam legíveis.
        assert raw["llm_provider"] == "openrouter"

    def test_secret_key_is_encrypted_too(self, tmp_path) -> None:
        """The key the audit found in cleartext on disk.

        ``"secret_key".endswith("api_key"|"secret"|"password"|"token")`` is
        false for all four, so the old suffix-only rule wrote it verbatim.
        """
        target = tmp_path / "settings.json"
        save_settings(target, {"secret_key": "a-real-secret-key-value"})
        raw = json.loads(target.read_text(encoding="utf-8"))
        assert raw["secret_key"].startswith("enc:v2:")
        assert "a-real-secret-key-value" not in target.read_text(encoding="utf-8")
        assert load_settings(target)["secret_key"] == "a-real-secret-key-value"


    def test_roundtrip_returns_plaintext(self, tmp_path) -> None:
        target = tmp_path / "settings.json"
        save_settings(target, {"gemini_api_key": "AIzaSecreta123"})
        loaded = load_settings(target)
        assert loaded["gemini_api_key"] == "AIzaSecreta123"

    def test_legacy_plaintext_still_readable(self, tmp_path) -> None:
        target = tmp_path / "settings.json"
        target.write_text(
            json.dumps({"openai_api_key": "sk-legado-em-claro"}),
            encoding="utf-8",
        )
        assert load_settings(target)["openai_api_key"] == "sk-legado-em-claro"
        # E o decrypt direto passa através de valores sem prefixo.
        assert decrypt_value("qualquer-coisa") == "qualquer-coisa"

    def test_reencryption_on_second_save(self, tmp_path) -> None:
        target = tmp_path / "settings.json"
        save_settings(target, {"kimi_api_key": "chave-viva"})
        primeiro = json.loads(target.read_text(encoding="utf-8"))["kimi_api_key"]
        save_settings(target, {"kimi_api_key": "chave-viva"})
        segundo = json.loads(target.read_text(encoding="utf-8"))["kimi_api_key"]
        # Fernet com AES-GCM: mesmo plaintext → ciphertexts diferentes.
        assert primeiro != segundo
        assert load_settings(target)["kimi_api_key"] == "chave-viva"

    def test_suffix_detection(self) -> None:
        assert is_sensitive_key("groq_api_key")
        assert is_sensitive_key("jwt_secret")
        assert is_sensitive_key("db_password")
        # AUDIT P1-4: this one used to be False and SECRET_KEY was written in
        # cleartext to data/settings.json.
        assert is_sensitive_key("secret_key")
        assert not is_sensitive_key("llm_provider")
        assert not is_sensitive_key("max_tokens")
        # Token counters must never be encrypted, or the LLM logs become noise.
        assert not is_sensitive_key("input_tokens")
        assert not is_sensitive_key("cost_per_token")

    def test_encrypt_decrypt_roundtrip_direct(self) -> None:
        token = encrypt_value("valor-seguro-123")
        assert token.startswith("enc:v2:")
        assert decrypt_value(token) == "valor-seguro-123"

    def test_encryption_fails_closed_without_crypto(self, tmp_path, monkeypatch) -> None:
        """The old code returned the *plaintext* when cryptography was missing."""
        import backend.core.secure_settings_store as store

        monkeypatch.setattr(
            store,
            "_fernet",
            lambda *a, **k: (_ for _ in ()).throw(store.EncryptionUnavailableError("x")),
        )
        with pytest.raises(store.EncryptionUnavailableError):
            store.encrypt_value("valor-seguro-123")


    def test_legacy_v1_envelope_is_still_readable(self) -> None:
        # secure_settings_store.py documents that `enc:v1:` stays readable
        # forever and that migration is explicit. This test did not exist, so
        # the v1 -> v2 bump could have silently broken every already-encrypted
        # settings.json on disk without anything going red.
        token = encrypt_value_v1("valor-antigo-456")

        assert token.startswith(PREFIX_V1)
        assert decrypt_value(token) == "valor-antigo-456"


class TestCostsEndpoints:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.llm.cost_governor import get_cost_governor  # noqa: F401 (reset no topo)
        from backend.observability.routes import costs as costs_mod

        db = tmp_path / "nexus.db"
        reset_cost_governor()
        governor = get_cost_governor(db)
        governor.record(cost_usd=0.42, provider="openai", model="gpt-test",
                        input_tokens=10, output_tokens=20, run_id="r1")
        governor.record(cost_usd=0.08, provider="openrouter", model="m-free")

        monkeypatch.setattr(costs_mod, "DB_PATH", db)
        app = FastAPI()
        app.include_router(costs_mod.router)
        yield TestClient(app)
        reset_cost_governor()

    def test_cost_summary_aggregates(self, client) -> None:
        resp = client.get("/metrics/costs")
        assert resp.status_code == 200
        data = resp.json()
        total = sum(entry["usd"] for entry in data["by_model"])
        assert total == pytest.approx(0.50)
        providers = {e["provider"]: e["usd"] for e in data["by_provider"]}
        assert providers["openai"] == pytest.approx(0.42)
        assert data["month_to_date_usd"] >= 0.5

    def test_cost_ledger_lists_recent(self, client) -> None:
        resp = client.get("/metrics/costs/ledger?limit=10")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) == 2
        assert {e["model"] for e in entries} == {"gpt-test", "m-free"}
