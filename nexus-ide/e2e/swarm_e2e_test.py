"""End-to-end test for the SWARM API.

Exercises the new ``/api/swarm/*`` endpoints end-to-end with the real
FastAPI app. Verifies:
- Health
- Modes / agents / skills catalogue
- RAG index + search (offline, embeddings disabled)
- A full SWARM run via ``POST /api/swarm/run`` (no LLM call — uses a
  faked agent registry injected through the lifespan)
- A skill run
- Dashboard endpoint
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Make project importable
PROJECT_ROOT = Path(r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide")
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.middleware.auth import create_access_token  # noqa: E402
from backend.orchestrator.main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Fake agents — used so SWARM runs complete without Ollama
# ---------------------------------------------------------------------------


@dataclass
class _FakeAgent:
    name: str
    output: str = "ok"

    async def run(self, request: Any) -> Any:
        async def _gen():
            for tok in (f"[{self.name}]", " ", self.output):
                yield tok
        return _gen()


def _install_fake_registry() -> None:
    """Inject a fake agent registry into the app state for testing."""
    registry = {
        "ARCHITECT": _FakeAgent("ARCHITECT", output="architecture plan"),
        "RESEARCHER": _FakeAgent("RESEARCHER", output="research findings"),
        "ANALYZER": _FakeAgent("ANALYZER", output="investigation report"),
        "DEBUGGER": _FakeAgent("DEBUGGER", output="debug result"),
        "CODER": _FakeAgent("CODER", output="implementation plan"),
        "REVIEWER": _FakeAgent("REVIEWER", output="PASS"),
        "DASHBOARD": _FakeAgent("DASHBOARD", output=""),
        "MICRO": _FakeAgent("MICRO", output=""),
        "DOCUMENTER": _FakeAgent("DOCUMENTER", output=""),
    }
    app.state.registry = registry


def _bearer() -> dict[str, str]:
    token = create_access_token({"sub": "test-user", "email": "test@test.com"})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


@dataclass
class Step:
    name: str
    method: str
    url: str
    body: Any = None
    expect_status: int = 200
    expect_keys: tuple[str, ...] = ()


def run_step(client: TestClient, step: Step) -> tuple[bool, dict[str, Any]]:
    t0 = time.time()
    try:
        if step.method == "GET":
            r = client.get(step.url, headers=_bearer())
        elif step.method == "POST":
            r = client.post(step.url, json=step.body, headers=_bearer())
        else:
            return False, {"error": f"unknown method {step.method}"}
        ok = r.status_code == step.expect_status
        body: Any = {}
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text[:500]}
        # Check expected keys
        if ok and step.expect_keys and isinstance(body, dict):
            for k in step.expect_keys:
                if k not in body:
                    ok = False
                    body.setdefault("_missing", []).append(k)
        return ok, {
            "status": r.status_code,
            "duration_ms": int((time.time() - t0) * 1000),
            "body": body,
        }
    except Exception as exc:
        return False, {"error": repr(exc)}


def main() -> int:
    _install_fake_registry()
    client = TestClient(app)
    passes = 0
    failures = 0

    steps: list[Step] = [
        Step("health", "GET", "/api/swarm/health", expect_keys=("status",)),
        Step("list modes", "GET", "/api/swarm/modes", expect_keys=("modes",)),
        Step("list agents", "GET", "/api/swarm/agents", expect_keys=("agents",)),
        Step("list skills", "GET", "/api/swarm/skills", expect_keys=("skills", "count", "categories")),
        Step("get skill security-audit", "GET", "/api/swarm/skills/security-audit", expect_keys=("id", "name", "variables")),
        Step("list workflows", "GET", "/api/swarm/workflows", expect_keys=("workflows",)),
        Step("rag index", "POST", "/api/swarm/rag/index", body={"project_path": str(PROJECT_ROOT), "max_files": 30}),
        Step("rag search", "POST", "/api/swarm/rag/search", body={"query": "swarm orchestrator", "top_k": 3}),
        Step(
            "swarm run investigation",
            "POST",
            "/api/swarm/run",
            body={
                "objective": "investigate the auth module",
                "session_id": "t-e2e-1",
                "mode": "investigation",
            },
            expect_keys=("run_id", "mode", "final_answer", "scores", "state"),
        ),
        Step(
            "swarm run review",
            "POST",
            "/api/swarm/run",
            body={
                "objective": "review the helper function",
                "session_id": "t-e2e-2",
                "mode": "review",
            },
            expect_keys=("run_id", "state", "scores"),
        ),
        Step(
            "skill run security-audit",
            "POST",
            "/api/swarm/skills/security-audit/run",
            body={
                "variables": {
                    "file_path": "backend/swarm/core/orchestrator.py",
                    "project_path": str(PROJECT_ROOT),
                },
                "session_id": "t-skill-1",
            },
        ),
        Step("dashboard", "GET", "/api/swarm/dashboard", expect_keys=("memory", "retriever", "recent_runs", "total_runs")),
        Step("list runs", "GET", "/api/swarm/runs?limit=5", expect_keys=("runs",)),
    ]

    print("=" * 70)
    print("NEXUS SWARM - End-to-end test")
    print("=" * 70)
    for step in steps:
        ok, info = run_step(client, step)
        marker = "[PASS]" if ok else "[FAIL]"
        if ok:
            passes += 1
        else:
            failures += 1
        body_preview = str(info.get("body", info.get("error", "")))[:120]
        # ASCII-safe output (Windows console)
        body_preview = body_preview.encode("ascii", "replace").decode("ascii")
        print(f"{marker} {step.name:40s} {info.get('status', '?'):>4}  {info.get('duration_ms', 0):>4}ms  {body_preview}")

    print()
    print(f"Summary: {passes} passed, {failures} failed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
