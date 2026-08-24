"""Preço dinâmico (B4): YAML → catálogo live → taxa conservadora."""

from __future__ import annotations

import pytest

from backend.llm.pricing import (
    PricingTable,
    conservative_unknown_prices,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "NEXUS_UNKNOWN_PRICE_USD_PER_1M_INPUT",
        "NEXUS_UNKNOWN_PRICE_USD_PER_1M_OUTPUT",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


class TestDynamicPricing:
    def test_yaml_model_uses_yaml_source(self, tmp_path) -> None:
        cfg = tmp_path / "models.yaml"
        cfg.write_text(
            "pricing:\n  gpt-x:\n    input_price_per_1m: 2.5\n"
            "    output_price_per_1m: 10.0\n",
            encoding="utf-8",
        )
        pt = PricingTable(cfg)
        resolved = pt.resolve_prices("gpt-x")
        assert resolved is not None and resolved[1] == "yaml"
        custo = pt.compute_cost("gpt-x", input_tokens=1_000_000, output_tokens=0)
        assert custo == pytest.approx(2.5)

    def test_unknown_without_conservative_is_zero(self, tmp_path) -> None:
        pt = PricingTable(tmp_path / "vazio.yaml")
        assert pt.resolve_prices("modelo-misterioso") is None
        # Comportamento antigo preservado quando o chamador não pede conservadorismo.
        assert pt.compute_cost("modelo-misterioso", 1000, 1000) == 0.0

    def test_conservative_rates_for_paid_mode(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_UNKNOWN_PRICE_USD_PER_1M_INPUT", "3.0")
        monkeypatch.setenv("NEXUS_UNKNOWN_PRICE_USD_PER_1M_OUTPUT", "15.0")
        pt = PricingTable(tmp_path / "vazio.yaml")
        cost = pt.compute_cost(
            "desconhecido", input_tokens=2_000_000, output_tokens=1_000_000,
            conservative_unknown=True,
        )  # 2M×3.0 + 1M×15.0
        assert cost == pytest.approx(2 * 3.0 + 15.0)

    def test_defaults_are_conservative_not_zero(self, tmp_path) -> None:
        rates = conservative_unknown_prices()
        assert rates["input_price_per_1m"] > 0
        assert rates["output_price_per_1m"] > rates["input_price_per_1m"]

    def test_catalog_fallback_by_suffix(self, tmp_path, monkeypatch) -> None:
        from types import SimpleNamespace

        import backend.llm.model_catalog as mc

        fake = [
            SimpleNamespace(model_id="vendor/modelo-novo", input_price_per_1m=0.8,
                            output_price_per_1m=4.0),
        ]
        monkeypatch.setattr(mc, "load_validated_models", lambda prov: fake)

        pt = PricingTable(tmp_path / "vazio.yaml")
        resolved = pt.resolve_prices("modelo-novo", provider="openrouter")
        assert resolved is not None and resolved[1] == "catalog"
        assert resolved[0]["output_price_per_1m"] == pytest.approx(4.0)

    def test_free_models_in_catalog_cost_zero(self, tmp_path, monkeypatch) -> None:
        from types import SimpleNamespace

        import backend.llm.model_catalog as mc

        fake = [
            SimpleNamespace(model_id="free/gratis", input_price_per_1m=0.0,
                            output_price_per_1m=0.0),
        ]
        monkeypatch.setattr(mc, "load_validated_models", lambda prov: fake)
        pt = PricingTable(tmp_path / "vazio.yaml")
        assert pt.compute_cost("gratis", 500_000, 500_000) == 0.0
