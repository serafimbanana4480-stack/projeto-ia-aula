"""Collaboration routes — Shared Memory, Peer Review, Debate, Auto-Correction.

Endpoints:
    GET  /whiteboard                 — view shared memory entries
    POST /whiteboard                 — write a whiteboard entry
    GET  /reviews/{artifact_id}      — view reviews for an artifact
    POST /reviews/submit             — submit an artifact for review
    GET  /debates/{debate_id}        — view a debate result
    GET  /auto-correction/status     — view auto-correction status
"""



import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.core.auto_correction import get_auto_correction_loop
from backend.core.debate import AgentOpinion, get_debate_result, run_debate
from backend.core.peer_review import (
    ReviewComment,
    get_peer_review_system,
)
from backend.core.shared_memory import get_shared_memory
from backend.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic request/response models ──────────────────────────────────────────


class WhiteboardWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(min_length=1, max_length=128)
    topic: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    related_entries: list[str] = Field(default_factory=list)


class WhiteboardWriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    topic: str
    author_agent: str
    timestamp: str


class ReviewSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(default="code")
    author_agent: str = Field(min_length=1)
    content: str = Field(min_length=1)


class ReviewSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    artifact_id: str
    status: str


class ReviewConductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1)
    reviewer_agent: str = Field(min_length=1)
    status: str = Field(pattern="^(approved|changes_requested|rejected)$")
    comments: list[ReviewComment] = Field(default_factory=list)
    criteria_scores: dict[str, float] = Field(default_factory=dict)


class DebateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1)
    opinions: list[AgentOpinion]
    max_rounds: int = Field(default=3, ge=1, le=10)


# ── Whiteboard routes ─────────────────────────────────────────────────────────


@router.get("/whiteboard")
@limiter.limit("120/minute")
async def list_whiteboard(
    request: Request,
    topic: str | None = Query(None),
    agent: str | None = Query(None),
    tags: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    since: str | None = Query(None),
) -> dict[str, Any]:
    """Read shared-memory whiteboard entries with optional filters."""
    shm = get_shared_memory()
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid since: {exc}") from exc

    entries = await shm.read_entries(
        topic=topic,
        agent=agent,
        tags=tags,
        limit=limit,
        since=since_dt,
    )
    return {
        "entries": [e.model_dump(mode="json") for e in entries],
        "count": len(entries),
    }


@router.post("/whiteboard")
@limiter.limit("120/minute")
async def write_whiteboard(
    req: WhiteboardWriteRequest, request: Request
) -> WhiteboardWriteResponse:
    """Write a new entry to the shared whiteboard."""
    shm = get_shared_memory()
    entry = await shm.write_entry(
        agent_name=req.agent_name,
        topic=req.topic,
        content=req.content,
        importance=req.importance,
        tags=req.tags,
        related_entries=req.related_entries,
    )
    return WhiteboardWriteResponse(
        entry_id=entry.entry_id,
        topic=entry.topic,
        author_agent=entry.author_agent,
        timestamp=entry.timestamp.isoformat(),
    )


@router.get("/whiteboard/search")
@limiter.limit("120/minute")
async def search_whiteboard(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Search whiteboard entries by text."""
    shm = get_shared_memory()
    entries = await shm.search_entries(query=q, limit=limit)
    return {
        "query": q,
        "entries": [e.model_dump(mode="json") for e in entries],
        "count": len(entries),
    }


@router.get("/whiteboard/thread/{entry_id}")
@limiter.limit("120/minute")
async def get_whiteboard_thread(
    request: Request, entry_id: str
) -> dict[str, Any]:
    """Return an entry and all related entries recursively."""
    shm = get_shared_memory()
    thread = await shm.get_thread(entry_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {
        "entry_id": entry_id,
        "entries": [e.model_dump(mode="json") for e in thread],
        "count": len(thread),
    }


# ── Peer Review routes ────────────────────────────────────────────────────────


@router.get("/reviews/{artifact_id}")
@limiter.limit("120/minute")
async def get_reviews(
    request: Request, artifact_id: str
) -> dict[str, Any]:
    """Return all reviews and their results for an artifact."""
    prs = get_peer_review_system()
    status = await prs.get_review_status(artifact_id)
    return status


@router.post("/reviews/submit")
@limiter.limit("60/minute")
async def submit_review(
    req: ReviewSubmitRequest, request: Request
) -> ReviewSubmitResponse:
    """Submit an artifact for peer review."""
    prs = get_peer_review_system()
    review = await prs.submit_for_review(
        artifact_id=req.artifact_id,
        artifact_type=req.artifact_type,
        author_agent=req.author_agent,
        content=req.content,
    )
    return ReviewSubmitResponse(
        review_id=review.review_id,
        artifact_id=review.artifact_id,
        status=review.status,
    )


@router.post("/reviews/conduct")
@limiter.limit("60/minute")
async def conduct_review(
    req: ReviewConductRequest, request: Request
) -> dict[str, Any]:
    """Conduct a review and record the verdict."""
    prs = get_peer_review_system()
    result = await prs.conduct_review(
        review_id=req.review_id,
        reviewer_agent=req.reviewer_agent,
        status=req.status,
        comments=req.comments,
        criteria_scores=req.criteria_scores,
    )
    return {"result": result.model_dump(mode="json")}


# ── Debate routes ─────────────────────────────────────────────────────────────


@router.post("/debates")
@limiter.limit("30/minute")
async def create_debate(
    req: DebateCreateRequest, request: Request
) -> dict[str, Any]:
    """Run a new debate session and return the result."""
    result = await run_debate(
        topic=req.topic,
        opinions=req.opinions,
        max_rounds=req.max_rounds,
    )
    return {"debate": result.model_dump(mode="json")}


@router.get("/debates/{debate_id}")
@limiter.limit("120/minute")
async def get_debate(
    request: Request, debate_id: str
) -> dict[str, Any]:
    """Retrieve the result of a previously run debate."""
    result = get_debate_result(debate_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Debate not found")
    return {"debate": result.model_dump(mode="json")}


# ── Auto-Correction routes ────────────────────────────────────────────────────


@router.get("/auto-correction/status")
@limiter.limit("120/minute")
async def auto_correction_status(request: Request) -> dict[str, Any]:
    """Return the current auto-correction loop status."""
    loop = get_auto_correction_loop()
    return loop.get_status()
