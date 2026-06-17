from fastapi import APIRouter
from pathlib import Path
import yaml

router = APIRouter()


@router.get("/models/available")
async def list_available_models() -> list[dict[str, object]]:
    config_path = (
        Path(__file__).resolve().parents[3] / ".." / ".." / "config" / "models.yaml"
    ).resolve()
    if not config_path.exists():
        raise FileNotFoundError(
            f"models.yaml not found at {config_path}. "
            "Please ensure the config file exists."
        )
    with open(config_path, "r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file)

    output: list[dict[str, object]] = []

    models_cfg = data.get("models", {})
    for tier, cfg in models_cfg.items():
        if not isinstance(cfg, dict):
            continue
        model_id = cfg.get("id")
        if not model_id:
            continue
        provider = "openrouter" if "/" in str(model_id) else "ollama"
        output.append(
            {
                "id": model_id,
                "name": cfg.get("name") or model_id,
                "tier": tier,
                "provider": provider,
                "pricing": cfg.get("pricing", "free"),
                "estimated_tokens_per_sec": cfg.get("estimated_tokens_per_sec", 0),
            }
        )

    return output
