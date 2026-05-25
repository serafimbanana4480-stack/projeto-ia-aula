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

    def test_models_use_qwen3_series(self, models_yaml: dict) -> None:
        """Test that models are using qwen3.x series as per setup.sh documentation."""
        critical_models = {
            "nano": "qwen3.5:2b",
            "micro": "qwen3.5:4b",
            "small": "qwen3.5:9b",
            "medium": "qwen3-coder:7b",
            "large": "deepseek-r1:8b",
            "expert": "qwen3-coder:30b",
        }
        for key, expected_id in critical_models.items():
            actual_id = models_yaml["models"][key]["id"]
            assert actual_id == expected_id, (
                f"Model {key} should use '{expected_id}' but uses '{actual_id}'. "
                f"models.yaml must match setup.sh model list."
            )

    def test_embed_model_is_qwen3_embedding(self, models_yaml: dict) -> None:
        """Test that embed model is qwen3-embedding:4b as per setup.sh."""
        embed_id = models_yaml["models"]["embed"]["id"]
        assert embed_id == "qwen3-embedding:4b", (
            f"Embed model should be 'qwen3-embedding:4b' but is '{embed_id}'. "
            f"This must match setup.sh."
        )

    def test_dashboard_uses_correct_host(self, models_yaml: dict) -> None:
        """Test that dashboard model uses the dedicated Ollama host on port 11435."""
        dashboard_host = models_yaml["models"]["dashboard"]["ollama_host"]
        assert dashboard_host == "http://localhost:11435", (
            f"Dashboard should use localhost:11435 but uses '{dashboard_host}'"
        )
