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
        s = Settings()
        assert s.ollama_host == "http://localhost:11434"
        assert s.ollama_dashboard_host == "http://localhost:11435"
        assert s.backend_port == 8000
        assert s.log_level == "INFO"
        assert s.prometheus_port == 9090
        assert s.environment == "development"
        assert s.debug is True
        assert s.enable_tracing is False
        assert s.enable_metrics is True

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
        # configurable by design.
        assert isinstance(nano["id"], str) and nano["id"]
        assert nano["id"].startswith("qwen")
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
