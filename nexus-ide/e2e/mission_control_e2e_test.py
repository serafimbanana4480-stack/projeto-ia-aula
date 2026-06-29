"""End-to-end test for Mission Control API endpoints.

This script exercises all Mission Control endpoints and produces a detailed report.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

# Ensure project root is on path
sys.path.insert(0, r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide")

from backend.orchestrator.main import app


@dataclass
class EndpointResult:
    endpoint: str
    method: str
    status_code: int
    response_time_ms: float
    works: bool
    issues: list[str] = field(default_factory=list)
    response_preview: str = ""
    expected_status: int = 200


def truncate(value: Any, max_len: int = 500) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False) if not isinstance(value, str) else value
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def run_tests() -> list[EndpointResult]:
    results: list[EndpointResult] = []
    mission_id: str | None = None

    with TestClient(app) as client:
        # ------------------------------------------------------------------
        # 1. POST /api/missions — create a mission
        # ------------------------------------------------------------------
        print("Testing POST /api/missions ...")
        start = time.perf_counter()
        try:
            resp = client.post(
                "/api/missions",
                json={
                    "objective": "analyze project structure",
                    "token_budget": 50000,
                    "time_budget_seconds": 3600,
                    "project_path": ".",
                },
            )
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/missions", method="POST", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues: list[str] = []
            works = resp.status_code == 200
            if not works:
                issues.append(f"Expected 200, got {resp.status_code}")
            data = resp.json()
            if works:
                mission_id = data.get("mission_id")
                if not mission_id:
                    issues.append("Missing 'mission_id' in response")
                if "status" not in data:
                    issues.append("Missing 'status' in response")
                if "objective" not in data:
                    issues.append("Missing 'objective' in response")
                if "phases" not in data:
                    issues.append("Missing 'phases' in response")
            results.append(EndpointResult(
                endpoint="/api/missions", method="POST",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 2. GET /api/missions/{id} — get mission status
        # ------------------------------------------------------------------
        test_id = mission_id or "test-mission-123"
        print(f"Testing GET /api/missions/{test_id} ...")
        start = time.perf_counter()
        try:
            resp = client.get(f"/api/missions/{test_id}")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/missions/{id}", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code in (200, 404)
            if resp.status_code not in (200, 404):
                issues.append(f"Unexpected status: {resp.status_code}")
            data = resp.json()
            if resp.status_code == 200:
                for key in ("mission_id", "status", "objective", "current_phase", "phases"):
                    if key not in data:
                        issues.append(f"Missing '{key}' in response")
            elif resp.status_code == 404:
                if "detail" not in data:
                    issues.append("Missing 'detail' in 404 response")
            results.append(EndpointResult(
                endpoint="/api/missions/{id}", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 3. GET /api/missions/{id}/agents — list active agents
        # ------------------------------------------------------------------
        print(f"Testing GET /api/missions/{test_id}/agents ...")
        start = time.perf_counter()
        try:
            resp = client.get(f"/api/missions/{test_id}/agents")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/missions/{id}/agents", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code in (200, 404)
            if resp.status_code not in (200, 404):
                issues.append(f"Unexpected status: {resp.status_code}")
            data = resp.json()
            if resp.status_code == 200:
                for key in ("mission_id", "agents"):
                    if key not in data:
                        issues.append(f"Missing '{key}' in response")
            results.append(EndpointResult(
                endpoint="/api/missions/{id}/agents", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 4. POST /api/missions/{id}/pause — pause
        # ------------------------------------------------------------------
        print(f"Testing POST /api/missions/{test_id}/pause ...")
        start = time.perf_counter()
        try:
            resp = client.post(f"/api/missions/{test_id}/pause")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/missions/{id}/pause", method="POST", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code in (200, 404)
            if resp.status_code not in (200, 404):
                issues.append(f"Unexpected status: {resp.status_code}")
            data = resp.json()
            if resp.status_code == 200:
                for key in ("mission_id", "status", "action"):
                    if key not in data:
                        issues.append(f"Missing '{key}' in response")
                if data.get("action") != "pause":
                    issues.append(f"Expected action='pause', got '{data.get('action')}'")
            results.append(EndpointResult(
                endpoint="/api/missions/{id}/pause", method="POST",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 5. POST /api/missions/{id}/resume — resume
        # ------------------------------------------------------------------
        print(f"Testing POST /api/missions/{test_id}/resume ...")
        start = time.perf_counter()
        try:
            resp = client.post(f"/api/missions/{test_id}/resume")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/missions/{id}/resume", method="POST", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code in (200, 404)
            if resp.status_code not in (200, 404):
                issues.append(f"Unexpected status: {resp.status_code}")
            data = resp.json()
            if resp.status_code == 200:
                for key in ("mission_id", "status", "action"):
                    if key not in data:
                        issues.append(f"Missing '{key}' in response")
                if data.get("action") != "resume":
                    issues.append(f"Expected action='resume', got '{data.get('action')}'")
            results.append(EndpointResult(
                endpoint="/api/missions/{id}/resume", method="POST",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 6. POST /api/missions/{id}/abort — abort
        # ------------------------------------------------------------------
        print(f"Testing POST /api/missions/{test_id}/abort ...")
        start = time.perf_counter()
        try:
            resp = client.post(f"/api/missions/{test_id}/abort")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/missions/{id}/abort", method="POST", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code in (200, 404)
            if resp.status_code not in (200, 404):
                issues.append(f"Unexpected status: {resp.status_code}")
            data = resp.json()
            if resp.status_code == 200:
                for key in ("mission_id", "status", "action"):
                    if key not in data:
                        issues.append(f"Missing '{key}' in response")
                if data.get("action") != "abort":
                    issues.append(f"Expected action='abort', got '{data.get('action')}'")
            results.append(EndpointResult(
                endpoint="/api/missions/{id}/abort", method="POST",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 7. GET /api/agents/instances — list all agent instances
        # ------------------------------------------------------------------
        print("Testing GET /api/agents/instances ...")
        start = time.perf_counter()
        try:
            resp = client.get("/api/agents/instances")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/agents/instances", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code == 200
            if not works:
                issues.append(f"Expected 200, got {resp.status_code}")
            data = resp.json()
            if works:
                for key in ("instances", "count", "stats"):
                    if key not in data:
                        issues.append(f"Missing '{key}' in response")
            results.append(EndpointResult(
                endpoint="/api/agents/instances", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 8. GET /api/overseer/dashboard — overseer dashboard
        # ------------------------------------------------------------------
        print("Testing GET /api/overseer/dashboard ...")
        start = time.perf_counter()
        try:
            resp = client.get("/api/overseer/dashboard")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/overseer/dashboard", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code in (200, 503)
            if resp.status_code not in (200, 503):
                issues.append(f"Unexpected status: {resp.status_code}")
            data = resp.json()
            results.append(EndpointResult(
                endpoint="/api/overseer/dashboard", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 9. GET /api/bus/topics — bus topics
        # ------------------------------------------------------------------
        print("Testing GET /api/bus/topics ...")
        start = time.perf_counter()
        try:
            resp = client.get("/api/bus/topics")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/bus/topics", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code == 200
            if not works:
                issues.append(f"Expected 200, got {resp.status_code}")
            data = resp.json()
            if works and "topics" not in data:
                issues.append("Missing 'topics' in response")
            results.append(EndpointResult(
                endpoint="/api/bus/topics", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 10. GET /api/whiteboard — shared memory
        # ------------------------------------------------------------------
        print("Testing GET /api/whiteboard ...")
        start = time.perf_counter()
        try:
            resp = client.get("/api/whiteboard")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/whiteboard", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code == 200
            if not works:
                issues.append(f"Expected 200, got {resp.status_code}")
            data = resp.json()
            if works:
                for key in ("entries", "count"):
                    if key not in data:
                        issues.append(f"Missing '{key}' in response")
            results.append(EndpointResult(
                endpoint="/api/whiteboard", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 11. GET /api/reviews — peer reviews
        # NOTE: Actual route is /api/reviews/{artifact_id}. We test both.
        # ------------------------------------------------------------------
        print("Testing GET /api/reviews/test-artifact ...")
        start = time.perf_counter()
        try:
            resp = client.get("/api/reviews/test-artifact")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/reviews/{artifact_id}", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code in (200, 404)
            if resp.status_code not in (200, 404):
                issues.append(f"Unexpected status: {resp.status_code}")
            data = resp.json()
            results.append(EndpointResult(
                endpoint="/api/reviews/{artifact_id}", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # Also test the bare /api/reviews to see if it exists
        print("Testing GET /api/reviews (bare) ...")
        start = time.perf_counter()
        try:
            resp = client.get("/api/reviews")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/reviews", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code in (404, 405, 307, 308)
            if not works:
                issues.append(f"Unexpected status: {resp.status_code} (bare /reviews likely missing)")
            data = resp.json()
            results.append(EndpointResult(
                endpoint="/api/reviews (bare)", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 12. GET /api/auto-correction/status — auto correction
        # ------------------------------------------------------------------
        print("Testing GET /api/auto-correction/status ...")
        start = time.perf_counter()
        try:
            resp = client.get("/api/auto-correction/status")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/auto-correction/status", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code == 200
            if not works:
                issues.append(f"Expected 200, got {resp.status_code}")
            data = resp.json()
            results.append(EndpointResult(
                endpoint="/api/auto-correction/status", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 13. GET /api/workers — background workers
        # ------------------------------------------------------------------
        print("Testing GET /api/workers ...")
        start = time.perf_counter()
        try:
            resp = client.get("/api/workers")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/workers", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code == 200
            if not works:
                issues.append(f"Expected 200, got {resp.status_code}")
            data = resp.json()
            if works and "workers" not in data:
                issues.append("Missing 'workers' in response")
            results.append(EndpointResult(
                endpoint="/api/workers", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

        # ------------------------------------------------------------------
        # 14. GET /api/system/self-improvement — self improvement proposals
        # ------------------------------------------------------------------
        print("Testing GET /api/system/self-improvement ...")
        start = time.perf_counter()
        try:
            resp = client.get("/api/system/self-improvement")
        except Exception as exc:
            results.append(EndpointResult(
                endpoint="/api/system/self-improvement", method="GET", status_code=0,
                response_time_ms=(time.perf_counter() - start) * 1000,
                works=False, issues=[f"Exception: {exc}"],
            ))
        else:
            elapsed = (time.perf_counter() - start) * 1000
            issues = []
            works = resp.status_code in (200, 404)
            if resp.status_code not in (200, 404):
                issues.append(f"Unexpected status: {resp.status_code}")
            data = resp.json()
            results.append(EndpointResult(
                endpoint="/api/system/self-improvement", method="GET",
                status_code=resp.status_code, response_time_ms=elapsed,
                works=works and not issues, issues=issues,
                response_preview=truncate(data),
            ))

    return results


def print_report(results: list[EndpointResult]) -> None:
    print("\n" + "=" * 100)
    print("MISSION CONTROL API - END-TO-END TEST REPORT")
    print("=" * 100)

    print(f"\n{'Endpoint':<45} {'Method':<8} {'Status':<8} {'Time (ms)':<12} {'Works?':<8} {'Issues'}")
    print("-" * 100)

    total = len(results)
    passing = 0
    failing = 0
    missing = []
    broken = []
    slow = []

    for r in results:
        status_str = str(r.status_code) if r.status_code else "ERR"
        works_str = "PASS" if r.works else "FAIL"
        issues_str = "; ".join(r.issues) if r.issues else "None"
        print(f"{r.endpoint:<45} {r.method:<8} {status_str:<8} {r.response_time_ms:>10.2f}  {works_str:<8} {issues_str}")

        if r.works:
            passing += 1
        else:
            failing += 1
            if r.status_code in (404, 405):
                missing.append(r.endpoint)
            else:
                broken.append(r.endpoint)

        if r.response_time_ms > 2000:
            slow.append((r.endpoint, r.response_time_ms))

    print("-" * 100)
    print(f"TOTAL: {total} | PASSING: {passing} | FAILING: {failing}")

    print("\n" + "=" * 100)
    print("OVERALL API HEALTH ASSESSMENT")
    print("=" * 100)
    health_pct = (passing / total * 100) if total else 0
    if health_pct >= 90:
        health = "HEALTHY"
        emoji = "[OK]"
    elif health_pct >= 70:
        health = "DEGRADED"
        emoji = "[WARN]"
    else:
        health = "CRITICAL"
        emoji = "[FAIL]"
    print(f"{emoji} Health Score: {health_pct:.1f}% ({health})")

    print("\n" + "=" * 100)
    print("MISSING ENDPOINTS OR BROKEN ROUTES")
    print("=" * 100)
    if missing:
        print("Potentially missing routes (returned 404/405):")
        for m in missing:
            print(f"  - {m}")
    else:
        print("No routes returned 404/405.")

    if broken:
        print("\nBroken routes (returned unexpected errors):")
        for b in broken:
            print(f"  - {b}")
    else:
        print("No broken routes detected.")

    if slow:
        print("\nSlow endpoints (>2000 ms):")
        for endpoint, ms in slow:
            print(f"  - {endpoint}: {ms:.2f} ms")

    print("\n" + "=" * 100)
    print("RECOMMENDATIONS")
    print("=" * 100)
    if missing:
        print("1. Implement missing endpoints or update documentation:")
        for m in missing:
            print(f"   - {m}")
    if broken:
        print("2. Fix broken routes - investigate server-side exceptions or misconfigurations.")
    if slow:
        print("3. Optimize slow endpoints - consider caching or async background tasks.")
    if not missing and not broken and not slow:
        print("[OK] All tested endpoints are responding correctly and within acceptable latency.")
    if any("mission" in b for b in broken):
        print("4. Mission lifecycle endpoints may fail when no mission exists - ensure proper test isolation.")
    if any("overseer" in b for b in broken):
        print("5. Overseer dashboard depends on the OVERSEER agent being registered - verify registry initialization.")
    if any("self-improvement" in m for m in missing + broken):
        print("6. Self-improvement endpoint returns 404 when no report has been generated - this is expected on a fresh instance.")

    print("\n" + "=" * 100)


def main() -> None:
    print("Starting Mission Control API end-to-end test...")
    try:
        results = run_tests()
    except Exception as exc:
        print(f"FATAL ERROR during test execution: {exc}")
        traceback.print_exc()
        sys.exit(1)
    print_report(results)


if __name__ == "__main__":
    main()
