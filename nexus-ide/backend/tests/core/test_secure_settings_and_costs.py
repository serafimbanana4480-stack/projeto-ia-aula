"""B7: chaves encriptadas em repouso em data/settings.json."""

from __future__ import annotations

import json

import pytest

from backend.core.secure_settings_store import (
    decrypt_value,
    encrypt_value,
    is_sensitive_key,
    load_settings,
    save_settings,
)
from backend.llm.cost_governor import reset_cost_governor


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
        # No disco NADA de texto claro para a chave...
        assert raw["openrouter_api_key"].startswith("enc:v1:")
        assert "SUPERSECRETA" not in target.read_text(encoding="utf-8")
        # ...mas valores não sensíveis continuam legíveis.
        assert raw["llm_provider"] == "openrouter"

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
        assert not is_sensitive_key("llm_provider")
        assert not is_sensitive_key("max_tokens")

    def test_encrypt_decrypt_roundtrip_direct(self) -> None:
        token = encrypt_value("valor-seguro-123")
        assert token.startswith("enc:v1:")
        assert decrypt_value(token) == "valor-seguro-123"


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
