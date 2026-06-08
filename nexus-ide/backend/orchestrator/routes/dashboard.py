"""Dashboard routes for models status.

Provides `/api/models/status` endpoint.
Note: `/api/dashboard/stream` is now in `backend/observability/routes/metrics.py`
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from backend.middleware.auth import require_auth

from backend.llm.airllm_provider import DEFAULT_MODEL_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models/status")
async def models_status(_user: dict = Depends(require_auth)) -> list[dict]:
    """Return status of available local models.

    Returns the AirLLM model registry with availability status.
    """
    try:
        models = []
        for model_id, repo_id in DEFAULT_MODEL_REGISTRY.items():
            models.append(
                {
                    "id": model_id,
                    "repo_id": repo_id,
                    "size_gb": None,  # Would require probing HF API
                    "status": "registered",
                    "provider": "airllm",
                }
            )
        return models
    except Exception as e:
        logger.warning("Failed to fetch model registry: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Local model registry is unavailable",
        ) from e
