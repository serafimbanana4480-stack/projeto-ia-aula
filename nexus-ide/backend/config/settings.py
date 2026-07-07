"""Application settings loaded from environment and `config/models.yaml`.

See ARCHITECTURE.md §7 (Backend stack) and `config/models.yaml` for the schema.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
PROMPTS_DIR = CONFIG_DIR / "prompts"
MODELS_YAML = CONFIG_DIR / "models.yaml"
MODES_YAML = CONFIG_DIR / "modes.yaml"

logger = logging.getLogger(__name__)


def _detect_device() -> str:
    # Lazy import — torch is a 2+ second import and is only needed when the
    # user actually wants GPU inference.  In tests we override this via
    # LOCAL_LLM_DEVICE=cpu so the import is skipped entirely.
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


class Settings(BaseSettings):
    """Environment-driven settings. See `.env.example` for defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Environment
    environment: str = Field(default="development")

    # LLM Provider selection
    # Default: OpenRouter (cloud). Ollama is opt-in via NEXUS_ENABLE_OLLAMA=true.
    llm_provider: str = Field(default="openrouter")

    # Local LLM (AirLLM experimental)
    local_llm_device: str = Field(default="auto")
    local_llm_compression: str = Field(default="")
    local_llm_dashboard_device: str = Field(default="cpu")
    airllm_experimental_enabled: bool = Field(default=False)

    # Ollama
    ollama_host: str = Field(default="http://localhost:11434")
    ollama_dashboard_host: str = Field(default="http://localhost:11434")

    # Cloud API keys (used when llm_provider != "local")
    openai_api_key: str = Field(default="")
    deepseek_api_key: str = Field(default="")
    kimi_api_key: str = Field(default="")
    groq_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    # Google / Gemini
    gemini_api_key: str = Field(default="")
    gemini_base_url: str = Field(default="https://generativelanguage.googleapis.com/v1beta")
    # OpenRouter
    openrouter_api_key: str = Field(default="")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api")
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1")

    # OpenCode Go (https://opencode.ai/zen/go/v1)
    opencode_go_api_key: str = Field(default="")
    opencode_go_base_url: str = Field(default="https://opencode.ai/zen/go/v1")

    # Multi-LLM Manager
    multi_llm_enabled: bool = Field(default=True)
    default_provider: str = Field(default="openrouter")
    fallback_provider: str = Field(default="openrouter")

    # Provider-specific defaults
    openai_temperature: float = Field(default=0.7)
    openai_max_tokens: int = Field(default=2048)
    kimi_temperature: float = Field(default=0.7)
    kimi_max_tokens: int = Field(default=2048)
    local_llm_temperature: float = Field(default=0.7)
    local_llm_max_tokens: int = Field(default=2048)
    deepseek_temperature: float = Field(default=0.7)
    deepseek_max_tokens: int = Field(default=2048)
    groq_temperature: float = Field(default=0.7)
    groq_max_tokens: int = Field(default=2048)
    anthropic_temperature: float = Field(default=0.7)
    anthropic_max_tokens: int = Field(default=4096)

    # Redis
    redis_url: str = Field(default="redis://localhost:6379")
    redis_db: int = Field(default=0)
    redis_password: str = Field(default="")

    # Web search
    brave_api_key: str = Field(default="")

    # Backend
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)
    backend_reload: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=True)

    # Observability
    otel_exporter_otlp_endpoint: str = Field(default="http://localhost:4317")
    prometheus_port: int = Field(default=9090)
    enable_tracing: bool = Field(default=False)
    enable_metrics: bool = Field(default=True)

    # Security
    secret_key: str = Field(default="development-secret-key-change-in-production")

    # Content Security Policy
    #   csp_enabled: when false, the CSP header is omitted entirely (dev/debug).
    #   csp_policy:  non-empty string overrides the built-in default CSP verbatim.
    csp_enabled: bool = Field(default=True)
    csp_policy: str = Field(default="")

    # CORS - Comma-separated string for environment variable
    allowed_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    # JWT Authentication
    jwt_secret: str = Field(default="development-jwt-secret-change-in-production")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiration_minutes: int = Field(default=30)

    # Database
    database_url: str = Field(default=f"sqlite:///{REPO_ROOT.as_posix()}/data/nexus.db")

    # Plan approval
    plan_approval_timeout: int = Field(default=300)

    # Session lifecycle / garbage collection
    nexus_session_ttl_hours: int = Field(default=24, description="Hours of inactivity before a session is considered expired")
    nexus_gc_interval_minutes: int = Field(default=60, description="Minutes between automatic garbage-collection runs")

    # Rate limiting
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_requests_per_minute: int = Field(default=60)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate that environment is one of the allowed values."""
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}, got: {v}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate that log_level is a valid logging level."""
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got: {v}")
        return v.upper()

    @field_validator("local_llm_device", mode="before")
    @classmethod
    def _auto_detect_device(cls, v: Any) -> Any:
        if v == "auto" or v is None or v == "":
            return _detect_device()
        return v

    def get_allowed_origins_list(self) -> list[str]:
        """Convert comma-separated allowed_origins to list."""
        return [origin.strip() for origin in self.allowed_origins.split(",")]


_settings_instance: Settings | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get the cached settings singleton instance.

    Uses ``functools.lru_cache`` so that the same ``Settings`` instance is
    returned across calls within a process. Tests can call
    ``get_settings.cache_clear()`` to force re-instantiation after mutating
    environment variables.
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def load_environment_config() -> dict[str, Any]:
    """Load environment-specific configuration from YAML files.

    Returns the configuration for the current environment, or an empty dict
    if no environment-specific config exists.
    """
    try:
        settings = get_settings()
    except Exception:
        return {}

    env = settings.environment
    env_config_map = {
        "development": "dev.yaml",
        "staging": "staging.yaml",
        "production": "prod.yaml",
    }

    config_file = env_config_map.get(env)
    if not config_file:
        logger.warning("No config file mapping for environment: %s", env)
        return {}

    config_path = CONFIG_DIR / config_file
    if not config_path.exists():
        logger.info("No environment-specific config found at %s", config_path)
        return {}

    try:
        with config_path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        logger.info("Loaded environment-specific config from %s", config_file)
        return config
    except yaml.YAMLError as e:
        logger.error("Failed to load environment config from %s: %s", config_path, e)
        return {}


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


@lru_cache
def load_modes_config() -> dict[str, Any]:
    """Load and cache the ``config/modes.yaml`` configuration."""
    if not MODES_YAML.exists():
        return {"modes": {}, "tool_aliases": {}}
    with MODES_YAML.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_mode_config(mode_name: str) -> dict[str, Any]:
    """Return a mode configuration block with resolved tool aliases.

    Falls back to the ``auto`` mode configuration if the requested mode is
    not defined, so the chat pipeline always has sensible defaults.
    """
    cfg = load_modes_config()
    modes = cfg.get("modes", {})
    mode = modes.get(mode_name) or modes.get("auto") or {}
    mode = dict(mode)

    # Resolve tool aliases (e.g. "all" -> list of concrete tools)
    enabled = mode.get("tools_enabled", [])
    aliases = cfg.get("tool_aliases", {})
    resolved: list[str] = []
    for item in enabled:
        if isinstance(item, str) and item in aliases:
            resolved.extend(aliases[item])
        elif isinstance(item, str):
            resolved.append(item)
    mode["tools_enabled_resolved"] = resolved
    return mode


def validate_configuration() -> list[str]:
    """Validate the application configuration.

    Returns a list of error messages. Empty list means validation passed.
    """
    errors: list[str] = []
    warnings_list: list[str] = []

    try:
        settings = get_settings()

        if settings.environment == "production":
            if settings.secret_key == "development-secret-key-change-in-production":
                errors.append(
                    "SECRET_KEY is set to default value in production. This is a security risk."
                )
            elif len(settings.secret_key) < 32:
                errors.append(
                    "SECRET_KEY is shorter than 32 characters in production. "
                    "Use a longer, cryptographically random key (e.g. `python -c 'import secrets; print(secrets.token_urlsafe(48))'`)."
                )
            if settings.jwt_secret == "development-jwt-secret-change-in-production":
                errors.append(
                    "JWT_SECRET is set to default value in production. This is a security risk."
                )
            elif len(settings.jwt_secret) < 32:
                errors.append(
                    "JWT_SECRET is shorter than 32 characters in production. "
                    "Use a longer, cryptographically random key."
                )
        else:
            if settings.secret_key == "development-secret-key-change-in-production":
                warnings_list.append(
                    "SECRET_KEY is set to default value. "
                    "Change this before deploying to production."
                )
            if settings.jwt_secret == "development-jwt-secret-change-in-production":
                warnings_list.append(
                    "JWT_SECRET is set to default value. "
                    "Change this before deploying to production."
                )

        if not MODELS_YAML.exists():
            errors.append(f"Required config file not found: {MODELS_YAML}")

        prompts_dir = CONFIG_DIR / "prompts"
        if not prompts_dir.exists():
            errors.append(f"Required prompts directory not found: {prompts_dir}")

        provider = settings.llm_provider.lower()
        cloud_providers = {
            "openai",
            "deepseek",
            "kimi",
            "groq",
            "anthropic",
            "gemini",
            "openrouter",
        }
        if provider in cloud_providers:
            key_attr = f"{provider}_api_key"
            api_key = getattr(settings, key_attr, "")
            if not api_key:
                errors.append(
                    f"LLM_PROVIDER is set to '{provider}' but {key_attr.upper()} is not set."
                )

        for warning in warnings_list:
            logger.warning("Configuration warning: %s", warning)

    except Exception as e:
        errors.append(f"Failed to validate configuration: {e}")

    return errors


def resolve_project_path(project_path: str) -> tuple[str, bool]:
    """Return an effective project path and whether a default was applied.

    Empty strings and ``"."`` resolve to the first project in the database,
    or :data:`REPO_ROOT` if no project exists.
    """
    stripped = (project_path or "").strip()
    if not stripped or stripped == ".":
        # Try to get project from database
        try:
            from backend.persistence.db import get_connection_pool
            pool = get_connection_pool()
            conn = pool.get_connection()
            try:
                row = conn.execute('SELECT path FROM projects LIMIT 1').fetchone()
                if row:
                    return row['path'], True
            finally:
                conn.close()
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(f"resolve_project_path: DB read failed: {_e}")
            # Don't fail silently - let callers know something went wrong
            pass  # Still default to REPO_ROOT
        return str(REPO_ROOT), True
    return stripped, False
