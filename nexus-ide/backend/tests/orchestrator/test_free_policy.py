from __future__ import annotations

import time

from backend.llm.free_policy import FreeModelPolicy, FreeModelRequirement, ModelEligibility
def _model(model_id: str, provider: str = "openrouter", **kwargs: object) -> dict[str, object]:
    return {
        "id": model_id,
        "provider": provider,
        "free": kwargs.pop("free", True),
        "input_price_per_1m": kwargs.pop("input_price_per_1m", 0),
        "output_price_per_1m": kwargs.pop("output_price_per_1m", 0),
        "quota_available": kwargs.pop("quota_available", True),
        "validated_at": kwargs.pop("validated_at", time.time()),
        **kwargs,
    }


def test_paid_and_unconfirmed_models_are_rejected() -> None:
    policy = FreeModelPolicy()
    candidates = [
        _model("paid", input_price_per_1m=1, output_price_per_1m=1, free=False),
        {"id": "kimi-k2.7-code", "provider": "openrouter", "free": True},
    ]
    assert policy.select(FreeModelRequirement(), candidates, {}) is None


def test_confirmed_openrouter_free_router_is_selected() -> None:
    selection = FreeModelPolicy().select(
        FreeModelRequirement(), [_model("openrouter/free")], {}
    )
    assert selection is not None
    assert selection.source == "openrouter_router"
    assert selection.simulation is False


def test_capability_quota_latency_and_breaker_filters_apply() -> None:
    requirement = FreeModelRequirement(
        tool_calling=True, structured_output=True, min_context=100, max_latency_ms=100
    )
    candidate = _model(
        "specific-free",
        capabilities=["tools", "json_schema"],
        context_window=200,
        latency_ms=50,
    )
    assert FreeModelPolicy().select(requirement, [candidate], {}) is not None
    assert FreeModelPolicy().select(requirement, [candidate], {"openrouter": {"state": "open"}}) is None
    candidate["quota_available"] = False
    assert FreeModelPolicy().select(requirement, [candidate], {}) is None


def test_ollama_requires_opt_in_and_installed_model() -> None:
    policy = FreeModelPolicy()
    assert policy.select(FreeModelRequirement(), [], {"ollama": {}}, {"enabled": False, "models": ["local"]}) is None
    selection = policy.select(
        FreeModelRequirement(), [], {}, {"enabled": True, "models": ["qwen2.5:1.5b"]}
    )
    assert selection is not None
    assert selection.source == "ollama"
    assert selection.provider == "ollama"


def test_simulation_is_explicitly_marked() -> None:
    eligibility = ModelEligibility(
        model_id="dev",
        provider="dev",
        free=True,
        quota_available=True,
        validated_at=time.time(),
    )
    selection = FreeModelPolicy().select(FreeModelRequirement(), [eligibility], {})
    assert selection is not None
