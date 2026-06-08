"""System-level REST API — self-improvement and global controls.

Endpoints:
    GET  /api/system/self-improvement      view latest improvement proposals
    POST /api/system/self-improvement/run  trigger analysis on demand
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.core.self_improvement import SelfImprovementAnalyzer
from backend.middleware.auth import require_auth
from backend.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/system/self-improvement")
@limiter.limit("60/minute")
async def get_self_improvement(request: Request, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Return the latest self-improvement report."""
    analyzer = SelfImprovementAnalyzer()
    report = analyzer.get_last_report()
    if not report:
        raise HTTPException(status_code=404, detail="No self-improvement report available")
    return report.model_dump(mode="json")


@router.post("/system/self-improvement/run")
@limiter.limit("10/minute")
async def run_self_improvement(request: Request, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Trigger the self-improvement analysis on demand."""
    analyzer = SelfImprovementAnalyzer()
    try:
        report = await analyzer.run_analysis()
    except Exception as exc:
        logger.exception("Self-improvement analysis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "success": True,
        "report": report.model_dump(mode="json"),
    }
