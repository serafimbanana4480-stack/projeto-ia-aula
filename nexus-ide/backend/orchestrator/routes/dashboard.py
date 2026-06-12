"""Dashboard routes for models status.

Note: `/api/models/status` is now in `backend/observability/routes/metrics.py`
which fetches real Ollama models. This module is kept as a placeholder for
future dashboard-specific endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()
