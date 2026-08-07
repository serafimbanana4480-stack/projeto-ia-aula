"""Application settings loaded from environment and `config/models.yaml`.

See ARCHITECTURE.md §7 (Backend stack) and `config/models.yaml` for the schema.
"""

from __future__ import annotations

import logging
import os
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

_DEFAULT_SECRET_KEY = "development-secret-key-change-in-production"
_DEFAULT_JWT_SECRET = "development-jwt-secret-change-in-production"


def _bootstrap_secrets() -> None:
    """Auto-generate SECRET_KEY / JWT_SECRET on first startup if still at defaults.

    Writes the generated values back to ``.env`` so they persist across restarts.
    Does nothing if the values have already been overridden or if ``.env`` is
    absent (the Settings class defaults will apply in that case).
    """
    import secrets

    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return

    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return

    new_secret_key: str | None = None
    new_jwt_secret: str | None = None

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key == "SECRET_KEY" and value == _DEFAULT_SECRET_KEY:
            new_secret_key = secrets.token_urlsafe(48)
        if key == "JWT_SECRET" and value == _DEFAULT_JWT_SECRET:
            new_jwt_secret = secrets.token_urlsafe(48)

    if new_secret_key is None and new_jwt_secret is None:
        return

    updated_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("SECRET_KEY=") and new_secret_key is not None:
            updated_lines.append(f"SECRET_KEY={new_secret_key}")
        elif line.startswith("JWT_SECRET=") and new_jwt_secret is not None:
            updated_lines.append(f"JWT_SECRET={new_jwt_secret}")
        else:
            updated_lines.append(line)

    try:
        env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
        logger.info(
            "Auto-generated SECRET_KEY and JWT_SECRET in .env (production must set explicit values)"
        )
    except OSError:
        logger.warning("Could not write auto-generated secrets to .env", exc_info=True)


_bootstrap_secrets()


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

    # Resolve environment files from the repository instead of the process
    # working directory.  The launcher starts from the repository root, while
    # manual backend runs commonly start from ``backend/``; both must load the
    # same provider configuration and secrets.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        extra="ignore",
    )

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
    rate_limit_enabled: bool = Field(default=False)
    rate_limit_requests_per_minute: int = Field(default=0)

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


_AUTONOMOUS_IMPROVEMENT_CONFIG_CACHE: dict[str, Any] | None = None


def get_autonomous_improvement_config() -> dict[str, Any]:
    """Return autonomous improvement config with 12-factor precedence.

    Precedence: Environment variables (NEXUS_AI_*) > YAML config > Code defaults.
    """
    global _AUTONOMOUS_IMPROVEMENT_CONFIG_CACHE
    if _AUTONOMOUS_IMPROVEMENT_CONFIG_CACHE is not None:
        return _AUTONOMOUS_IMPROVEMENT_CONFIG_CACHE

    defaults: dict[str, Any] = {
        "enabled": True,
        "mode": "dogfood",
        "cycle_interval_minutes": 30,
        "max_concurrent_improvements": 3,
        "auto_apply_threshold": 0.85,
        "require_meta_approval": True,
        "circuit_breaker": {
            "max_failures_per_hour": 5,
            "cooldown_minutes": 30,
        },
        "skill_retention_days": 30,
        "cross_project_learning": True,
        "failure_pattern_min_occurrences": 3,
        "quality_gates": {
            "min_test_pass_rate": 1.0,
            "max_lint_errors": 0,
            "max_security_issues": 0,
            "max_perf_regression_factor": 1.05,
            "require_type_check": True,
        },
        "skill_evolution": {
            "promotion_threshold": 0.7,
            "min_uses_for_promotion": 20,
            "deprecation_threshold": 0.1,
            "merge_similarity_threshold": 0.85,
        },
        "swarm_failure_analysis": {
            "enabled": True,
            "fuzzy_match_threshold": 0.85,
            "max_stack_frames": 3,
        },
        "predictive_failure": {
            "enabled": True,
            "block_threshold": 0.7,
            "require_approval_threshold": 0.4,
        },
        "meta_learning": {
            "enabled": True,
            "optimization_interval_cycles": 20,
        },
        "observability": {
            "emit_events": True,
            "log_level": "INFO",
        },
        "persistence": {
            "knowledge_base_path": ".nexus/knowledge_base",
            "cycle_history_retention_days": 90,
            "failure_history_retention_days": 180,
            "auto_commit_config": True,
        },
    }

    config = dict(defaults)
    yaml_path = CONFIG_DIR / "autonomous_improvement.yaml"
    if yaml_path.exists():
        try:
            with yaml_path.open("r", encoding="utf-8") as fh:
                yaml_config = yaml.safe_load(fh) or {}
            if isinstance(yaml_config, dict):
                config = _deep_merge(config, yaml_config)
        except Exception:
            logger.warning("Failed to load autonomous_improvement.yaml", exc_info=True)

    env_overrides = _load_env_overrides()
    if env_overrides:
        config = _deep_merge(config, env_overrides)

    _AUTONOMOUS_IMPROVEMENT_CONFIG_CACHE = config
    return config


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_env_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    prefix = "NEXUS_AI_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        config_key = key[len(prefix):].lower()
        nested = config_key.split("__")
        target: Any = overrides
        for part in nested[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]
        final_key = nested[-1]
        target[final_key] = _coerce_env_value(value)
    return overrides


def _coerce_env_value(value: str) -> Any:
    low = value.lower()
    if low in {"true", "1", "yes", "on"}:
        return True
    if low in {"false", "0", "no", "off"}:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


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
            if settings.secret_key == _DEFAULT_SECRET_KEY:
                errors.append(
                    "SECRET_KEY is set to the development default. "
                    "Set a strong random value in .env before starting in production. "
                    "Example: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                )
            if settings.jwt_secret == _DEFAULT_JWT_SECRET:
                errors.append(
                    "JWT_SECRET is set to the development default. "
                    "Set a strong random value in .env before starting in production. "
                    "Example: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
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
                # This connection belongs to the shared pool. Closing it
                # directly leaves the pool's created-count inflated and
                # eventually makes every request wait for an unavailable
                # connection.
                pool.return_connection(conn)
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(f"resolve_project_path: DB read failed: {_e}")
            # Don't fail silently - let callers know something went wrong
            pass  # Still default to REPO_ROOT
        return str(REPO_ROOT), True
    return stripped, False
