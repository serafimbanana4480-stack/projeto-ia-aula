#!/usr/bin/env python3
"""Pre-download and layer-split AirLLM models for offline use.

Usage:
    python scripts/setup-airllm-models.py [model_id ...]

Examples:
    python scripts/setup-airllm-models.py qwen3.5:4b coder
    python scripts/setup-airllm-models.py --all
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from llm.airllm_provider import DEFAULT_MODEL_REGISTRY, _load_airllm_model

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def predownload_model(friendly_id: str, device: str = "cpu") -> None:
    """Download and split a model into layer shards."""
    repo_id = DEFAULT_MODEL_REGISTRY.get(friendly_id, friendly_id)
    logger.info("=" * 60)
    logger.info("Processing: %s -> %s", friendly_id, repo_id)
    logger.info("Device: %s", device)
    logger.info("This may take several minutes for large models...")
    logger.info("=" * 60)

    try:
        model = _load_airllm_model(repo_id, device=device, compression=None)
        logger.info("SUCCESS: %s is ready", friendly_id)
        # Keep reference to prevent GC, then release
        del model
    except Exception as exc:
        logger.error("FAILED: %s -> %s", friendly_id, exc)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-download AirLLM models")
    parser.add_argument(
        "models",
        nargs="*",
        help="Model IDs to pre-download (aliases from models.yaml)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all models in the default registry",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Device to use for splitting (cpu or cuda:0)",
    )
    args = parser.parse_args()

    if args.all:
        models = list(DEFAULT_MODEL_REGISTRY.keys())
    elif args.models:
        models = args.models
    else:
        # Default essential models
        models = ["micro", "fast", "coder"]

    failed = []
    for m in models:
        try:
            predownload_model(m, device=args.device)
        except Exception:
            failed.append(m)

    if failed:
        logger.error("Failed models: %s", failed)
        return 1

    logger.info("All models ready!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
