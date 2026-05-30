"""Peer Review System — automatic code/design review pipeline.

Rules:
- ALL code written by CODER must be reviewed by ANALYZER + BUG_HUNTER_STATIC
- ALL designs by ARCHITECT_DESIGN must be reviewed by ARCHITECT_COMPLEXITY
- If review is "changes_requested", spawn REFACTOR_CLEAN or CODER to fix
- If 2 reviewers disagree, escalate to META_ANALYZER
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.agent_bus import BusMessage, get_agent_bus
from backend.persistence.db import get_db

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# DB initialisation
# ──────────────────────────────────────────────────────────────────────────────


def _init_peer_review_db() -> None:
    """Create peer-review tables if they do not exist."""
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS peer_review_requests (
                review_id      TEXT PRIMARY KEY,
                artifact_id    TEXT NOT NULL,
                artifact_type  TEXT NOT NULL
                    CHECK (artifact_type IN ('code', 'design', 'test', 'config')),
                author_agent   TEXT NOT NULL,
                content_hash   TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_review', 'approved',
                                      'changes_requested', 'rejected')),
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS peer_review_results (
                result_id       TEXT PRIMARY KEY,
                review_id       TEXT NOT NULL,
                reviewer_agent  TEXT NOT NULL,
                status          TEXT NOT NULL
                    CHECK (status IN ('approved', 'changes_requested', 'rejected')),
                comments        TEXT NOT NULL DEFAULT '[]',
                criteria_scores TEXT NOT NULL DEFAULT '{}',
                created_at      TEXT NOT NULL,
                FOREIGN KEY (review_id)
                    REFERENCES peer_review_requests(review_id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pr_artifact "
            "ON peer_review_requests(artifact_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pr_status "
            "ON peer_review_requests(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pr_results_review "
            "ON peer_review_results(review_id)"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────────────────────


class ReviewComment(BaseModel):
    """A single comment inside a review result."""

    model_config = ConfigDict(extra="forbid")

    line: int | None = None
    severity: str = "info"  # info, warning, error
    message: str


class ReviewRequest(BaseModel):
    """A queued review request."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(default="code")
    author_agent: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    status: str = Field(default="pending")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewResult(BaseModel):
    """The outcome of a single reviewer conducting a review."""

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    review_id: str = Field(min_length=1)
    reviewer_agent: str = Field(min_length=1)
    status: str = Field(default="approved")
    comments: list[ReviewComment] = Field(default_factory=list)
    criteria_scores: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# author_agent → required reviewer agents
REVIEW_RULES: dict[str, list[str]] = {
    "CODER": ["ANALYZER", "BUG_HUNTER_STATIC"],
    "ARCHITECT_DESIGN": ["ARCHITECT_COMPLEXITY"],
}


# ──────────────────────────────────────────────────────────────────────────────
# PeerReviewSystem
# ──────────────────────────────────────────────────────────────────────────────


class PeerReviewSystem:
    """Singleton manager for the peer-review pipeline.

    Usage::

        prs = get_peer_review_system()
        req = prs.submit_for_review("api.py", "code", "CODER", "def foo(): ...")
        result = await prs.conduct_review(req.review_id, "ANALYZER", "approved")
        status = prs.get_review_status("api.py")
    """

    _instance: PeerReviewSystem | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> PeerReviewSystem:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    _init_peer_review_db()
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit_for_review(
        self,
        artifact_id: str,
        artifact_type: str,
        author_agent: str,
        content: str,
    ) -> ReviewRequest:
        """Queue a new artifact for peer review."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        review = ReviewRequest(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            author_agent=author_agent,
            content_hash=content_hash,
        )
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO peer_review_requests
                (review_id, artifact_id, artifact_type, author_agent,
                 content_hash, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.review_id,
                    review.artifact_id,
                    review.artifact_type,
                    review.author_agent,
                    review.content_hash,
                    review.status,
                    review.created_at.isoformat(),
                    review.updated_at.isoformat(),
                ),
            )
        logger.info(
            "Review %s submitted for %s by %s",
            review.review_id,
            artifact_id,
            author_agent,
        )
        return review

    def get_review_status(self, artifact_id: str) -> dict[str, Any]:
        """Return all reviews and their results for an artifact."""
        with get_db() as conn:
            req_rows = conn.execute(
                """
                SELECT * FROM peer_review_requests
                WHERE artifact_id = ?
                ORDER BY created_at DESC
                """,
                (artifact_id,),
            ).fetchall()

        reviews: list[dict[str, Any]] = []
        for req_row in req_rows:
            review = self._row_to_request(req_row)
            with get_db() as conn:
                res_rows = conn.execute(
                    """
                    SELECT * FROM peer_review_results
                    WHERE review_id = ?
                    """,
                    (review.review_id,),
                ).fetchall()
            results = [self._row_to_result(r) for r in res_rows]
            reviews.append(
                {
                    "review": review.model_dump(mode="json"),
                    "results": [r.model_dump(mode="json") for r in results],
                }
            )
        return {"artifact_id": artifact_id, "reviews": reviews}

    async def conduct_review(
        self,
        review_id: str,
        reviewer_agent: str,
        status: str,
        comments: list[ReviewComment] | None = None,
        criteria_scores: dict[str, float] | None = None,
    ) -> ReviewResult:
        """Record a reviewer's verdict for a queued review."""
        if status not in ("approved", "changes_requested", "rejected"):
            raise ValueError(f"Invalid review status: {status}")

        result = ReviewResult(
            review_id=review_id,
            reviewer_agent=reviewer_agent,
            status=status,
            comments=comments or [],
            criteria_scores=criteria_scores or {},
        )

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO peer_review_results
                (result_id, review_id, reviewer_agent, status,
                 comments, criteria_scores, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.result_id,
                    result.review_id,
                    result.reviewer_agent,
                    result.status,
                    json.dumps([c.model_dump() for c in result.comments]),
                    json.dumps(result.criteria_scores),
                    result.created_at.isoformat(),
                ),
            )
            self._update_request_status(conn, review_id)

        await self._publish_review_completed(review_id)
        logger.info(
            "Review %s conducted by %s: %s",
            review_id,
            reviewer_agent,
            status,
        )
        return result

    def get_review_request(self, review_id: str) -> ReviewRequest | None:
        """Fetch a single review request by id."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM peer_review_requests WHERE review_id = ?",
                (review_id,),
            ).fetchone()
            if row:
                return self._row_to_request(row)
            return None

    def get_required_reviewers(self, author_agent: str) -> list[str]:
        """Return the list of mandatory reviewers for an author agent."""
        return list(REVIEW_RULES.get(author_agent, []))

    def check_disagreement(self, review_id: str) -> bool:
        """Return ``True`` if reviewers have delivered conflicting verdicts."""
        with get_db() as conn:
            res_rows = conn.execute(
                "SELECT status FROM peer_review_results WHERE review_id = ?",
                (review_id,),
            ).fetchall()
        if len(res_rows) < 2:
            return False
        statuses = {r["status"] for r in res_rows}
        return len(statuses) > 1

    def list_pending_reviews(
        self, reviewer_agent: str | None = None
    ) -> list[ReviewRequest]:
        """Return review requests that are still pending or in review."""
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM peer_review_requests
                WHERE status IN ('pending', 'in_review')
                ORDER BY created_at DESC
                """,
            ).fetchall()
        return [self._row_to_request(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _publish_review_completed(self, review_id: str) -> None:
        try:
            bus = get_agent_bus()
            await bus.publish(
                "review.completed",
                BusMessage(
                    message_id=uuid.uuid4().hex[:16],
                    source_agent="PEER_REVIEW_SYSTEM",
                    payload={"review_id": review_id, "event": "review.completed"},
                ),
            )
        except Exception as exc:
            logger.warning("Failed to publish review.completed event: %s", exc)

    def _update_request_status(
        self, conn: sqlite3.Connection, review_id: str
    ) -> None:
        req_row = conn.execute(
            "SELECT * FROM peer_review_requests WHERE review_id = ?",
            (review_id,),
        ).fetchone()
        if req_row is None:
            return

        author_agent = req_row["author_agent"]
        required_reviewers = self.get_required_reviewers(author_agent)

        res_rows = conn.execute(
            "SELECT * FROM peer_review_results WHERE review_id = ?",
            (review_id,),
        ).fetchall()

        if not res_rows:
            return

        statuses = [r["status"] for r in res_rows]
        reviewers = [r["reviewer_agent"] for r in res_rows]

        if "rejected" in statuses:
            new_status = "rejected"
        elif "changes_requested" in statuses:
            new_status = "changes_requested"
        else:
            new_status = "approved"

        missing = [r for r in required_reviewers if r not in reviewers]
        if missing and new_status == "approved":
            new_status = "in_review"

        conn.execute(
            """
            UPDATE peer_review_requests
            SET status = ?, updated_at = ?
            WHERE review_id = ?
            """,
            (new_status, datetime.now(UTC).isoformat(), review_id),
        )

    def _row_to_request(self, row: sqlite3.Row) -> ReviewRequest:
        return ReviewRequest(
            review_id=row["review_id"],
            artifact_id=row["artifact_id"],
            artifact_type=row["artifact_type"],
            author_agent=row["author_agent"],
            content_hash=row["content_hash"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_result(self, row: sqlite3.Row) -> ReviewResult:
        return ReviewResult(
            result_id=row["result_id"],
            review_id=row["review_id"],
            reviewer_agent=row["reviewer_agent"],
            status=row["status"],
            comments=[
                ReviewComment(**c) for c in json.loads(row["comments"])
            ],
            criteria_scores=json.loads(row["criteria_scores"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Convenience accessor
# ──────────────────────────────────────────────────────────────────────────────


def get_peer_review_system() -> PeerReviewSystem:
    """Return the singleton :class:`PeerReviewSystem` instance."""
    return PeerReviewSystem()
