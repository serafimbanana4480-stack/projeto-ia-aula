"""Application settings loaded from environment and `config/models.yaml`.

See ARCHITECTURE.md §7 (Backend stack) and `config/models.yaml` for the schema.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
PROMPTS_DIR = CONFIG_DIR / "prompts"
MODELS_YAML = CONFIG_DIR / "models.yaml"
MODES_YAML = CONFIG_DIR / "modes.yaml"

logger = logging.getLogger(__name__)

_DEFAULT_SECRET_KEY = "development-secret-key-change-in-production"
_DEFAULT_JWT_SECRET = "development-jwt-secret-change-in-production"

#: The ``JWT_SECRET`` value shipped in ``.env.example``.  It is published in
#: the repository, so a token signed with it can be forged by anyone who can
#: read the repository.
_EXAMPLE_JWT_SECRET = "change-this-secret-in-production-use-env-var"

#: Minimum length of a secret that signs or verifies tokens.
MIN_SECRET_LENGTH = 32

#: Substrings that mark a value as a placeholder instead of a real secret.
_PLACEHOLDER_PATTERNS = (
    "change",
    "example",
    "your-",
    "changeme",
    "dev-secret",
    "placeholder",
)

#: ``backend/tests/conftest.py`` pins this exact secret for the whole test
#: suite so that tokens are reproducible.  It is a public constant, so it is
#: only tolerated while running under pytest; anywhere else it is rejected
#: like any other published value.
_SUITE_PINNED_JWT_SECRET = "test-jwt-secret-for-testing"


def _generate_secret() -> str:
    """A fresh, high-entropy secret value."""
    import secrets as _secrets

    return _secrets.token_urlsafe(48)


def _read_env_value(content: str, name: str) -> str:
    """The effective value of ``name`` in a dotenv body.

    Mirrors python-dotenv: the last assignment wins and surrounding quotes
    are stripped.  The last-wins rule matters because the bootstrap appends
    to the file, and the appended value is the one in force.
    """
    value = ""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        if key.strip() != name:
            continue
        raw_value = raw_value.strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in "\"'":
            raw_value = raw_value[1:-1]
        value = raw_value
    return value


def _get_env_var(content: str, name: str) -> bool:
    """Whether ``name`` carries a non-empty value in a dotenv body."""
    return bool(_read_env_value(content, name))


def _env_value_line_index(lines: list[str], name: str) -> int | None:
    """Index of the line that assigns ``name`` (the last one), or ``None``."""
    index: int | None = None
    for position, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.partition("=")[0].strip() == name:
            index = position
    return index


def _write_env_file(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically.

    A crash halfway through a rewrite must not leave the operator with a
    truncated ``.env``, so the new content goes to a sibling temporary file
    that replaces the original in one step.
    """
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.nexus-tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


def _example_secret_values() -> frozenset[str]:
    """Every secret value published in ``.env.example``, plus the defaults.

    ``.env.example`` ships the values an operator is meant to replace, so any
    of them is a *public* secret: a token signed with one of them is accepted
    by the API, and anyone can produce one.
    """
    values = {_DEFAULT_SECRET_KEY, _DEFAULT_JWT_SECRET, _EXAMPLE_JWT_SECRET}
    try:
        example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    except OSError:
        return frozenset(values)
    for name in ("SECRET_KEY", "JWT_SECRET"):
        value = _read_env_value(example, name)
        if value:
            values.add(value)
    return frozenset(values)


def is_placeholder_secret(value: str) -> bool:
    """Whether ``value`` is a published placeholder instead of a real secret."""
    if not value:
        return True
    if value in _example_secret_values():
        return True
    lowered = value.lower()
    return any(pattern in lowered for pattern in _PLACEHOLDER_PATTERNS)


def is_low_entropy_secret(value: str) -> bool:
    """Whether ``value`` is too weak to be used as a signing secret."""
    if not value:
        return True
    if value == _SUITE_PINNED_JWT_SECRET and "pytest" in sys.modules:
        # The suite pins a public secret on purpose; see the constant.
        return False
    return len(value) < MIN_SECRET_LENGTH


def describe_secret_problem(name: str, value: str) -> str | None:
    """Why ``value`` cannot be used as the secret ``name`` (``None`` when fine).

    The message is the one the operator sees, so it names the variable, says
    why the value is refused, and gives the command that produces a real
    secret.
    """
    generate = (
        'generate one with python -c "import secrets; print(secrets.token_urlsafe(48))" '
        f"and set {name} in {REPO_ROOT / '.env'}"
    )
    generate = generate[0].upper() + generate[1:]
    if not value:
        return f"{name} is not set. {generate}."
    if value in _example_secret_values():
        return (
            f"{name} is set to the value published in .env.example. That value is "
            f"public, so anyone can sign a token with it and be accepted as an "
            f"admin. {generate}."
        )
    if is_placeholder_secret(value):
        return (
            f"{name} still looks like a placeholder ({value!r}). A placeholder is a "
            f"public value, so tokens signed with it can be forged. "
            f"{generate}."
        )
    if is_low_entropy_secret(value):
        return (
            f"{name} is too weak ({len(value)} characters, {MIN_SECRET_LENGTH} are "
            f"required). {generate}."
        )
    return None


def _bootstrap_secrets(env_path: Path | None = None) -> None:
    """Make sure ``.env`` holds a strong, non-placeholder SECRET_KEY / JWT_SECRET.

    A secret that is *missing* and a secret that still carries a *published
    placeholder* are the same failure: the API is signing tokens with a value
    that everybody can read in ``.env.example``.  Both are treated as absent,
    so a fresh high-entropy value is generated -- a missing one is appended,
    a placeholder is replaced where it stands.  The replacement is logged, so
    the operator knows the file carries a generated secret and can set their
    own.
    """
    path = env_path if env_path is not None else REPO_ROOT / ".env"
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return

    lines = existing.splitlines(keepends=True)
    appended: list[str] = []
    replaced: list[tuple[int, str]] = []
    replaced_names: list[str] = []

    for name in ("SECRET_KEY", "JWT_SECRET"):
        value = _read_env_value(existing, name)
        if not value:
            appended.append(f"{name}={_generate_secret()}")
            continue
        if not is_placeholder_secret(value):
            continue
        generated = _generate_secret()
        index = _env_value_line_index(lines, name)
        if index is None:
            appended.append(f"{name}={generated}")
        else:
            replaced.append((index, f"{name}={generated}"))
        replaced_names.append(name)

    if not appended and not replaced:
        return

    for index, new_line in replaced:
        ending = "\n" if lines[index].endswith("\n") else ""
        lines[index] = new_line + ending
    content = "".join(lines)

    if appended:
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n# Auto-generated by NEXUS IDE bootstrap\n"
        content += "".join(f"{line}\n" for line in appended)

    try:
        _write_env_file(path, content)
    except OSError:
        logger.warning("Could not write auto-generated secrets to %s", path, exc_info=True)
        return

    if replaced_names:
        logger.warning(
            "%s carried a published placeholder in %s and was replaced with a "
            "generated strong secret. Set your own value to silence this warning: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"',
            ", ".join(replaced_names),
            path,
        )
    if appended:
        logger.info("Auto-generated secrets in %s", path)


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
    # Runtime execution is fail-closed: only validated zero-cost models are
    # eligible unless an operator explicitly disables this guard.
    llm_provider: str = Field(default="openrouter")
    free_only: bool = Field(default=True, validation_alias="NEXUS_FREE_ONLY")
    provider_validation_ttl_seconds: int = Field(
        default=600, validation_alias="NEXUS_PROVIDER_VALIDATION_TTL_SECONDS", ge=1
    )
    max_provider_latency_ms: int = Field(
        default=30_000, validation_alias="NEXUS_MAX_PROVIDER_LATENCY_MS", ge=0
    )

    # Local LLM (AirLLM experimental)
    local_llm_device: str = Field(default="auto")
    local_llm_compression: str = Field(default="")
    local_llm_dashboard_device: str = Field(default="cpu")
    airllm_experimental_enabled: bool = Field(default=False)

    # Ollama is opt-in, including for free-only policy selection.
    ollama_host: str = Field(default="http://localhost:11434")
    ollama_dashboard_host: str = Field(default="http://localhost:11434")
    nexus_enable_ollama: bool = Field(default=False, validation_alias="NEXUS_ENABLE_OLLAMA")

    # LM Studio (local OpenAI-compatible server on port 1234). Zero-cost like
    # Ollama, so the free-only policy treats it as an eligible local provider.
    lmstudio_host: str = Field(default="http://localhost:1234/v1")
    lmstudio_api_key: str = Field(default="")
    lmstudio_default_model: str = Field(default="lfm2.5-2.6b-heretic-abliterated")
    lmstudio_fast_model: str = Field(default="lfm2.5-2.6b-heretic-abliterated")
    lmstudio_coder_model: str = Field(default="lfm2.5-2.6b-heretic-abliterated")
    lmstudio_read_timeout: float = Field(default=600.0)

    # Primary runtime: per-signal provider timeout in seconds (0 = off). Bounds
    # a wedged or cold-loading small local model instead of hanging the turn.
    # The process env var takes precedence (tests monkeypatch it directly).
    nexus_primary_signal_timeout: float = Field(
        default=0.0, validation_alias="NEXUS_PRIMARY_SIGNAL_TIMEOUT", ge=0
    )

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

    # Kilo AI Gateway (OpenAI-compatible, without /v1 in the path)
    kilo_api_key: str = Field(default="")
    kilo_base_url: str = Field(default="https://api.kilo.ai/api/gateway")

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
    # The IDE is local-first: expose the API to this machine by default.
    # Network deployments must opt in explicitly with BACKEND_HOST.
    backend_host: str = Field(default="127.0.0.1")
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
    secret_key: str = Field(default="")

    # Self-registration is a development convenience.  Outside development it
    # is off unless an operator turns it on explicitly, because an open
    # registration endpoint hands an account -- and with it the tool-execution
    # endpoints -- to anyone who can reach the API.
    #
    # Tri-state on purpose: ``None`` means "not configured", and the effective
    # value then follows the environment (see the model validator below).
    allow_self_registration: bool | None = Field(default=None)

    # Content Security Policy
    #   csp_enabled: when false, the CSP header is omitted entirely (dev/debug).
    #   csp_policy:  non-empty string overrides the built-in default CSP verbatim.
    csp_enabled: bool = Field(default=True)
    csp_policy: str = Field(default="")

    # CORS - Comma-separated string for environment variable
    allowed_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    # JWT Authentication
    jwt_secret: str = Field(default="")
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
    rate_limit_tokens_per_minute: int = Field(default=100000)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate that environment is one of the allowed values."""
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}, got: {v}")
        return v

    @model_validator(mode="before")
    @classmethod
    def _default_allow_self_registration(cls, data: Any) -> Any:
        """Default self-registration to the development environment only.

        Runs *before* the field validators so it can read the environment the
        settings were actually resolved with (process env, ``.env`` or an
        explicit constructor argument).  An explicit ``ALLOW_SELF_REGISTRATION``
        always wins: this only fills in the value nobody configured.
        """
        if not isinstance(data, dict) or "allow_self_registration" in data:
            return data
        environment = data.get("environment") or "development"
        values = dict(data)
        values["allow_self_registration"] = str(environment).strip().lower() == "development"
        return values

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

    @field_validator("secret_key", mode="after")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if not v:
            raise RuntimeError(
                "SECRET_KEY is not set. Set the SECRET_KEY environment variable."
            )
        return v

    @field_validator("jwt_secret", mode="after")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if not v:
            raise RuntimeError(
                "JWT_SECRET is not set. Set the JWT_SECRET environment variable."
            )
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

        if settings.allow_self_registration and not _is_loopback_host(settings.backend_host):
            errors.append(
                "Self-registration cannot be enabled when BACKEND_HOST is not loopback. "
                "Set ALLOW_SELF_REGISTRATION=false before exposing the API to a network."
            )

        # Secret strength gate (security gate).
        #
        # A published or weak secret is not a misconfiguration to warn about:
        # it is a key anybody can sign an admin token with, so the startup gate
        # refuses to continue with one.  This check never rewrites ``.env`` --
        # it tells the operator what to set.
        for name, value in (
            ("SECRET_KEY", settings.secret_key),
            ("JWT_SECRET", settings.jwt_secret),
        ):
            problem = describe_secret_problem(name, value)
            if problem:
                errors.append(problem)

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
            "kilo",
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


def _is_loopback_host(host: str) -> bool:
    """Whether a listener host is explicitly limited to this machine."""
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class ProjectContextError(ValueError):
    """Raised when a mission has no explicit, usable project context."""

    code = "BLOCKED_PROJECT_CONTEXT"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{self.code}: {reason}")


def resolve_mission_project(project_path: str, session_project: str | None = None) -> Path:
    """Resolve a mission target without ever defaulting to :data:`REPO_ROOT`.

    Mission work must be tied to a caller-provided directory.  ``session_project``
    is accepted as the only fallback for clients whose active project lives in
    session state; an empty request with no session target is blocked.
    """
    if not isinstance(project_path, str):
        raise ProjectContextError("project_path must be a string")
    if session_project is not None and not isinstance(session_project, str):
        raise ProjectContextError("session_project must be a string")
    requested = project_path.strip()
    session_target = (session_project or "").strip()
    candidate = requested if requested not in {"", ".", "./", ".\\"} else session_target
    if not candidate or candidate in {".", "./", ".\\"}:
        raise ProjectContextError("an explicit project_path or session_project is required")

    try:
        resolved = Path(candidate).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectContextError(f"project path cannot be resolved: {candidate}") from exc
    if not resolved.is_dir():
        raise ProjectContextError(f"project path is not an existing directory: {resolved}")
    return resolved


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
