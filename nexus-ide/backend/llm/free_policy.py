"""Typed, fail-closed policy for selecting zero-cost LLM providers.

The runtime may use a cloud model only after a live catalog has proved both
input and output prices are exactly zero. Missing/stale prices are unknown,
not free. Local Ollama models are eligible only when the caller supplies an
installed, enabled local catalog entry.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class FreeModelRequirement:
    tool_calling: bool = False
    structured_output: bool = False
    min_context: int = 0
    max_latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ModelEligibility:
    model_id: str
    provider: str
    free: bool
    capabilities: tuple[str, ...] = ()
    context_window: int = 0
    quota_available: bool | None = None
    latency_ms: float | None = None
    validated_at: float | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    provider: str
    model: str
    source: str
    validated_at: float | None
    simulation: bool = False
    eligibility: ModelEligibility | None = None

    @property
    def model_id(self) -> str:
        return self.model


class ProviderUnavailableError(RuntimeError):
    """Bounded, machine-readable provider failure."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "provider_unavailable",
        provider: str | None = None,
        model: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.provider = provider
        self.model = model
        self.retry_after = retry_after

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": str(self),
            "category": self.category,
            "provider": self.provider,
            "model": self.model,
            "retry_after": self.retry_after,
        }


def _value(candidate: Any, key: str, default: Any = None) -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get(key, default)
    return getattr(candidate, key, default)


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _eligibility(candidate: Any) -> ModelEligibility:
    if isinstance(candidate, ModelEligibility):
        return candidate
    provider = str(_value(candidate, "provider", "")).strip().lower()
    model_id = str(_value(candidate, "model_id", _value(candidate, "id", ""))).strip()
    caps = _value(candidate, "capabilities", ()) or ()
    if isinstance(caps, str):
        caps = (caps,)
    else:
        caps = tuple(str(item) for item in caps)
    input_price = _value(candidate, "input_price_per_1m", None)
    output_price = _value(candidate, "output_price_per_1m", None)
    verified_prices = input_price == 0 and output_price == 0
    local_verified = provider == "ollama" and bool(_value(candidate, "installed", True))
    free = bool(_value(candidate, "free", False)) and (verified_prices or local_verified)
    if local_verified:
        free = True
    quota_available = _value(candidate, "quota_available", None)
    latency_ms = _number(_value(candidate, "latency_ms", None))
    validated_at = _number(_value(candidate, "validated_at", None))
    reason = str(_value(candidate, "reason", "") or "")
    if not free and not reason:
        reason = "prices are not confirmed as zero" if provider != "ollama" else "local model is not installed"
    try:
        context_window = int(_value(candidate, "context_window", 0) or 0)
    except (TypeError, ValueError):
        context_window = 0
    return ModelEligibility(
        model_id=model_id,
        provider=provider,
        free=free,
        capabilities=caps,
        context_window=max(0, context_window),
        quota_available=quota_available,
        latency_ms=latency_ms if latency_ms is None or latency_ms >= 0 else None,
        validated_at=validated_at,
        reason=reason,
    )


def _breaker_open(breaker: Any) -> tuple[bool, float | None]:
    if breaker is None:
        return False, None
    state = _value(breaker, "state", _value(breaker, "_state", ""))
    state = getattr(state, "value", state)
    if isinstance(breaker, Mapping):
        state = breaker.get("state", state)
    opened = str(state).lower() in {"open", "circuitstate.open"}
    retry_after = _value(breaker, "retry_after", None)
    if isinstance(breaker, Mapping):
        retry_after = breaker.get("retry_after", retry_after)
    return opened, retry_after


def _has_capability(caps: Iterable[str], names: set[str]) -> bool:
    normalized = {str(cap).lower().replace("-", "_") for cap in caps}
    return bool(normalized & names)


class FreeModelPolicy:
    """Select the first validated free model satisfying a requirement."""

    def __init__(self, *, validation_ttl_seconds: int = 600) -> None:
        self.validation_ttl_seconds = max(1, int(validation_ttl_seconds))
    def select(
        self,
        requirement: FreeModelRequirement,
        candidates: Iterable[Any],
        breakers: Mapping[str, Any] | None = None,
        local_models: Any = None,
    ) -> ProviderSelection | None:
        breakers = breakers or {}
        normalized = [_eligibility(item) for item in candidates]
        local = self._local_eligibilities(local_models)
        ordered = [item for item in normalized if item.provider != "ollama"] + local
        now = time.time()
        for item in ordered:
            if not item.model_id or not item.free:
                continue
            if item.provider != "ollama":
                if item.validated_at is None:
                    continue
                age = now - item.validated_at
                if age < 0 or age > self.validation_ttl_seconds:
                    continue
            open_, _ = _breaker_open(breakers.get(item.provider))
            if open_:
                continue
            if item.quota_available is not True:
                continue
            if item.context_window < requirement.min_context:
                continue
            # OpenRouter and Kilo publish live model catalogs without a
            # per-account latency sample. Unknown latency is not a failure;
            # only an observed sample above the requested ceiling is rejected.
            if (
                requirement.max_latency_ms is not None
                and item.latency_ms is not None
                and item.latency_ms > requirement.max_latency_ms
            ):
                continue
            caps = item.capabilities
            if requirement.tool_calling and not _has_capability(
                caps, {"tool_calling", "tools", "function_calling", "functions"}
            ):
                continue
            if requirement.structured_output and not _has_capability(
                caps, {"structured_output", "json", "json_schema", "structured"}
            ):
                continue
            simulation = item.provider in {"dev", "mock", "simulation"}
            if item.provider == "ollama":
                source = "ollama"
            elif item.model_id == "openrouter/free":
                source = "openrouter_router"
            else:
                source = "specific_free"
            return ProviderSelection(
                provider=item.provider,
                model=item.model_id,
                source=source,
                validated_at=item.validated_at,
                simulation=simulation,
                eligibility=item,
            )

    @staticmethod
    def _local_eligibilities(local_models: Any) -> list[ModelEligibility]:
        if local_models is None:
            return []
        enabled = True
        values: Any = local_models
        if isinstance(local_models, Mapping):
            enabled = _bool_value(
                local_models.get("enabled", local_models.get("ollama_enabled", False))
            )
            values = local_models.get("models", local_models.get("installed", []))
        if not enabled:
            return []
        if isinstance(values, (str, bytes)):
            values = [values]
        result: list[ModelEligibility] = []
        for value in values or []:
            if isinstance(value, str):
                result.append(
                    ModelEligibility(
                        model_id=value,
                        provider="ollama",
                        free=True,
                        quota_available=True,
                        validated_at=time.time(),
                        reason="verified installed Ollama model",
                    )
                )
                continue
            item = _eligibility(value)
            installed = _bool_value(_value(value, "installed", True), False)
            healthy = _bool_value(_value(value, "healthy", True), False)
            if item.provider != "ollama" or (installed and healthy and not item.free):
                item = ModelEligibility(
                    model_id=item.model_id,
                    provider="ollama",
                    free=installed and healthy,
                    capabilities=item.capabilities,
                    context_window=item.context_window,
                    quota_available=True if installed and healthy else item.quota_available,
                    latency_ms=item.latency_ms if item.latency_ms is not None else 0.0,
                    validated_at=item.validated_at or (time.time() if installed and healthy else None),
                    reason=item.reason or "verified installed Ollama model",
                )
            if installed and healthy and item.validated_at is not None:
                result.append(item)
        return result
