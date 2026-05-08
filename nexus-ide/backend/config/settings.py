"""Application settings loaded from environment and `config/models.yaml`.

See ARCHITECTURE.md §7 (Backend stack) and `config/models.yaml` for the schema.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
PROMPTS_DIR = CONFIG_DIR / "prompts"
MODELS_YAML = CONFIG_DIR / "models.yaml"


class Settings(BaseSettings):
    """Environment-driven settings. See `.env.example` for defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Ollama
    ollama_host: str = Field(default="http://localhost:11434")
    ollama_dashboard_host: str = Field(default="http://localhost:11435")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379")

    # Web search
    brave_api_key: str = Field(default="")

    # Backend
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    # Observability
    otel_exporter_otlp_endpoint: str = Field(default="http://localhost:4317")
    prometheus_port: int = Field(default=9090)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_models_config() -> dict[str, Any]:
    """Load and cache the `models.yaml` configuration."""
    with MODELS_YAML.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache
def load_prompt(agent_name: str) -> str:
    """Load an agent system prompt from ``config/prompts/<agent>.md``.

    The result is cached; prompts are treated as immutable configuration.
    Raises :class:`FileNotFoundError` if the prompt does not exist so the
    orchestrator fails loudly at startup rather than silently at request time.
    """
    prompt_path = PROMPTS_DIR / f"{agent_name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def get_model_config(model_key: str) -> dict[str, Any]:
    """Return the config block for a model key (e.g. ``"nano"``).

    Raises :class:`KeyError` if the key is absent so callers get a clear
    error instead of a silent ``None``.
    """
    cfg = load_models_config()
    models = cfg.get("models", {})
    if model_key not in models:
        raise KeyError(f"Unknown model key: {model_key!r}. Available: {sorted(models)}")
    return models[model_key]
