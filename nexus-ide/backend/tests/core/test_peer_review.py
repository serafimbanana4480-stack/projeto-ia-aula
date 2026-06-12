"""Tests for the Peer Review system."""

from __future__ import annotations

import pytest

from backend.core.peer_review import (
    PeerReviewSystem,
    ReviewComment,
    get_peer_review_system,
)


@pytest.fixture(autouse=True)
def reset_peer_review_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the PeerReviewSystem singleton before each test."""
    monkeypatch.setattr(PeerReviewSystem, "_instance", None)
    monkeypatch.setattr(PeerReviewSystem, "_initialized", False)


class TestPeerReview:
    def setup_method(self):
        from backend.persistence.db import close_pool
        close_pool()

    @pytest.mark.asyncio
    async def test_submit_and_get_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        prs = get_peer_review_system()
        review = await prs.submit_for_review(
            artifact_id="api.py",
            artifact_type="code",
            author_agent="CODER",
            content="def hello(): pass",
        )
        assert review.review_id
        assert review.status == "pending"

        status = await prs.get_review_status("api.py")
        assert status["artifact_id"] == "api.py"
        assert len(status["reviews"]) == 1

    @pytest.mark.asyncio
    async def test_conduct_review_approved(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        prs = get_peer_review_system()
        review = await prs.submit_for_review(
            artifact_id="api.py",
            artifact_type="code",
            author_agent="CODER",
            content="def hello(): pass",
        )

        result = await prs.conduct_review(
            review_id=review.review_id,
            reviewer_agent="ANALYZER",
            status="approved",
            comments=[ReviewComment(message="LGTM")],
            criteria_scores={"readability": 9.0},
        )
        assert result.reviewer_agent == "ANALYZER"
        assert result.status == "approved"

        updated = await prs.get_review_request(review.review_id)
        # Missing BUG_HUNTER_STATIC, so should stay in_review
        assert updated.status == "in_review"

    @pytest.mark.asyncio
    async def test_required_reviewers_complete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        prs = get_peer_review_system()
        review = await prs.submit_for_review(
            artifact_id="api.py",
            artifact_type="code",
            author_agent="CODER",
            content="def hello(): pass",
        )

        await prs.conduct_review(review.review_id, "ANALYZER", "approved")
        await prs.conduct_review(review.review_id, "BUG_HUNTER_STATIC", "approved")

        updated = await prs.get_review_request(review.review_id)
        assert updated.status == "approved"

    @pytest.mark.asyncio
    async def test_disagreement_escalation(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        prs = get_peer_review_system()
        review = await prs.submit_for_review(
            artifact_id="api.py",
            artifact_type="code",
            author_agent="CODER",
            content="def hello(): pass",
        )

        await prs.conduct_review(review.review_id, "ANALYZER", "approved")
        await prs.conduct_review(review.review_id, "BUG_HUNTER_STATIC", "changes_requested")

        assert await prs.check_disagreement(review.review_id) is True
        updated = await prs.get_review_request(review.review_id)
        assert updated.status == "changes_requested"

    def test_review_rules(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        prs = get_peer_review_system()
        assert "ANALYZER" in prs.get_required_reviewers("CODER")
        assert "BUG_HUNTER_STATIC" in prs.get_required_reviewers("CODER")
        assert "ARCHITECT_COMPLEXITY" in prs.get_required_reviewers("ARCHITECT_DESIGN")
        assert prs.get_required_reviewers("UNKNOWN") == []

    @pytest.mark.asyncio
    async def test_list_pending_reviews(self, tmp_path, monkeypatch):
        # Clean tables to avoid test pollution
        import sqlite3
        from backend.persistence.db import DB_PATH
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("DELETE FROM peer_review_requests")
        conn.execute("DELETE FROM peer_review_results")
        conn.commit()
        conn.close()
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db
        init_db()
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        prs = get_peer_review_system()
        await prs.submit_for_review("a.py", "code", "CODER", "x")
        await prs.submit_for_review("b.py", "design", "ARCHITECT_DESIGN", "y")

        pending = await prs.list_pending_reviews()
        assert len(pending) == 2
