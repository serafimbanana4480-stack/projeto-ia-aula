"""Embeddings endpoints — index a codebase and search it semantically."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.workspace_security import _is_blocked_path
from backend.middleware.auth import require_auth
from backend.tools.embeddings import (
    get_index_stats,
    index_codebase,
    search_codebase,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class IndexRequest(BaseModel):
    project_path: str = Field(
        min_length=1, max_length=2000, description="Absolute path to the project root to index"
    )
    force_reindex: bool = Field(
        default=False, description="Ignore the existing snapshot and rebuild the index"
    )


class IndexResponse(BaseModel):
    chunks_indexed: int
    total_chunks: int
    project_path: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000, description="Natural-language search query")
    k: int = Field(default=8, ge=1, le=50, description="Maximum number of results")


class SearchResultItem(BaseModel):
    file: str
    start_line: int
    end_line: int
    score: float
    language: str
    symbol_name: str
    symbol_type: str
    content: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    total_found: int


class StatsResponse(BaseModel):
    total_chunks: int
    total_files: int
    by_language: dict[str, int]
    by_symbol_type: dict[str, int]
    snapshot_path: str


@router.post("/embeddings/index", response_model=IndexResponse)
async def index_endpoint(
    req: IndexRequest,
    _user: dict = Depends(require_auth),
) -> IndexResponse:
    """Index a project codebase for semantic search.

    Walks the project directory, chunks code files, generates embeddings
    via Ollama, and stores them in memory for search. Supports incremental
    updates and forced re-indexing.
    """
    blocked, reason = _is_blocked_path(req.project_path)
    if blocked:
        raise HTTPException(status_code=400, detail=f"Blocked path: {reason}")

    chunk_count = await index_codebase(req.project_path, force_reindex=req.force_reindex)
    stats = await get_index_stats()
    return IndexResponse(
        chunks_indexed=chunk_count,
        total_chunks=stats["total_chunks"],
        project_path=req.project_path,
    )


@router.post("/embeddings/search", response_model=SearchResponse)
async def search_endpoint(
    req: SearchRequest,
    _user: dict = Depends(require_auth),
) -> SearchResponse:
    """Search the indexed codebase using semantic similarity.

    Returns the top-k most relevant code chunks for the query.
    The codebase must be indexed first via /api/embeddings/index.
    """
    results = await search_codebase(req.query, k=req.k)
    return SearchResponse(
        query=req.query,
        results=[
            SearchResultItem(
                file=r.file,
                start_line=r.start_line,
                end_line=r.end_line,
                score=round(r.score, 3),
                language=r.language,
                symbol_name=r.symbol_name,
                symbol_type=r.symbol_type,
                content=r.content[:500],
            )
            for r in results
        ],
        total_found=len(results),
    )


@router.get("/embeddings/stats", response_model=StatsResponse)
async def stats_endpoint(
    _user: dict = Depends(require_auth),
) -> StatsResponse:
    """Return statistics about the current codebase embedding index."""
    stats = await get_index_stats()
    return StatsResponse(**stats)
