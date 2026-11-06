from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.shared_memory import SharedMemory
from backend.middleware.auth import require_auth
from backend.orchestrator.routes.collaboration import router
from backend.persistence.db import get_db


def test_whiteboard_routes_only_return_entries_owned_by_the_caller(monkeypatch) -> None:
    """List, search and thread lookups must not expose another user's memory."""
    monkeypatch.setattr(SharedMemory, "_instance", None)
    monkeypatch.setattr(SharedMemory, "_initialized", False)
    identity = {"user_id": "whiteboard-owner"}
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[require_auth] = lambda: identity

    with TestClient(app) as client:
        owner_write = client.post(
            "/api/whiteboard",
            json={
                "agent_name": "CODER",
                "topic": "private.project.note",
                "content": "WHITEBOARD-OWNER-SECRET",
            },
        )
        assert owner_write.status_code == 200, owner_write.text
        owner_entry_id = owner_write.json()["entry_id"]

        identity["user_id"] = "whiteboard-other"
        other_write = client.post(
            "/api/whiteboard",
            json={
                "agent_name": "ANALYZER",
                "topic": "other.note",
                "content": "WHITEBOARD-OTHER-FACT",
            },
        )
        assert other_write.status_code == 200, other_write.text

        # Rows created before ownership was added stay ownerless and must not
        # silently become visible to any authenticated account.
        with get_db() as conn:
            conn.execute(
                "INSERT INTO whiteboard_entries "
                "(entry_id, topic, author_agent, content, timestamp, importance, "
                "tags, related_entries, archived) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-whiteboard-entry",
                    "legacy.note",
                    "OLD-AGENT",
                    "WHITEBOARD-LEGACY-GLOBAL-DATA",
                    "2026-10-30T00:00:00+00:00",
                    0.5,
                    "[]",
                    "[]",
                    0,
                ),
            )

        listing = client.get("/api/whiteboard")
        assert listing.status_code == 200, listing.text
        body = listing.text
        assert "WHITEBOARD-OTHER-FACT" in body
        assert "WHITEBOARD-OWNER-SECRET" not in body
        assert "WHITEBOARD-LEGACY-GLOBAL-DATA" not in body

        search = client.get(
            "/api/whiteboard/search", params={"q": "WHITEBOARD-OWNER-SECRET"}
        )
        assert search.status_code == 200, search.text
        assert search.json()["count"] == 0

        hidden_thread = client.get(f"/api/whiteboard/thread/{owner_entry_id}")
        assert hidden_thread.status_code == 404
        assert "WHITEBOARD-OWNER-SECRET" not in hidden_thread.text

        identity["user_id"] = "whiteboard-owner"
        owner_thread = client.get(f"/api/whiteboard/thread/{owner_entry_id}")
        assert owner_thread.status_code == 200, owner_thread.text
        assert "WHITEBOARD-OWNER-SECRET" in owner_thread.text


def test_whiteboard_rejects_an_authenticated_identity_without_an_owner_id(monkeypatch) -> None:
    monkeypatch.setattr(SharedMemory, "_instance", None)
    monkeypatch.setattr(SharedMemory, "_initialized", False)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[require_auth] = lambda: {"user_id": " "}

    with TestClient(app) as client:
        response = client.get("/api/whiteboard")

    assert response.status_code == 401
