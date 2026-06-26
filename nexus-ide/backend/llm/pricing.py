"""Token pricing table loaded from config/models.yaml.

Provides a :class:`PricingTable` singleton that maps model names to
per-1M-token prices (input/output) and a helper to compute cost from
token counts.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Path relative to this file: ../../config/models.yaml
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"

_DEFAULT_PRICES = {"input_price_per_1m": 0.0, "output_price_per_1m": 0.0}


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

    def compute_cost(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> float:
        """Compute the cost in USD for a given model and token counts.

        Uses the per-1M-token rates from the pricing table.
        Returns 0.0 for unlisted models (assumes free/local).
        """
        prices = self.get_prices(model)
        input_price = (input_tokens / 1_000_000) * prices["input_price_per_1m"]
        output_price = (output_tokens / 1_000_000) * prices["output_price_per_1m"]
        return round(input_price + output_price, 6)

    def reload(self, config_path: Path | str | None = None) -> None:
        """Reload pricing from the YAML file (useful after hot-reload)."""
        self._prices = _load_pricing_from_yaml(config_path or _CONFIG_PATH)


__all__ = ["PricingTable"]
