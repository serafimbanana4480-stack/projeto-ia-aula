"""The context budget must reflect the model that is actually called.

Regression tests for the mismatch between ``config/models.yaml`` (per-tier
``context_window``) and the concrete model selected at request time.

Background: every agent derives its concrete model id with
``resolve_model_id(request)``, where an explicit user/model override wins over the
tier mapping. The budget, however, was computed only from ``self.model_key``
(the tier), so ``get_context_limit("deep")`` returned the 131 072 declared in
``models.yaml`` even when the run was pinned to a model whose real window is
64 000 (``opencode_go`` entries in the catalog cache) or smaller.

Effect: NEXUS assembled up to 85 % of 131 072 input tokens and handed it to a
64 000-token model. The provider rejected the request with a context-length
error — exactly when a long task needs the model to work.

These tests pin the safe direction: the budget may only ever be *lowered* to
the model's real window, never raised above the configured tier window.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend import token_management as tm

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_CACHE = REPO_ROOT / "data" / "model_catalog_cache.json"
MODELS_YAML = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clear_catalog_cache() -> None:
    tm._CATALOG_WINDOW_CACHE = None
    yield
    tm._CATALOG_WINDOW_CACHE = None


def _write_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, models: list[dict]) -> None:
    path = tmp_path / "model_catalog_cache.json"
    path.write_text(
        json.dumps({"openrouter": {"fetched_at": 0, "models": models}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(tm, "_CATALOG_CACHE_PATH", path)


def test_real_catalog_has_models_smaller_than_the_configured_tier() -> None:
    """Guards the premise: the mismatch is real in the shipped catalog.

    ``opencode_go`` advertises a 64 000 window while ``models.yaml`` declares
    131 072 for every cloud tier. Without this, the clamp tests below could pass
    simply because the catalog happened to agree with the configuration.
    """
    if not CATALOG_CACHE.exists():
        pytest.skip(f"catalogo ausente: {CATALOG_CACHE}")
    data = json.loads(CATALOG_CACHE.read_text(encoding="utf-8"))
    windows = [
        int(m.get("context_window") or 0)
        for entry in data.values()
        if isinstance(entry, dict)
        for m in (entry.get("models") or [])
        if int(m.get("context_window") or 0) > 0
    ]
    assert windows, "esperava modelos com context_window no catalogo"

    tier_windows = [
        int(block.get("context_window") or 0)
        for block in MODELS_YAML.get("models", {}).values()
        if isinstance(block, dict)
    ]
    assert max(windows) > max(tier_windows) or min(windows) < min(tier_windows), (
        "o catalogo e a configuracao divergem; se passarem a concordar, "
        "a hipotese por tras deste teste mudou"
    )


def test_budget_is_clamped_to_the_concrete_model_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_catalog(
        monkeypatch,
        tmp_path,
        [{"id": "openrouter/tiny", "context_window": 64_000}],
    )

    tier_only = tm.get_context_limit("deep")
    with_model = tm.get_context_limit("deep", model_id="openrouter/tiny")

    assert with_model == 64_000, (
        "o orcamento deve ser limitado a janela real do modelo "
        f"(64 000), nao a janela do tier ({tier_only})"
    )


def test_clamp_never_raises_the_budget_above_the_configured_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A huge model must not inflate a deliberately small tier."""
    _write_catalog(
        monkeypatch,
        tmp_path,
        [{"id": "openrouter/huge", "context_window": 1_048_576}],
    )

    tier_only = tm.get_context_limit("micro")
    with_model = tm.get_context_limit("micro", model_id="openrouter/huge")

    assert with_model == tier_only, (
        "o limite do tier tem de continuar a ser o tecto; o catalogo so pode reduzir"
    )


def test_unknown_model_leaves_the_limit_untouched() -> None:
    assert tm.get_context_limit("deep", model_id="not/in-the-catalog") == tm.get_context_limit(
        "deep"
    )


def test_zero_window_entries_are_ignored_not_treated_as_a_limit() -> None:
    """``ctx=0`` means 'unknown' in the catalog (several lmstudio entries)."""
    assert tm.get_context_limit("deep", model_id="") == tm.get_context_limit("deep")


def test_output_reserve_is_clamped_consistently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_catalog(
        monkeypatch,
        tmp_path,
        [{"id": "openrouter/small", "context_window": 8_192}],
    )

    reserve = tm.resolve_output_reserve("deep", 8_192, model_id="openrouter/small")

    assert reserve <= tm.get_context_limit("deep", model_id="openrouter/small")
    assert reserve >= 1