"""Semantic memory REST API.

Exposes endpoints to search, store, list, and delete semantic memories
stored by the persistent memory layer. These memories are shared with the
agent ``recall_context`` / ``store_memory`` tools and the chat pipeline.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.knowledge.memory import MemoryType, get_memory_store
from backend.middleware.auth import require_auth

router = APIRouter()


class StoreMemoryRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100_000)
    memory_type: str = Field(default="session")
    session_id: str = Field(default="")
    project_id: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    source: str = Field(default="")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    file_path: str = Field(default="")
    language: str = Field(default="")


class MemoryResponse(BaseModel):
    memory_id: str
    type: str
    content_preview: str
    summary: str
    source: str
    tags: list[str]
    file_path: str
    language: str
    importance: float
    created_at: float


class SearchMemoriesRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    session_id: str = Field(default="")
    project_id: str = Field(default="")
    memory_type: str = Field(default="")
    top_k: int = Field(default=8, ge=1, le=25)


class SearchMemoriesResponse(BaseModel):
    query: str
    memories: list[MemoryResponse]
    total_found: int


class StoreMemoryResponse(BaseModel):
    memory_id: str
    type: str
    stored: bool


@router.post("/memories/search", response_model=SearchMemoriesResponse)
async def search_memories(
    req: SearchMemoriesRequest,
    _user: dict = Depends(require_auth),
) -> SearchMemoriesResponse:
    """Semantic search over persistent memories."""
    store = get_memory_store()

    mem_type = None
    if req.memory_type:
        try:
            mem_type = MemoryType(req.memory_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid memory_type") from None

    results = await store.search(
        req.query,
        user_id=str(_user.get("user_id") or ""),
        session_id=req.session_id or None,
        project_id=req.project_id or None,
        memory_type=mem_type,
        top_k=req.top_k,
        min_similarity=0.2,
    )

    return SearchMemoriesResponse(
        query=req.query,
        memories=[
            MemoryResponse(
                memory_id=mem.memory_id,
                type=mem.memory_type.value,
                content_preview=mem.content[:500],
                summary=mem.summary,
                source=mem.source,
                tags=mem.tags,
                file_path=mem.file_path,
                language=mem.language,
                importance=mem.importance,
                created_at=mem.created_at,
            )
            for mem, _ in results
        ],
        total_found=len(results),
    )


@router.post("/memories", response_model=StoreMemoryResponse)
async def create_memory(
    req: StoreMemoryRequest,
    _user: dict = Depends(require_auth),
) -> StoreMemoryResponse:
    """Store a new semantic memory."""
    store = get_memory_store()

    try:
        mem_type = MemoryType(req.memory_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid memory_type") from None

    memory = await store.store(
        content=req.content,
        user_id=str(_user.get("user_id") or ""),
        memory_type=mem_type,
        session_id=req.session_id,
        project_id=req.project_id,
        tags=req.tags,
        source=req.source,
        importance=req.importance,
        file_path=req.file_path,
        language=req.language,
    )

    return StoreMemoryResponse(
        memory_id=memory.memory_id,
        type=memory.memory_type.value,
        stored=True,
    )


@router.get("/memories")
async def list_memories(
    session_id: str = "",
    project_id: str = "",
    memory_type: str = "",
    limit: int = 100,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """List recent memories with optional filters."""
    store = get_memory_store()

    mem_type = None
    if memory_type:
        try:
            mem_type = MemoryType(memory_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid memory_type") from None

    all_memories = await store.list_all(
        limit=max(limit, 1000), user_id=str(_user.get("user_id") or "")
    )
    filtered = [
        m
        for m in all_memories
        if (not session_id or m.session_id == session_id)
        and (not project_id or m.project_id == project_id)
        and (not mem_type or m.memory_type == mem_type)
    ][:limit]

    return {
        "memories": [
            {
                "memory_id": m.memory_id,
                "type": m.memory_type.value,
                "content_preview": m.content[:500],
                "summary": m.summary,
                "source": m.source,
                "tags": m.tags,
                "file_path": m.file_path,
                "language": m.language,
                "importance": m.importance,
                "created_at": m.created_at,
                "last_accessed_at": m.last_accessed_at,
                "access_count": m.access_count,
            }
            for m in filtered
        ],
        "total": len(filtered),
    }


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Delete a memory by ID."""
    store = get_memory_store()
    deleted = await store.delete(memory_id, user_id=str(_user.get("user_id") or ""))
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": True, "memory_id": memory_id}


@router.get("/memories/stats")
async def memory_stats(
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return statistics about the semantic memory store."""
    store = get_memory_store()
    return store.stats(user_id=str(_user.get("user_id") or ""))
