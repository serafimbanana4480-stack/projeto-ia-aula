"""Dashboard routes for models status.

Provides `/api/models/status` endpoint.
Note: `/api/dashboard/stream` is now in `backend/observability/routes/metrics.py`
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models/status")
async def models_status() -> list[dict]:
    """Return status of available models from Ollama.

    Queries Ollama API to get installed models with metadata.
    """
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:11434/api/tags", timeout=5.0)
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("models", []):
                models.append(
                    {
                        "id": model.get("name"),
                        "size_bytes": model.get("size", 0),
                        "size_gb": round(model.get("size", 0) / 1e9, 2),
                        "modified_at": model.get("modified_at"),
                        "details": model.get("details", {}),
                        "status": "available",
                    }
                )

            return models
    except Exception as e:
        logger.warning("Failed to fetch models from Ollama: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Ollama model inventory is unavailable",
        ) from e
