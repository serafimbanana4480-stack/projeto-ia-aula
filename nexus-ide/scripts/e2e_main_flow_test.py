#!/usr/bin/env python3
"""End-to-end smoke test for the main NEXUS IDE flow.

Validates the critical user journey:
    1. GET  /health
    2. GET  /api/providers
    3. POST /api/chat  (mode=auto)
    4. POST /api/chat  (mode=swarm)

Requires a running NEXUS backend (default: http://localhost:8000).
Use environment variables to configure:
    NEXUS_API_URL     base URL, e.g. http://localhost:8000
    NEXUS_TOKEN       JWT access token (optional; if unset a default dev token is used)
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE_URL = os.environ.get("NEXUS_API_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get(
    "NEXUS_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0LXVzZXIiLCJlbWFpbCI6InRlc3RAdGVzdC5jb20ifQ."
    "dummy-token-for-local-e2e-tests",
)
TIMEOUT_SECONDS = 120


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}


def _sse_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "text/event-stream"}


def _parse_sse(raw: bytes) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[len("data: "):]))
            except json.JSONDecodeError as exc:
                events.append({"type": "parse_error", "raw": line, "error": str(exc)})
    return events


def _new_session(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@dataclass
class StepResult:
    name: str
    passed: bool = False
    duration_ms: float = 0.0
    details: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)


def _step_health() -> StepResult:
    result = StepResult(name="health")
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            resp = client.get(f"{BASE_URL}/health", headers=_auth_headers())
        result.duration_ms = round((time.perf_counter() - start) * 1000, 2)
        if resp.status_code == 200 and resp.json().get("status") == "ok":
            result.passed = True
            result.details = "backend is alive"
        else:
            result.details = f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        result.details = f"{type(exc).__name__}: {exc}"
    return result


def _step_providers() -> StepResult:
    result = StepResult(name="providers")
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            resp = client.get(f"{BASE_URL}/api/providers", headers=_auth_headers())
        result.duration_ms = round((time.perf_counter() - start) * 1000, 2)
        if resp.status_code != 200:
            result.details = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return result
        data = resp.json()
        providers = data.get("providers", [])
        if not providers:
            result.details = "no providers configured"
            return result
        result.passed = True
        names = [p["id"] for p in providers]
        result.details = f"providers: {', '.join(names)}; active={data.get('active_provider')}"
    except Exception as exc:
        result.details = f"{type(exc).__name__}: {exc}"
    return result


def _step_chat_auto() -> StepResult:
    result = StepResult(name="chat_auto")
    session_id = _new_session("auto")
    payload = {
        "message": "create a Python script that calculates fibonacci",
        "session_id": session_id,
        "mode": "auto",
        "model": "",
        "project_path": "",
    }
    start = time.perf_counter()
    try:
        with httpx.stream(
            "POST",
            f"{BASE_URL}/api/chat",
            json=payload,
            timeout=TIMEOUT_SECONDS,
            headers=_sse_headers(),
        ) as resp:
            raw = b""
            for chunk in resp.iter_bytes():
                raw += chunk
            result.events = _parse_sse(raw)
        result.duration_ms = round((time.perf_counter() - start) * 1000, 2)

        if resp.status_code != 200:
            result.details = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return result

        types = [e.get("type") for e in result.events]
        errors = [e for e in result.events if e.get("type") == "error"]
        if errors:
            result.details = " | ".join(str(e.get("content", "")) for e in errors)
            return result

        if "routing" not in types or "done" not in types:
            result.details = f"missing events; got types: {types}"
            return result

        routing = next(e for e in result.events if e.get("type") == "routing")["routing"]
        if routing.get("primary_agent") != "CODER":
            result.details = f"unexpected agent: {routing.get('primary_agent')}"
            return result

        result.passed = True
        result.details = f"agent={routing.get('primary_agent')} reason={routing.get('routing_reason')}"
    except Exception as exc:
        result.details = f"{type(exc).__name__}: {exc}"
    return result


def _step_chat_swarm() -> StepResult:
    result = StepResult(name="chat_swarm")
    session_id = _new_session("swarm")
    payload = {
        "message": "design a simple caching system",
        "session_id": session_id,
        "mode": "swarm",
        "swarm_agents": ["CODER", "ANALYZER"],
        "swarm_strategy": "ensemble",
        "model": "",
        "project_path": "",
    }
    start = time.perf_counter()
    try:
        with httpx.stream(
            "POST",
            f"{BASE_URL}/api/chat",
            json=payload,
            timeout=TIMEOUT_SECONDS,
            headers=_sse_headers(),
        ) as resp:
            raw = b""
            for chunk in resp.iter_bytes():
                raw += chunk
            result.events = _parse_sse(raw)
        result.duration_ms = round((time.perf_counter() - start) * 1000, 2)

        if resp.status_code != 200:
            result.details = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return result

        types = [e.get("type") for e in result.events]
        errors = [e for e in result.events if e.get("type") == "error"]
        if errors:
            result.details = " | ".join(str(e.get("content", "")) for e in errors)
            return result

        if "done" not in types or "agent_started" not in types:
            result.details = f"missing events; got types: {types}"
            return result

        agents = {e.get("agent") for e in result.events if e.get("type") == "agent_started"}
        if "SWARM" not in agents:
            result.details = f"SWARM not started; agents: {agents}"
            return result

        result.passed = True
        result.details = f"agents: {', '.join(str(a) for a in agents if a)}"
    except Exception as exc:
        result.details = f"{type(exc).__name__}: {exc}"
    return result


def main() -> int:
    print(f"NEXUS IDE — Main Flow E2E Test")
    print(f"Base URL: {BASE_URL}")
    print(f"Timeout : {TIMEOUT_SECONDS}s per step\n")

    steps = [
        _step_health(),
        _step_providers(),
        _step_chat_auto(),
        _step_chat_swarm(),
    ]

    print("RESULTS")
    print("-" * 70)
    for step in steps:
        status = "PASS" if step.passed else "FAIL"
        print(f"[{status}] {step.name:<12} {step.duration_ms:>8.1f} ms  {step.details}")

    passed = sum(1 for s in steps if s.passed)
    failed = len(steps) - passed
    print("-" * 70)
    print(f"Total: {len(steps)} | Passed: {passed} | Failed: {failed}")

    if failed:
        print("\nFailed step details:")
        for step in steps:
            if not step.passed:
                print(f"  - {step.name}: {step.details}")
                for ev in step.events:
                    if ev.get("type") == "error":
                        print(f"      error event: {ev.get('content', '')[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
