"""Tests for config/models.yaml — structural validation against architecture spec."""

from __future__ import annotations

import pytest
import yaml


class TestModelsYamlStructure:
    @pytest.fixture
    def models_yaml(self) -> dict:
        from backend.config.settings import CONFIG_DIR

        path = CONFIG_DIR / "models.yaml"
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def test_top_level_keys(self, models_yaml: dict) -> None:
        required = {
            "models",
            "concurrency",
            "routing",
            "fallback",
            "web_search",
            "code_execution",
            "rate_limits",
        }
        assert required.issubset(models_yaml.keys())

    def test_all_agents_have_models(self, models_yaml: dict) -> None:
        expected_models = {
            "nano",
            "micro",
            "small",
            "medium",
            "large",
            "expert",
            "vision",
            "embed",
            "dashboard",
        }
        assert expected_models.issubset(models_yaml["models"].keys())

    def test_model_fields(self, models_yaml: dict) -> None:
        for name, spec in models_yaml["models"].items():
            assert "id" in spec, f"Model {name} missing id"
            assert "ollama_host" in spec, f"Model {name} missing ollama_host"
            assert "temperature" in spec, f"Model {name} missing temperature"
            assert "use_cases" in spec, f"Model {name} missing use_cases"

    def test_routing_thresholds(self, models_yaml: dict) -> None:
        routing = models_yaml["routing"]
        assert routing["max_react_iterations"] > 0
        assert routing["fallback_timeout_seconds"] > 0
        assert routing["queue_timeout_seconds"] > 0

    def test_fallback_chains(self, models_yaml: dict) -> None:
        fallback = models_yaml["fallback"]
        for primary, chain in fallback.items():
            assert isinstance(chain, list), f"Fallback chain for {primary} must be a list"
            # MICRO is the terminal agent and legitimately has an empty chain.
            if primary == "MICRO":
                continue
            assert len(chain) > 0, f"Fallback chain for {primary} must not be empty"

    def test_concurrency_limits_positive(self, models_yaml: dict) -> None:
        for agent, limit in models_yaml["concurrency"].items():
            assert isinstance(limit, int), f"Concurrency for {agent} must be int"
            assert limit > 0, f"Concurrency for {agent} must be > 0"

    def test_rate_limits_positive(self, models_yaml: dict) -> None:
        limits = models_yaml["rate_limits"]
        assert limits["requests_per_minute"] > 0
        assert limits["tokens_per_minute"] > 0
