"""Token pricing table loaded from config/models.yaml.

Provides a :class:`PricingTable` singleton that maps model names to
per-1M-token prices (input/output) and a helper to compute cost from
token counts.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Path relative to this file: ../../config/models.yaml
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"

_DEFAULT_PRICES = {"input_price_per_1m": 0.0, "output_price_per_1m": 0.0}

# Conservative rates for models whose price is UNKNOWN (audit 2026-08-24,
# blocker B4: unknown used to count as $0, systematically under-reporting
# spend exactly when it matters most). Overridable via env.
_CONSERVATIVE_INPUT_ENV = "NEXUS_UNKNOWN_PRICE_USD_PER_1M_INPUT"
_CONSERVATIVE_OUTPUT_ENV = "NEXUS_UNKNOWN_PRICE_USD_PER_1M_OUTPUT"
_DEFAULT_CONSERVATIVE_IN = 2.5
_DEFAULT_CONSERVATIVE_OUT = 10.0


def _env_rate(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid %s=%r — using %s", name, raw, default)
        return default


def conservative_unknown_prices() -> dict[str, float]:
    """Upper-bound rates assumed for models with unknown pricing."""
    return {
        "input_price_per_1m": _env_rate(_CONSERVATIVE_INPUT_ENV, _DEFAULT_CONSERVATIVE_IN),
        "output_price_per_1m": _env_rate(_CONSERVATIVE_OUTPUT_ENV, _DEFAULT_CONSERVATIVE_OUT),
    }


# Providers whose live catalog may carry prices (mirrors factory registrations).
_CATALOG_PROVIDERS = (
    "openrouter",
    "openai",
    "deepseek",
    "groq",
    "kimi",
    "opencode_go",
    "anthropic",
    "gemini",
)


def _catalog_prices(model: str, provider: str | None) -> dict[str, float] | None:
    """Look up per-1M prices in the live model catalog (disk-cached).

    Never raises and never triggers network refreshes — only reads whatever
    cache ``load_validated_models`` already holds, so cost accounting stays
    cheap and side-effect free.
    """
    try:
        from backend.llm.model_catalog import ModelInfo, load_validated_models

        providers = (provider,) if provider else _CATALOG_PROVIDERS
        wanted = str(model).strip().lower()
        last_segment = wanted.rsplit("/", 1)[-1]
        for prov in providers:
            try:
                infos: list[ModelInfo] = load_validated_models(prov)
            except Exception:  # noqa: BLE001 — catalog is best-effort only
                continue
            for info in infos or []:
                info_id = str(getattr(info, "model_id", "") or "").lower()
                if not info_id:
                    continue
                if info_id == wanted or info_id.endswith("/" + wanted) or (
                    "/" not in wanted and info_id.rsplit("/", 1)[-1] == last_segment
                ):
                    in_price = getattr(info, "input_price_per_1m", None)
                    out_price = getattr(info, "output_price_per_1m", None)
                    if in_price is None or out_price is None:
                        return None
                    return {
                        "input_price_per_1m": float(in_price),
                        "output_price_per_1m": float(out_price),
                    }
    except Exception:  # noqa: BLE001 — pricing must never break a chat
        logger.debug("Catalog price lookup failed for %s", model, exc_info=True)
    return None


def _load_pricing_from_yaml(path: Path | str) -> dict[str, dict[str, float]]:
    """Load the ``pricing`` section from ``models.yaml``.

    Returns a dict::

        {model_id: {"input_price_per_1m": float, "output_price_per_1m": float}}

    Returns an empty dict if the file or section is missing.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not data or "pricing" not in data:
            logger.debug("No 'pricing' section found in %s", path)
            return {}
        return {
            model: {
                "input_price_per_1m": float(entry.get("input_price_per_1m", 0.0)),
                "output_price_per_1m": float(entry.get("output_price_per_1m", 0.0)),
            }
            for model, entry in data["pricing"].items()
        }
    except FileNotFoundError:
        logger.warning("Config file not found: %s", path)
        return {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse YAML pricing: %s", exc)
        return {}


class PricingTable:
    """Singleton pricing table that maps model IDs to per-1M-token costs.

    Usage::

        pt = PricingTable()
        cost = pt.compute_cost(model="gpt-4o", input_tokens=500, output_tokens=200)
        # cost = (500/1_000_000) * 2.50 + (200/1_000_000) * 10.00
    """

    _instance: PricingTable | None = None

    def __init__(self, config_path: Path | str | None = None) -> None:
        self._prices = _load_pricing_from_yaml(config_path or _CONFIG_PATH)

    @classmethod
    def get_instance(cls, config_path: Path | str | None = None) -> PricingTable:
        """Return the global singleton, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls(config_path=config_path)
        return cls._instance

    def get_prices(self, model: str) -> dict[str, float]:
        """Return per-1m prices for *model*, falling back to defaults.

        Args:
            model: The model identifier (e.g. ``gpt-4o``, ``deepseek-v4-flash``).

        Returns:
            Dict with ``input_price_per_1m`` and ``output_price_per_1m`` keys.
        """
        prices = self._prices.get(model) or self._prices.get(model.lower())
        if prices is not None:
            return prices
        # Fallback: try a case-insensitive match
        for key, val in self._prices.items():
            if key.lower() == model.lower():
                return val
        return dict(_DEFAULT_PRICES)

    def has_pricing(self, model: str) -> bool:
        """Return True if we have explicit pricing for *model*."""
        return model in self._prices or model.lower() in {k.lower() for k in self._prices}

    def resolve_prices(
        self,
        model: str,
        provider: str | None = None,
    ) -> tuple[dict[str, float], str] | None:
        """Best-effort price resolution with source label.

        Order:
          1. Static ``config/models.yaml`` table.
          2. Live model catalog (cached, refreshed in background) — covers
             models added after the YAML was written (B4 fix).

        Returns ``(prices, source)`` or ``None`` when nothing is known.
        """
        static = self.get_prices(model)
        if self.has_pricing(model):
            return dict(static), "yaml"

        catalog = _catalog_prices(model, provider)
        if catalog is not None:
            return catalog, "catalog"
        return None

    def compute_cost(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        *,
        provider: str | None = None,
        conservative_unknown: bool = False,
    ) -> float:
        """Compute the cost in USD for a given model and token counts.

        Uses per-1M-token rates from: YAML → live catalog → (optionally)
        conservative upper-bound rates for unknown models. Returns 0.0 only
        for models whose price resolves to zero (free/local) — never because
        the price is unknown.
        """
        resolved = self.resolve_prices(model, provider)
        if resolved is not None:
            prices, _source = resolved
        elif conservative_unknown:
            prices = conservative_unknown_prices()
            logger.warning(
                "Preço desconhecido para '%s' (provider=%s) — a usar taxas "
                "conservadoras %s para não sub-repor custo. Define o preço em "
                "config/models.yaml ou atualiza o catálogo.",
                model,
                provider or "?",
                prices,
            )
        else:
            return 0.0
        input_price = (input_tokens / 1_000_000) * prices["input_price_per_1m"]
        output_price = (output_tokens / 1_000_000) * prices["output_price_per_1m"]
        return round(input_price + output_price, 6)

    def reload(self, config_path: Path | str | None = None) -> None:
        """Reload pricing from the YAML file (useful after hot-reload)."""
        self._prices = _load_pricing_from_yaml(config_path or _CONFIG_PATH)


__all__ = ["PricingTable", "conservative_unknown_prices"]
