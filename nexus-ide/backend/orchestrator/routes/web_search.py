"""Web search endpoint — exposes the web_search tool as a REST API."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.tools.web_search import web_search as _web_search

logger = logging.getLogger(__name__)

router = APIRouter()


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    max_results: int = Field(default=10, ge=1, le=50)


@router.post("/web_search")
async def web_search_endpoint(req: WebSearchRequest) -> list[dict]:
    """Perform a web search via DuckDuckGo."""
    results = await _web_search(query=req.query, max_results=req.max_results)
    return [
        {
            "title": r.title,
            "url": r.url,
            "snippet": r.snippet,
        }
        for r in results
    ]
