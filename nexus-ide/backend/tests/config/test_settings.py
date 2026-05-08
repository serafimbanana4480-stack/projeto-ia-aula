"""Tests for backend.config.settings — Settings dataclass and loaders."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.config.settings import Settings, get_settings, load_models_config, load_prompt


class TestSettingsDefaults:
    def test_default_values(self) -> None:
        s = Settings()
        assert s.ollama_host == "http://localhost:11434"
        assert s.ollama_dashboard_host == "http://localhost:11435"
        assert s.backend_port == 8000
        assert s.log_level == "INFO"
        assert s.prometheus_port == 9090


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
