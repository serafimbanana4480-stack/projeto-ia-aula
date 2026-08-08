"""Live model discovery across every configured LLM provider.

Before this module the UI model list was a hardcoded Python constant
(``models_ui.OPENROUTER_FREE_MODELS``), so adding an API key never revealed
the models that key unlocks. Here each provider is queried for its real
catalog and the results are normalised into :class:`ModelInfo`.

Flow used by the UI:

1. ``validate_api_key(provider, key)`` — check a key *before* persisting it.
2. ``discover_models(provider)`` — live list, memoised on disk for
   :data:`CACHE_TTL_SECONDS`.
3. ``aggregate_models()`` — union of every provider that has a usable key,
   which is what ``GET /api/models/available`` returns.

Endpoints per provider (all are plain HTTP GETs returning JSON):

===============  ====================================================
provider         endpoint
===============  ====================================================
openrouter       ``GET {base}/v1/models``   (pricing + context_length)
openai           ``GET {base}/models``
deepseek         ``GET {base}/models``
groq             ``GET {base}/models``
kimi             ``GET {base}/models``
opencode_go      ``GET {base}/models``
anthropic        ``GET {base}/v1/models``   (needs ``x-api-key``)
gemini           ``GET {base}/models?key=`` (key in query string)
ollama           ``GET {base}/api/tags``    (no key)
===============  ====================================================
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import REPO_ROOT, get_settings

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 600
CACHE_PATH = REPO_ROOT / "data" / "model_catalog_cache.json"
HTTP_TIMEOUT = 15.0

# Providers whose ``/models`` endpoint follows the OpenAI schema:
# ``{"data": [{"id": ..., "created": ...}, ...]}`` with a bearer token.
_OPENAI_COMPATIBLE = frozenset({"openai", "deepseek", "groq", "kimi", "opencode_go"})

# Per-provider metadata: which settings attribute holds the key, the default
# API root, and a human label. ``requires_key`` drives the Settings UI.
PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "label": "OpenRouter",
        "key_setting": "openrouter_api_key",
        "base_setting": "openrouter_base_url",
        "default_base": "https://openrouter.ai/api",
        "requires_key": True,
        "docs": "https://openrouter.ai/keys",
    },
    "openai": {
        "label": "OpenAI",
        "key_setting": "openai_api_key",
        "base_setting": "openai_base_url",
        "default_base": "https://api.openai.com/v1",
        "requires_key": True,
        "docs": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic",
        "key_setting": "anthropic_api_key",
        "base_setting": "anthropic_base_url",
        "default_base": "https://api.anthropic.com",
        "requires_key": True,
        "docs": "https://console.anthropic.com/settings/keys",
    },
    "gemini": {
        "label": "Google Gemini",
        "key_setting": "gemini_api_key",
        "base_setting": "gemini_base_url",
        "default_base": "https://generativelanguage.googleapis.com/v1beta",
        "requires_key": True,
        "docs": "https://aistudio.google.com/apikey",
    },
    "deepseek": {
        "label": "DeepSeek",
        "key_setting": "deepseek_api_key",
        "base_setting": "deepseek_base_url",
        "default_base": "https://api.deepseek.com/v1",
        "requires_key": True,
        "docs": "https://platform.deepseek.com/api_keys",
    },
    "groq": {
        "label": "Groq",
        "key_setting": "groq_api_key",
        "base_setting": "groq_base_url",
        "default_base": "https://api.groq.com/openai/v1",
        "requires_key": True,
        "docs": "https://console.groq.com/keys",
    },
    "kimi": {
        "label": "Kimi (Moonshot)",
        "key_setting": "kimi_api_key",
        "base_setting": "kimi_base_url",
        "default_base": "https://api.moonshot.cn/v1",
        "requires_key": True,
        "docs": "https://platform.moonshot.cn/console/api-keys",
    },
    "opencode_go": {
        "label": "OpenCode Go",
        "key_setting": "opencode_go_api_key",
        "base_setting": "opencode_go_base_url",
        "default_base": "https://opencode.ai/zen/go/v1",
        "requires_key": True,
        "docs": "https://opencode.ai",
    },
    "ollama": {
        "label": "Ollama (local)",
        "key_setting": "",
        "base_setting": "ollama_host",
        "default_base": "http://localhost:11434",
        "requires_key": False,
        "docs": "https://ollama.com",
    },
}

# Heuristics for tagging a model without an explicit capability field.
_CODE_HINTS = ("code", "coder", "codestral", "starcoder", "devstral", "qwen-coder")
_REASONING_HINTS = ("reason", "think", "-r1", "r1-", "o1", "o3", "o4", "deepseek-r")
_VISION_HINTS = (
    "vision",
    "-vl",
    "omni",
    "gpt-4o",
    "gemini",
    "claude-3",
    "claude-4",
    "claude-sonnet",
    "claude-opus",
    "claude-haiku",
    "pixtral",
)
_EMBED_HINTS = ("embed", "embedding", "bge-", "nomic-embed", "e5-")

# Fallback context windows keyed by substring, used when a provider does not
# report ``context_length``. Wrong-but-plausible beats showing nothing.
_CONTEXT_HINTS: tuple[tuple[str, int], ...] = (
    ("claude", 200_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("gpt-4", 8_192),
    ("gpt-3.5", 16_385),
    ("o1", 200_000),
    ("o3", 200_000),
    ("gemini-1.5-pro", 2_000_000),
    ("gemini", 1_000_000),
    ("deepseek", 64_000),
    ("llama-3.1", 128_000),
    ("llama-3", 8_192),
    ("qwen", 32_768),
    ("mixtral", 32_768),
    ("mistral", 32_768),
)


@dataclass(slots=True)
class ModelInfo:
    """One selectable model, normalised across every provider."""

    id: str
    provider: str
    name: str
    context_window: int = 0
    input_price_per_1m: float | None = None
    output_price_per_1m: float | None = None
    free: bool = False
    capabilities: list[str] = field(default_factory=list)
    description: str = ""
    deprecated: bool = False
    quota_available: bool | None = None
    latency_ms: float | None = None
    validated_at: float | None = None
    reason: str = ""
    # Legacy fields the existing UI still reads.
    tier: str = "medium"
    pricing: str = "paid"
    estimated_tokens_per_sec: int = 0
    color: str = "#818cf8"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────────── helpers ────────────────────────────


def _runtime_overrides() -> dict[str, str]:
    """Read ``data/settings.json``, written by ``PUT /api/settings``.

    API keys can be changed from the UI without restarting the server, so the
    live value may not be the one Pydantic loaded from ``.env`` at startup.
    """
    path = REPO_ROOT / "data" / "settings.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: v for k, v in data.items() if isinstance(v, str) and v}
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_credentials(provider: str) -> tuple[str, str]:
    """Return ``(api_key, base_url)`` for *provider*, runtime overrides first."""
    spec = PROVIDER_SPECS.get(provider)
    if spec is None:
        return "", ""
    settings = get_settings()
    overrides = _runtime_overrides()

    key = ""
    if spec["key_setting"]:
        key = overrides.get(spec["key_setting"]) or getattr(settings, spec["key_setting"], "") or ""

    base = ""
    if spec["base_setting"]:
        base = overrides.get(spec["base_setting"]) or getattr(settings, spec["base_setting"], "") or ""
    return str(key).strip(), str(base).strip() or str(spec["default_base"])


def _guess_capabilities(model_id: str, extra: str = "") -> list[str]:
    blob = f"{model_id} {extra}".lower()
    caps: list[str] = []
    if any(h in blob for h in _EMBED_HINTS):
        return ["embedding"]
    caps.append("chat")
    if any(h in blob for h in _CODE_HINTS):
        caps.append("code")
    if any(h in blob for h in _REASONING_HINTS):
        caps.append("reasoning")
    if any(h in blob for h in _VISION_HINTS):
        caps.append("vision")
    return caps


def _guess_context(model_id: str) -> int:
    lowered = model_id.lower()
    for hint, window in _CONTEXT_HINTS:
        if hint in lowered:
            return window
    return 0


_SMALL_TOKENS = frozenset({"nano", "mini", "tiny", "micro", "small", "lite"})
_FAST_TOKENS = frozenset({"flash", "fast", "instant", "haiku", "turbo", "8b", "7b", "3b"})
_DEEP_TOKENS = frozenset({"opus", "pro", "max", "ultra", "405b", "120b", "70b"})
# Parameter-count hints keep their punctuation, so they stay substring checks.
_SMALL_SUBSTRINGS = ("0.5b", "1.5b", "1b-", "2b-")


def _tokenize(model_id: str) -> set[str]:
    """Split a model id into alphanumeric tokens.

    Substring matching is unsafe here: ``"mini" in "gemini-2.5-pro"`` is true,
    which classified every Gemini model as the ``micro`` tier. Matching whole
    tokens instead means ``gemini-2.5-pro`` yields
    ``{"gemini", "2", "5", "pro"}`` and lands on ``deep``.
    """
    token = ""
    tokens: set[str] = set()
    for char in model_id.lower():
        if char.isalnum():
            token += char
        elif token:
            tokens.add(token)
            token = ""
    if token:
        tokens.add(token)
    return tokens


def _infer_tier(model_id: str, context_window: int, caps: list[str]) -> str:
    """Map a model onto one of the router tiers in ``config/models.yaml``.

    Only a hint for which *agent* handles the request; an explicit model id is
    always used verbatim for the actual call.
    """
    lowered = model_id.lower()
    tokens = _tokenize(model_id)

    if "code" in caps:
        return "coder"
    if "reasoning" in caps:
        return "reasoning"
    if tokens & _SMALL_TOKENS or any(s in lowered for s in _SMALL_SUBSTRINGS):
        return "micro"
    if tokens & _FAST_TOKENS:
        return "fast"
    if context_window >= 400_000 or tokens & _DEEP_TOKENS:
        return "deep"
    return "medium"


def _price_to_per_1m(raw: Any) -> float | None:
    """OpenRouter reports price per token as a string; convert to per-1M USD."""
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return round(value * 1_000_000, 4)


def _color_for(provider: str, model_id: str) -> str:
    lowered = model_id.lower()
    if "nvidia" in lowered or "nemotron" in lowered:
        return "#76b900"
    if "claude" in lowered or provider == "anthropic":
        return "#d97757"
    if "gemini" in lowered or "gemma" in lowered or provider == "gemini":
        return "#4285f4"
    if "deepseek" in lowered:
        return "#4d6bfe"
    if "qwen" in lowered:
        return "#a78bfa"
    if "llama" in lowered:
        return "#0866ff"
    if provider == "openai":
        return "#10a37f"
    if provider == "groq":
        return "#f55036"
    if provider == "ollama":
        return "#5eead4"
    return "#818cf8"

def _finalise(info: ModelInfo) -> ModelInfo:
    """Fill derived fields while keeping free eligibility fail-closed."""
    if not info.context_window:
        info.context_window = _guess_context(info.id)
    if not info.capabilities:
        info.capabilities = _guess_capabilities(info.id, info.description)
    if info.quota_available is None:
        info.quota_available = True
    # Missing prices are unknown.  An ID suffix alone is never evidence of a
    # free cloud model; only an exact zero/zero catalog entry qualifies.
    info.free = bool(
        info.provider == "ollama"
        or (info.input_price_per_1m == 0 and info.output_price_per_1m == 0)
    )
    if info.provider == "ollama" and not info.reason:
        info.reason = "verified installed Ollama model"
    elif info.free and not info.reason:
        info.reason = "catalog confirmed zero input/output prices"
    elif not info.free and not info.reason:
        info.reason = "prices missing or non-zero"
    info.pricing = "free" if info.free else "unknown" if info.reason.startswith("stale") else "paid"
    info.tier = _infer_tier(info.id, info.context_window, info.capabilities)
    info.color = _color_for(info.provider, info.id)
    if not info.name:
        info.name = info.id
    return info


# ─────────────────────── per-provider parsers ───────────────────────

def _parse_openrouter(payload: dict[str, Any]) -> list[ModelInfo]:
    out: list[ModelInfo] = []
    validated_at = time.time()
    for entry in payload.get("data", []):
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        pricing = entry.get("pricing") or {}
        arch = entry.get("architecture") or {}
        modalities = arch.get("input_modalities") or []
        caps = _guess_capabilities(str(entry["id"]), str(entry.get("description", "")))
        if "image" in modalities and "vision" not in caps:
            caps.append("vision")
        out.append(
            _finalise(
                ModelInfo(
                    id=str(entry["id"]),
                    provider="openrouter",
                    name=str(entry.get("name") or entry["id"]),
                    context_window=int(entry.get("context_length") or 0),
                    input_price_per_1m=_price_to_per_1m(pricing.get("prompt")),
                    output_price_per_1m=_price_to_per_1m(pricing.get("completion")),
                    capabilities=caps,
                    description=str(entry.get("description") or "")[:280],
                    quota_available=entry.get("quota_available", True),
                    latency_ms=entry.get("latency_ms"),
                    validated_at=validated_at,
                )
            )
        )
    return out


def _parse_openai_compatible(payload: dict[str, Any], provider: str) -> list[ModelInfo]:
    out: list[ModelInfo] = []
    for entry in payload.get("data", []) or []:
        if isinstance(entry, str):
            model_id = entry
            meta: dict[str, Any] = {}
        elif isinstance(entry, dict) and entry.get("id"):
            model_id = str(entry["id"])
            meta = entry
        else:
            continue
        out.append(
            _finalise(
                ModelInfo(
                    id=model_id,
                    provider=provider,
                    name=str(meta.get("name") or model_id),
                    # Groq is the only OpenAI-compatible API that reports this.
                    context_window=int(meta.get("context_window") or 0),
                    description=str(meta.get("description") or "")[:280],
                )
            )
        )
    return out


def _parse_anthropic(payload: dict[str, Any]) -> list[ModelInfo]:
    out: list[ModelInfo] = []
    for entry in payload.get("data", []) or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        out.append(
            _finalise(
                ModelInfo(
                    id=str(entry["id"]),
                    provider="anthropic",
                    name=str(entry.get("display_name") or entry["id"]),
                    context_window=200_000,
                )
            )
        )
    return out


def _parse_gemini(payload: dict[str, Any]) -> list[ModelInfo]:
    out: list[ModelInfo] = []
    for entry in payload.get("models", []) or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        # Gemini returns fully-qualified names like ``models/gemini-2.5-pro``.
        model_id = str(entry["name"]).removeprefix("models/")
        methods = entry.get("supportedGenerationMethods") or []
        if methods and not any(m in methods for m in ("generateContent", "embedContent")):
            continue
        out.append(
            _finalise(
                ModelInfo(
                    id=model_id,
                    provider="gemini",
                    name=str(entry.get("displayName") or model_id),
                    context_window=int(entry.get("inputTokenLimit") or 0),
                    description=str(entry.get("description") or "")[:280],
                )
            )
        )
    return out


def _parse_ollama(payload: dict[str, Any]) -> list[ModelInfo]:
    out: list[ModelInfo] = []
    validated_at = time.time()
    for entry in payload.get("models", []) or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        details = entry.get("details") or {}
        size_bytes = int(entry.get("size") or 0)
        size_gb = round(size_bytes / 1_073_741_824, 1) if size_bytes else 0
        param_size = details.get("parameter_size") or ""
        desc = " · ".join(
            str(p) for p in (param_size, f"{size_gb} GB" if size_gb else "") if p
        )
        out.append(
            _finalise(
                ModelInfo(
                    id=str(entry["name"]),
                    provider="ollama",
                    name=str(entry["name"]),
                    input_price_per_1m=0.0,
                    output_price_per_1m=0.0,
                    description=desc,
                    validated_at=validated_at,
                    quota_available=True,
                )
            )
        )
    return out


# ───────────────────────── HTTP discovery ─────────────────────────


def _build_request(provider: str, api_key: str, base_url: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """Return ``(url, headers, params)`` for the provider's list-models call."""
    root = base_url.rstrip("/")

    if provider == "openrouter":
        # openrouter_base_url is stored without the /v1 suffix.
        url = root if root.endswith("/v1") else f"{root}/v1"
        return f"{url}/models", {"Authorization": f"Bearer {api_key}"}, {}

    if provider == "anthropic":
        url = root.removesuffix("/v1")
        return (
            f"{url}/v1/models?limit=100",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            {},
        )

    if provider == "gemini":
        url = root if root.endswith(("/v1beta", "/v1")) else f"{root}/v1beta"
        return f"{url}/models", {}, {"key": api_key, "pageSize": "200"}

    if provider == "ollama":
        return f"{root}/api/tags", {}, {}

    # OpenAI-compatible: base URL already ends in /v1 for every spec default.
    url = root if root.endswith("/v1") else f"{root}/v1"
    return f"{url}/models", {"Authorization": f"Bearer {api_key}"}, {}


def _parse_payload(provider: str, payload: dict[str, Any]) -> list[ModelInfo]:
    if provider == "openrouter":
        return _parse_openrouter(payload)
    if provider == "anthropic":
        return _parse_anthropic(payload)
    if provider == "gemini":
        return _parse_gemini(payload)
    if provider == "ollama":
        return _parse_ollama(payload)
    if provider in _OPENAI_COMPATIBLE:
        return _parse_openai_compatible(payload, provider)
    return []


async def _fetch_models(provider: str, api_key: str, base_url: str) -> list[ModelInfo]:
    """Query *provider* for its catalog. Raises on transport/HTTP failure."""
    url, headers, params = _build_request(provider, api_key, base_url)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(url, headers=headers, params=params or None)
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError(f"{provider}: unexpected payload type {type(payload).__name__}")
    models = _parse_payload(provider, payload)
    models.sort(key=lambda m: (not m.free, m.name.lower()))
    return models


def _explain_http_error(provider: str, exc: httpx.HTTPStatusError) -> str:
    """Turn a status code into something a user can act on."""
    code = exc.response.status_code
    if code in (401, 403):
        return "Chave API inválida ou sem permissões."
    if code == 404:
        return f"Endpoint não encontrado ({exc.request.url}). Verifica o base URL."
    if code == 429:
        return "Rate limit atingido. Tenta novamente dentro de um minuto."
    if code >= 500:
        return f"{PROVIDER_SPECS.get(provider, {}).get('label', provider)} está com problemas (HTTP {code})."
    detail = ""
    try:
        body = exc.response.json()
        detail = str(body.get("error", {}).get("message") or body.get("message") or "")[:160]
    except Exception:  # noqa: BLE001 - body may be empty or not JSON
        detail = exc.response.text[:160]
    return f"HTTP {code}{f': {detail}' if detail else ''}"


def _explain_error(provider: str, exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return _explain_http_error(provider, exc)
    if isinstance(exc, httpx.ConnectError):
        if provider == "ollama":
            return "Ollama não está a correr em localhost:11434."
        return "Não foi possível ligar ao provider."
    if isinstance(exc, httpx.TimeoutException):
        return f"Timeout após {HTTP_TIMEOUT:.0f}s."
    return str(exc)[:200] or exc.__class__.__name__


# ───────────────────────────── cache ─────────────────────────────


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _stale_models(raw_models: list[dict[str, Any]]) -> list[ModelInfo]:
    """Keep stale entries visible, but make them ineligible for selection."""
    models: list[ModelInfo] = []
    for raw in raw_models:
        try:
            model = ModelInfo(**raw)
        except TypeError:
            continue
        model.free = False
        model.pricing = "unknown"
        model.reason = "stale catalog validation"
        models.append(model)
    return models


def _write_cache(cache: dict[str, Any]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False)
        tmp.replace(CACHE_PATH)
    except OSError as exc:
        logger.warning("Could not persist model catalog cache: %s", exc)


def _cache_entry(provider: str, models: list[ModelInfo]) -> dict[str, Any]:
    return {
        "fetched_at": time.time(),
        "models": [m.to_dict() for m in models],
    }


def invalidate_cache(provider: str | None = None) -> None:
    """Drop cached models — call after an API key changes."""
    if provider is None:
        cache: dict[str, Any] = {}
    else:
        cache = _load_cache()
        cache.pop(provider, None)
    _write_cache(cache)


# ────────────────────────── public API ──────────────────────────


@dataclass(slots=True)
class DiscoveryResult:
    """Outcome of one provider lookup, including why it may be empty."""

    provider: str
    models: list[ModelInfo]
    cached: bool = False
    fetched_at: float = 0.0
    error: str | None = None
    configured: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "label": PROVIDER_SPECS.get(self.provider, {}).get("label", self.provider),
            "models": [m.to_dict() for m in self.models],
            "count": len(self.models),
            "cached": self.cached,
            "fetched_at": self.fetched_at,
            "error": self.error,
            "configured": self.configured,
        }


async def discover_models(provider: str, *, refresh: bool = False) -> DiscoveryResult:
    """List the models *provider* exposes, using the disk cache when fresh."""
    if provider not in PROVIDER_SPECS:
        return DiscoveryResult(provider, [], error=f"Provider desconhecido: {provider}", configured=False)

    api_key, base_url = resolve_credentials(provider)
    spec = PROVIDER_SPECS[provider]
    if spec["requires_key"] and not api_key:
        return DiscoveryResult(
            provider, [], error="Sem chave API configurada.", configured=False
        )

    cache = _load_cache()
    entry = cache.get(provider)
    if not refresh and isinstance(entry, dict):
        age = time.time() - float(entry.get("fetched_at") or 0)
        if age < CACHE_TTL_SECONDS:
            models = [ModelInfo(**m) for m in entry.get("models", [])]
            return DiscoveryResult(
                provider, models, cached=True, fetched_at=float(entry.get("fetched_at") or 0)
            )

    try:
        models = await _fetch_models(provider, api_key, base_url)
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never raised
        message = _explain_error(provider, exc)
        logger.warning("Model discovery failed for %s: %s", provider, message)
        # Serve stale data rather than an empty list: a rate limit should not
        # wipe the user's model selector.
        if isinstance(entry, dict) and entry.get("models"):
            stale = _stale_models(entry["models"])
            return DiscoveryResult(
                provider,
                stale,
                cached=True,
                fetched_at=float(entry.get("fetched_at") or 0),
                error=f"{message} (a mostrar catálogo em cache)",
            )
        return DiscoveryResult(provider, [], error=message)

    cache[provider] = _cache_entry(provider, models)
    _write_cache(cache)
    return DiscoveryResult(provider, models, fetched_at=time.time())


async def validate_api_key(provider: str, api_key: str | None = None) -> dict[str, Any]:
    """Check a key by listing models with it. Never persists anything."""
    if provider not in PROVIDER_SPECS:
        return {"valid": False, "error": f"Provider desconhecido: {provider}", "models_count": 0}

    spec = PROVIDER_SPECS[provider]
    stored_key, base_url = resolve_credentials(provider)
    candidate = (api_key or stored_key or "").strip()

    if spec["requires_key"] and not candidate:
        return {"valid": False, "error": "Nenhuma chave API fornecida.", "models_count": 0}

    started = time.perf_counter()
    try:
        models = await _fetch_models(provider, candidate, base_url)
    except Exception as exc:  # noqa: BLE001 - the error text is the payload
        return {
            "valid": False,
            "error": _explain_error(provider, exc),
            "models_count": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    return {
        "valid": True,
        "error": None,
        "models_count": len(models),
        "free_count": sum(1 for m in models if m.free),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "sample": [m.id for m in models[:5]],
    }


async def aggregate_models(*, refresh: bool = False) -> dict[str, Any]:
    """Union of the catalogs of every provider that has a usable key."""
    providers = list(PROVIDER_SPECS)
    results = await asyncio.gather(
        *(discover_models(p, refresh=refresh) for p in providers),
        return_exceptions=True,
    )

    models: list[ModelInfo] = []
    per_provider: list[dict[str, Any]] = []
    for provider, result in zip(providers, results, strict=False):
        if isinstance(result, BaseException):
            per_provider.append(
                DiscoveryResult(provider, [], error=_explain_error(provider, result)).to_dict()
            )
            continue
        models.extend(result.models)
        summary = result.to_dict()
        summary.pop("models", None)  # keep the response small
        per_provider.append(summary)

    # Free first, then cheapest, then alphabetical — the order the selector shows.
    models.sort(
        key=lambda m: (
            not m.free,
            m.input_price_per_1m if m.input_price_per_1m is not None else 9_999,
            m.name.lower(),
        )
    )
    return {"models": [m.to_dict() for m in models], "providers": per_provider}


def list_provider_specs() -> list[dict[str, Any]]:
    """Provider metadata for the Settings UI, including whether a key is set."""
    out: list[dict[str, Any]] = []
    for provider, spec in PROVIDER_SPECS.items():
        api_key, base_url = resolve_credentials(provider)
        out.append(
            {
                "id": provider,
                "label": spec["label"],
                "key_setting": spec["key_setting"],
                "requires_key": spec["requires_key"],
                "api_key_set": bool(api_key),
                "base_url": base_url,
                "docs": spec["docs"],
            }
        )
    return out
