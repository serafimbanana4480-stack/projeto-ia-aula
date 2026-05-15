"""Embeddings endpoints — index a codebase and search it semantically."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.tools.embeddings import index_codebase, search_codebase

logger = logging.getLogger(__name__)

router = APIRouter()


class IndexRequest(BaseModel):
    project_path: str = Field(min_length=1, max_length=2000, description="Absolute path to the project root to index")


class IndexResponse(BaseModel):
    chunks_indexed: int
    project_path: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000, description="Natural-language search query")
    k: int = Field(default=8, ge=1, le=50, description="Maximum number of results")


class SearchResultItem(BaseModel):
    file: str
    start_line: int
    end_line: int
    score: float
    content: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    total_found: int


@router.post("/embeddings/index", response_model=IndexResponse)
async def index_endpoint(req: IndexRequest) -> IndexResponse:
    """Index a project codebase for semantic search.

    Walks the project directory, chunks code files, generates embeddings
    via Ollama, and stores them in memory for search.
    """
    chunk_count = await index_codebase(req.project_path)
    return IndexResponse(chunks_indexed=chunk_count, project_path=req.project_path)


@router.post("/embeddings/search", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest) -> SearchResponse:
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
                content=r.content[:500],
            )
            for r in results
        ],
        total_found=len(results),
    )
