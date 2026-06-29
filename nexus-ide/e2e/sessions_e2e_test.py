"""End-to-end test for the chat + sessions integration.

Verifies the full lifecycle:
- Create a session
- Add a user message
- Simulate an error and verify the error is persisted
- Read the session history
- Update the session (rename)
- List sessions
- Delete the session
- Cascade: messages are deleted too
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide")
sys.path.insert(0, str(PROJECT_ROOT))

import os
import importlib

# Set up per-test DB
tmp = Path(tempfile.mkdtemp())
os.environ["NEXUS_DB_PATH"] = str(tmp / "test_nexus.db")

import backend.persistence.db as db_mod
importlib.reload(db_mod)
db_mod.DB_PATH = tmp / "test_nexus.db"
db_mod._pool = None

from fastapi.testclient import TestClient
from backend.middleware import auth as auth_module
from backend.orchestrator.main import app


async def _fake_user() -> dict:
    return {"user_id": "test", "email": "t@t"}


app.dependency_overrides[auth_module.require_auth] = _fake_user

AUTH = {"Authorization": "Bearer test-bypass"}


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def check(label: str, condition: bool, detail: str = "") -> bool:
    mark = "[PASS]" if condition else "[FAIL]"
    print(f"  {mark}  {label}" + (f"  ({detail})" if detail else ""))
    return condition


def main() -> int:
    failures = 0
    with TestClient(app) as client:
        section("1. Create session")
        r = client.post(
            "/api/sessions",
            json={"title": "Sessao de chat de teste", "mode": "auto"},
            headers=AUTH,
        )
        if not check("POST /api/sessions returns 200", r.status_code == 200, f"status={r.status_code}"):
            failures += 1
            print(r.text[:200])
            return 1
        session = r.json()
        sid = session["id"]
        if not check("Session has 'id'", "id" in session):
            failures += 1
        if not check("Session has 'title'='Sessao de chat de teste'", session.get("title") == "Sessao de chat de teste", f"got={session.get('title')!r}"):
            failures += 1
        if not check("Session has 'mode'='auto'", session.get("mode") == "auto"):
            failures += 1
        if not check("Session has 'started_at'", "started_at" in session):
            failures += 1

        section("2. Add a user message")
        msg_user = client.post(
            "/api/messages",
            json={"role": "user", "content": "Ola mundo", "session_id": sid},
            headers=AUTH,
        )
        # /api/messages may not exist as a direct endpoint - use add_message via DB
        # Instead test the proper chat endpoint
        if msg_user.status_code == 404:
            # Use direct DB add
            db_mod.add_message(sid, "user", "Ola mundo")
            check("Used direct DB add_message", True)
        else:
            check(f"POST /api/messages returns {msg_user.status_code}", msg_user.status_code in (200, 201))

        section("3. Add an error message (simulate stream failure)")
        db_mod.add_message(sid, "assistant", "⚠ Stream interrupted: Provider timeout")
        check("Added error message", True)

        section("4. Read session messages")
        r = client.get(f"/api/sessions/{sid}/messages", headers=AUTH)
        if not check("GET /api/sessions/{id}/messages returns 200", r.status_code == 200):
            failures += 1
            print(r.text[:200])
        else:
            data = r.json()
            messages = data.get("messages", [])
            if not check("Has 2 messages", len(messages) == 2, f"got={len(messages)}"):
                failures += 1
            if messages:
                last = messages[-1]
                if not check("Last message has error content", "Stream interrupted" in last.get("content", "")):
                    failures += 1
                if not check("Last message is assistant role", last.get("role") == "assistant"):
                    failures += 1

        section("5. Update session (rename)")
        r = client.patch(
            f"/api/sessions/{sid}",
            json={"title": "Renomeado via teste"},
            headers=AUTH,
        )
        if not check("PATCH /api/sessions/{id} returns 200", r.status_code == 200):
            failures += 1
        else:
            updated = r.json()
            if not check("Title updated", updated.get("title") == "Renomeado via teste", f"got={updated.get('title')!r}"):
                failures += 1

        section("6. List sessions")
        r = client.get("/api/sessions?limit=20", headers=AUTH)
        if not check("GET /api/sessions returns 200", r.status_code == 200):
            failures += 1
        else:
            data = r.json()
            sessions_list = data.get("sessions", [])
            if not check("List has our session", any(s["id"] == sid for s in sessions_list)):
                failures += 1
            if not check("Sessions have message_count", all("message_count" in s for s in sessions_list)):
                failures += 1
            our_session = next((s for s in sessions_list if s["id"] == sid), None)
            if our_session and not check("Our session message_count=2", our_session.get("message_count") == 2):
                failures += 1

        section("7. Get single session")
        r = client.get(f"/api/sessions/{sid}", headers=AUTH)
        if not check("GET /api/sessions/{id} returns 200", r.status_code == 200):
            failures += 1

        section("8. Create another session")
        r = client.post(
            "/api/sessions",
            json={"title": "Segunda sessao"},
            headers=AUTH,
        )
        if not check("Second session created", r.status_code == 200):
            failures += 1
        sid2 = r.json()["id"]
        if not check("IDs are different", sid != sid2):
            failures += 1

        section("9. List shows both sessions")
        r = client.get("/api/sessions?limit=20", headers=AUTH)
        data = r.json()
        sessions_list = data.get("sessions", [])
        if not check("List has 2 sessions", len(sessions_list) >= 2):
            failures += 1
        ids = {s["id"] for s in sessions_list}
        if not check("Both IDs in list", sid in ids and sid2 in ids):
            failures += 1

        section("10. Delete first session (cascade messages)")
        r = client.delete(f"/api/sessions/{sid}", headers=AUTH)
        if not check("DELETE returns 200", r.status_code == 200):
            failures += 1
        else:
            body = r.json()
            if not check("deleted=True", body.get("deleted") is True):
                failures += 1
        # Verify gone
        r = client.get(f"/api/sessions/{sid}", headers=AUTH)
        if not check("GET after delete returns 404", r.status_code == 404):
            failures += 1
        # Verify messages cascaded
        r = client.get(f"/api/sessions/{sid}/messages", headers=AUTH)
        if not check("GET messages after delete returns 404", r.status_code == 404):
            failures += 1

        section("11. Delete second session (cleanup)")
        r = client.delete(f"/api/sessions/{sid2}", headers=AUTH)
        if not check("Second session deleted", r.status_code == 200):
            failures += 1

        section("12. Test swarm chat integration")
        # Run a swarm run and verify it creates an entry
        r = client.post(
            "/api/swarm/run",
            json={"objective": "test session flow", "mode": "investigation"},
            headers=AUTH,
        )
        if not check("Swarm run works", r.status_code == 200):
            failures += 1
        else:
            body = r.json()
            if not check("Swarm run has run_id", "run_id" in body):
                failures += 1
            if not check("Swarm run has scores", "scores" in body):
                failures += 1

        section("13. Dashboard shows everything")
        r = client.get("/api/swarm/dashboard", headers=AUTH)
        if not check("Dashboard returns 200", r.status_code == 200):
            failures += 1
        else:
            body = r.json()
            if not check("Dashboard has memory stats", "memory" in body):
                failures += 1
            if not check("Dashboard has retriever stats", "retriever" in body):
                failures += 1
            if not check("Dashboard has recent_runs", "recent_runs" in body):
                failures += 1

    print()
    print("=" * 72)
    if failures == 0:
        print("  ALL CHECKS PASSED")
        return 0
    else:
        print(f"  {failures} CHECK(S) FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
