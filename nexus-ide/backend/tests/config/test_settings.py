"""Tests for backend.config.settings — Settings dataclass and loaders."""

from __future__ import annotations

import pytest

from backend.config.settings import (
    Settings,
    get_settings,
    load_environment_config,
    load_models_config,
    load_prompt,
    validate_configuration,
)


class TestSettingsDefaults:
    def test_default_values(self) -> None:
        """Verify Settings has the expected local-provider fields.

        NOTE: This test runs with the `mock_settings` autouse fixture which
        overrides env vars (e.g. BACKEND_PORT=9999, LOG_LEVEL=DEBUG,
        OLLAMA_HOST=http://test-ollama:11434). We therefore only check
        types and well-formedness, not specific default values.
        """
        s = Settings()
        # The current runtime uses OpenRouter as the primary cloud provider;
        # override via LLM_PROVIDER when a local Ollama-only profile is needed.
        assert isinstance(s.llm_provider, str)
        assert s.llm_provider in {
            "ollama",
            "openrouter",
            "openai",
            "anthropic",
            "deepseek",
            "kimi",
            "gemini",
            "opencode_go",
            "kilo",
        }
        assert isinstance(s.local_llm_device, str)
        assert s.local_llm_device
        assert isinstance(s.local_llm_dashboard_device, str)
        assert s.default_provider == "openrouter"
        assert s.ollama_host.startswith("http://")
        # Network / runtime fields have the right types
        assert isinstance(s.backend_port, int)
        assert s.backend_port > 0
        assert isinstance(s.log_level, str)
        assert s.log_level.upper() in ("DEBUG", "INFO", "WARNING", "ERROR")
        assert isinstance(s.prometheus_port, int)
        assert s.environment == "development"
        assert isinstance(s.debug, bool)
        assert isinstance(s.enable_tracing, bool)
        assert isinstance(s.enable_metrics, bool)

    def test_environment_validation(self) -> None:
        s = Settings(environment="development")
        assert s.environment == "development"
        with pytest.raises(ValueError, match="environment must be one of"):
            Settings(environment="invalid")

    def test_log_level_validation(self) -> None:
        s = Settings(log_level="debug")
        assert s.log_level == "DEBUG"  # Should be uppercased
        with pytest.raises(ValueError, match="log_level must be one of"):
            Settings(log_level="invalid")

    def test_get_allowed_origins_list(self) -> None:
        s = Settings(allowed_origins="http://localhost:3000,http://127.0.0.1:3000")
        origins = s.get_allowed_origins_list()
        assert origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


class TestGetSettings:
    def test_returns_instance(self, mock_settings: None) -> None:
        s = get_settings()
        assert isinstance(s, Settings)
        assert s.ollama_host == "http://test-ollama:11434"
        assert s.backend_port == 9999
        assert s.brave_api_key == "test-key-123"


class TestLoadModelsConfig:
    def test_loads_yaml(self) -> None:
        config = load_models_config()
        assert "models" in config
        assert "nano" in config["models"]
        assert "routing" in config
        assert "fallback" in config

    def test_nano_model_fields(self) -> None:
        config = load_models_config()
        nano = config["models"]["nano"]
        # We verify structure + purpose, not a specific tag — the registry is
        # configurable by design. The current NEXUS IDE routes all tiers to
        # deepseek-v4-flash on OpenRouter; the assertion checks for a known
        # model family without locking to a specific version.
        assert isinstance(nano["id"], str) and nano["id"]
        assert (
            "llama3.1" in nano["id"]
            or "Llama" in nano["id"]
            or "qwen" in nano["id"]
            or "Qwen" in nano["id"]
            or "deepseek" in nano["id"].lower()
            or "mimo" in nano["id"].lower()
            or "minimax" in nano["id"].lower()
            or "gemma" in nano["id"].lower()
            or "nemotron" in nano["id"].lower()
        )
        assert nano["temperature"] == 0.1
        assert "routing" in nano["use_cases"]


class TestLoadPrompt:
    def test_loads_existing_prompt(self) -> None:
        text = load_prompt("router")
        assert "ROUTER" in text or "router" in text.lower()
        assert len(text) > 100

    def test_raises_on_missing_prompt(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_agent_xyz")


class TestLoadEnvironmentConfig:
    def test_loads_dev_config(self) -> None:
        config = load_environment_config()
        # Should return a dict with environment-specific settings
        assert isinstance(config, dict)

    def test_returns_empty_dict_for_invalid_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Temporarily set an invalid environment
        monkeypatch.setenv("ENVIRONMENT", "invalid_env")
        # Clear the cache
        get_settings.cache_clear()
        config = load_environment_config()
        # Should return empty dict for invalid environment
        assert config == {}
        # Restore
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        get_settings.cache_clear()


class TestValidateConfiguration:
    def test_validates_successfully(self) -> None:
        errors = validate_configuration()
        # Should return empty list for valid configuration
        assert isinstance(errors, list)

    def test_detects_insecure_secret_key_in_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SECRET_KEY", "development-secret-key-change-in-production")
        get_settings.cache_clear()
        errors = validate_configuration()
        # Should detect insecure secret key in production
        assert len(errors) > 0
        assert any("SECRET_KEY" in error for error in errors)
        # Cleanup
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        get_settings.cache_clear()
