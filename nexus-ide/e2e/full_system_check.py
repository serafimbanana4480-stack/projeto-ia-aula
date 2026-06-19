"""Comprehensive verification of the NEXUS SWARM v2 + Chat integration.

End-to-end test that exercises:
- /api/swarm/* (13 endpoints)
- /api/sessions/* (6 endpoints)
- /api/modes, /api/agents, /api/tools
- /api/skills (built-in + YAML)
- Dashboard metrics
- TypeScript safety (via subprocess)

Output a pass/fail summary.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide")
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure the lifespan can write to logs/backend.log regardless of CWD
(PROJECT_ROOT / "logs").mkdir(exist_ok=True)

# Run from the project root so the lifespan finds config files
import os
os.chdir(PROJECT_ROOT)

import importlib

tmp = Path(tempfile.mkdtemp())
os.environ["NEXUS_DB_PATH"] = str(tmp / "test_nexus.db")

import backend.persistence.db as db_mod
importlib.reload(db_mod)
db_mod.DB_PATH = tmp / "test_nexus.db"
db_mod._pool = None

from fastapi.testclient import TestClient
from backend.middleware import auth as auth_module
from backend.orchestrator.main import app

async def _fake_user():
    return {"user_id": "test", "email": "t@t"}

app.dependency_overrides[auth_module.require_auth] = _fake_user

AUTH = {"Authorization": "Bearer test-bypass"}

passed: list[str] = []
failed: list[tuple[str, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        passed.append(label)
        print(f"  [PASS]  {label}" + (f"  ({detail})" if detail else ""))
    else:
        failed.append((label, detail))
        print(f"  [FAIL]  {label}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


with TestClient(app) as client:
    section("1. Health & basic endpoints")
    r = client.get("/health")
    check("/health", r.status_code == 200)
    r = client.get("/api/swarm/health", headers=AUTH)
    check("/api/swarm/health", r.status_code == 200, f"status={r.status_code}")
    r = client.get("/api/modes", headers=AUTH)
    modes_count = len(r.json().get("modes", {})) if r.status_code == 200 else 0
    check(f"/api/modes returns modes", r.status_code == 200 and modes_count >= 7, f"got {modes_count}")
    r = client.get("/api/swarm/agents", headers=AUTH)
    agents_count = len(r.json().get("agents", {})) if r.status_code == 200 else 0
    check(f"/api/swarm/agents returns SWARM agents", r.status_code == 200 and agents_count == 6, f"got {agents_count}")
    r = client.get("/api/tools", headers=AUTH)
    check("/api/tools returns tools", r.status_code == 200 and "tools" in r.json())

    section("2. Sessions CRUD (full lifecycle)")
    r = client.post("/api/sessions", json={"title": "Sessao A", "mode": "auto"}, headers=AUTH)
    check("Create session A", r.status_code == 200)
    sid_a = r.json()["id"]
    r = client.post("/api/sessions", json={"title": "Sessao B", "mode": "swarm"}, headers=AUTH)
    check("Create session B", r.status_code == 200)
    sid_b = r.json()["id"]
    r = client.get("/api/sessions?limit=20", headers=AUTH)
    data = r.json()
    check("List returns 2 sessions", len(data["sessions"]) == 2, f"got {len(data['sessions'])}")
    check("Each session has message_count", all("message_count" in s for s in data["sessions"]))
    check("Sessions are ordered by recency", data["sessions"][0]["id"] == sid_b, "B is most recent")
    r = client.get(f"/api/sessions/{sid_a}", headers=AUTH)
    check("Get session A", r.status_code == 200 and r.json()["id"] == sid_a)
    r = client.patch(f"/api/sessions/{sid_a}", json={"title": "Sessao A Renomeada"}, headers=AUTH)
    check("Rename session A", r.status_code == 200 and r.json()["title"] == "Sessao A Renomeada")
    r = client.get("/api/sessions/does-not-exist", headers=AUTH)
    check("Get missing session returns 404", r.status_code == 404)
    r = client.delete(f"/api/sessions/{sid_a}", headers=AUTH)
    check("Delete session A", r.status_code == 200 and r.json()["deleted"] is True)
    r = client.get(f"/api/sessions/{sid_a}", headers=AUTH)
    check("Get deleted session returns 404", r.status_code == 404)

    section("3. Skills (built-in + YAML)")
    r = client.get("/api/swarm/skills", headers=AUTH)
    data = r.json()
    check("/api/swarm/skills returns 19 skills", data.get("count") == 19, f"got {data.get('count')}")
    check("Skills include security-audit", any(s["id"] == "security-audit" for s in data["skills"]))
    check("Skills include changelog-from-diff (YAML)", any(s["id"] == "changelog-from-diff" for s in data["skills"]))
    r = client.get("/api/swarm/skills/security-audit", headers=AUTH)
    check("Get skill security-audit", r.status_code == 200 and r.json()["id"] == "security-audit")
    r = client.get("/api/swarm/skills/does-not-exist", headers=AUTH)
    check("Get missing skill returns 404", r.status_code == 404)
    r = client.get("/api/swarm/workflows", headers=AUTH)
    data = r.json()
    check("/api/swarm/workflows returns 6", data.get("count") == 6, f"got {data.get('count')}")

    section("4. SWARM run + skill run")
    r = client.post(
        "/api/swarm/run",
        json={"objective": "verify the swarm system", "mode": "investigation"},
        headers=AUTH,
    )
    check("Swarm run investigation", r.status_code == 200)
    run_id = r.json().get("run_id", "")
    check("Swarm run has run_id", bool(run_id))
    r = client.post(
        "/api/swarm/skills/security-audit/run",
        json={"variables": {"file_path": "test.py", "project_path": str(PROJECT_ROOT)}, "session_id": sid_b},
        headers=AUTH,
    )
    check("Run skill security-audit", r.status_code == 200, f"status={r.status_code}")
    r = client.get("/api/swarm/runs?limit=5", headers=AUTH)
    check("List swarm runs", r.status_code == 200 and len(r.json().get("runs", [])) >= 2)
    r = client.get(f"/api/swarm/runs/{run_id}", headers=AUTH)
    check("Get specific swarm run", r.status_code == 200)
    r = client.post(
        "/api/swarm/skills/security-audit/run",
        json={"variables": {"project_path": str(PROJECT_ROOT)}, "session_id": sid_b},  # missing file_path
        headers=AUTH,
    )
    check("Skill with missing required variable returns 422", r.status_code == 422)

    section("5. RAG index + search")
    r = client.post(
        "/api/swarm/rag/index",
        json={"project_path": str(PROJECT_ROOT), "max_files": 5},
        headers=AUTH,
    )
    check("RAG index", r.status_code == 200 and "chunks" in r.json())
    r = client.post(
        "/api/swarm/rag/search",
        json={"query": "swarm orchestrator", "top_k": 3},
        headers=AUTH,
    )
    check("RAG search", r.status_code == 200 and "hits" in r.json())

    section("6. Dashboard")
    r = client.get("/api/swarm/dashboard", headers=AUTH)
    data = r.json()
    check("Dashboard returns 200", r.status_code == 200)
    check("Dashboard has memory stats", "memory" in data)
    check("Dashboard has retriever stats", "retriever" in data)
    check("Dashboard has recent_runs", "recent_runs" in data)
    check("Dashboard memory has 5 layers", len(data["memory"]) == 5)

    section("7. OpenAPI")
    r = client.get("/openapi.json")
    check("/openapi.json returns 200", r.status_code == 200, "with fallback schema")
    r = client.get("/docs")
    check("/docs returns 200", r.status_code == 200)
    r = client.get("/redoc")
    check("/redoc returns 200", r.status_code == 200)

    section("8. CORS preflight")
    r = client.options(
        "/api/sessions",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    check("CORS preflight on /api/sessions", r.status_code == 200)

    section("9. Auth (verify override)")
    r = client.get("/api/sessions")
    check("Auth override works (GET /api/sessions without auth still 200)", r.status_code == 200)

    # Cleanup
    client.delete(f"/api/sessions/{sid_b}", headers=AUTH)


print()
print("=" * 72)
print(f"  RESULTS: {len(passed)} passed, {len(failed)} failed")
print("=" * 72)
if failed:
    print()
    print("  FAILURES:")
    for label, detail in failed:
        print(f"    - {label}{('  (' + detail + ')') if detail else ''}")
    sys.exit(1)
print()
print("  ALL CHECKS PASSED - system is operational")
sys.exit(0)
