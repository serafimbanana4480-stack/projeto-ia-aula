#!/usr/bin/env python3
"""End-to-end test script for all NEXUS IDE chat modes.

Tests POST /api/chat for each mode and produces a detailed report.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

API_URL = "http://localhost:8000/api/chat"
TIMEOUT_SECONDS = 45


@dataclass
class ModeResult:
    mode: str
    prompt: str
    status: str = "pending"
    response_time_ms: float = 0.0
    is_streaming: bool = False
    got_done: bool = False
    routing_agent: str = ""
    routing_reason: str = ""
    used_agent: str = ""
    token_count: int = 0
    error: str = ""
    events: list[dict] = field(default_factory=list)
    first_token_latency_ms: float = 0.0


def _parse_sse(raw: bytes) -> list[dict]:
    """Parse SSE body into JSON events."""
    events: list[dict] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[len("data: "):]))
            except json.JSONDecodeError as exc:
                events.append({"type": "parse_error", "raw": line, "error": str(exc)})
    return events


def test_mode(mode: str, prompt: str) -> ModeResult:
    """Call /api/chat for a single mode and collect metrics."""
    result = ModeResult(mode=mode, prompt=prompt)
    session_id = f"e2e-test-{mode}-{uuid.uuid4().hex[:8]}"
    payload = {
        "message": prompt,
        "session_id": session_id,
        "mode": mode,
        "model": "",
        "project_path": "",
    }

    start = time.perf_counter()
    first_token_time: float | None = None

    try:
        with httpx.stream(
            "POST",
            API_URL,
            json=payload,
            timeout=TIMEOUT_SECONDS,
            headers={"Accept": "text/event-stream"},
        ) as response:
            elapsed_ms = (time.perf_counter() - start) * 1000
            result.response_time_ms = round(elapsed_ms, 2)

            if response.status_code != 200:
                result.status = "http_error"
                body = response.read(timeout=5)
                result.error = f"HTTP {response.status_code}: {body.decode('utf-8', errors='replace')[:500]}"
                return result

            content_type = response.headers.get("content-type", "")
            result.is_streaming = "text/event-stream" in content_type

            # Read the full SSE stream
            raw = b""
            for chunk in response.iter_bytes():
                raw += chunk
                if first_token_time is None and raw:
                    first_token_time = time.perf_counter()

            result.events = _parse_sse(raw)
    except httpx.ReadTimeout:
        result.status = "timeout"
        result.error = f"Read timeout after {TIMEOUT_SECONDS}s"
        result.response_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return result
    except Exception as exc:
        result.status = "exception"
        result.error = f"{type(exc).__name__}: {exc}"
        result.response_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return result

    # Calculate first-token latency
    if first_token_time is not None:
        result.first_token_latency_ms = round((first_token_time - start) * 1000, 2)

    # Analyze events
    types = [e.get("type") for e in result.events]
    result.got_done = "done" in types

    # Routing decision
    for ev in result.events:
        if ev.get("type") == "routing" and ev.get("routing"):
            result.routing_agent = ev["routing"].get("primary_agent", "")
            result.routing_reason = ev["routing"].get("routing_reason", "")

    # Agent used (from agent_started)
    for ev in result.events:
        if ev.get("type") == "agent_started" and ev.get("agent"):
            result.used_agent = ev["agent"]
            break

    # Token count
    result.token_count = sum(
        len(str(e.get("content", ""))) for e in result.events if e.get("type") == "token"
    )

    # Check for errors in stream
    error_events = [e for e in result.events if e.get("type") == "error"]
    if error_events:
        result.error = " | ".join(str(e.get("content", "")) for e in error_events)

    # Determine final status
    if result.got_done and not result.error:
        result.status = "success"
    elif result.error:
        result.status = "stream_error"
    else:
        result.status = "incomplete"

    return result


def _print_table(results: list[ModeResult]) -> None:
    """Print a markdown-friendly results table."""
    header = "| Mode   | Status | Response Time | First Token | Agent Used | Routing Reason | Tokens | Issues |"
    sep = "|--------|--------|---------------|-------------|------------|----------------|--------|--------|"
    print(header)
    print(sep)
    for r in results:
        issues = r.error if r.error else ("No done event" if not r.got_done else "None")
        print(
            f"| {r.mode:<6} | {r.status:<6} | {r.response_time_ms:>8.1f} ms | "
            f"{r.first_token_latency_ms:>7.1f} ms | {r.used_agent or '-':<10} | "
            f"{r.routing_reason or '-':<14} | {r.token_count:>6} | {issues:<30} |"
        )


def _print_detailed(results: list[ModeResult]) -> None:
    """Print detailed event logs for each mode."""
    for r in results:
        print(f"\n{'='*60}")
        print(f"MODE: {r.mode.upper()}  |  Session: {r.prompt[:40]}...")
        print(f"{'='*60}")
        print(f"  Status          : {r.status}")
        print(f"  Response Time   : {r.response_time_ms:.1f} ms")
        print(f"  First Token     : {r.first_token_latency_ms:.1f} ms")
        print(f"  Streaming       : {r.is_streaming}")
        print(f"  Got 'done'      : {r.got_done}")
        print(f"  Routing Agent   : {r.routing_agent}")
        print(f"  Used Agent      : {r.used_agent}")
        print(f"  Routing Reason  : {r.routing_reason}")
        print(f"  Token Chars     : {r.token_count}")
        print(f"  Event Types     : {[e.get('type') for e in r.events]}")
        if r.error:
            print(f"  ERROR           : {r.error}")


def main() -> int:
    modes = [
        ("ask", "what is Python?"),
        ("agent", "write a hello world function"),
        ("plan", "plan a REST API for a todo app"),
        ("debug", "fix this code: print(x)"),
        ("auto", "create a Python script that calculates fibonacci"),
        ("swarm", "design a caching system"),
    ]

    print("NEXUS IDE — Chat Modes End-to-End Test")
    print(f"API: {API_URL}")
    print(f"Timeout: {TIMEOUT_SECONDS}s per mode\n")

    results: list[ModeResult] = []
    for mode, prompt in modes:
        print(f"Testing mode='{mode}' ... ", end="", flush=True)
        result = test_mode(mode, prompt)
        results.append(result)
        print(f"{result.status} ({result.response_time_ms:.0f} ms)")

    print("\n" + "=" * 80)
    print("SUMMARY TABLE")
    print("=" * 80)
    _print_table(results)

    print("\n" + "=" * 80)
    print("DETAILED RESULTS")
    print("=" * 80)
    _print_detailed(results)

    # Overall assessment
    successes = [r for r in results if r.status == "success"]
    failures = [r for r in results if r.status != "success"]
    avg_time = sum(r.response_time_ms for r in results) / len(results) if results else 0
    avg_first = sum(r.first_token_latency_ms for r in results) / len(results) if results else 0

    print("\n" + "=" * 80)
    print("OVERALL ASSESSMENT")
    print("=" * 80)
    print(f"Total modes tested : {len(results)}")
    print(f"Successful         : {len(successes)}")
    print(f"Failed             : {len(failures)}")
    print(f"Avg response time  : {avg_time:.1f} ms")
    print(f"Avg first token    : {avg_first:.1f} ms")
    print(f"Streaming SSE      : {all(r.is_streaming for r in results)}")
    print(f"All got 'done'     : {all(r.got_done for r in results)}")

    print("\n" + "=" * 80)
    print("BOTTLENECKS IDENTIFIED")
    print("=" * 80)
    slow = sorted(results, key=lambda r: r.response_time_ms, reverse=True)[:3]
    for r in slow:
        print(f"  - {r.mode}: {r.response_time_ms:.1f} ms (agent={r.used_agent or '-'})")

    if not all(r.is_streaming for r in results):
        non_stream = [r.mode for r in results if not r.is_streaming]
        print(f"  - Non-streaming responses: {', '.join(non_stream)}")

    if failures:
        print(f"  - Failed modes: {', '.join(r.mode for r in failures)}")
        for r in failures:
            print(f"      {r.mode}: {r.error[:200]}")

    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    if failures:
        print("1. Investigate failures — check Ollama model availability and backend logs.")
    if any(r.response_time_ms > 30000 for r in results):
        print("2. Some modes exceed 30s — consider caching or lighter fallback models.")
    if not all(r.got_done for r in results):
        print("3. Missing 'done' events detected — verify SSE stream closure logic.")
    if avg_first > 5000:
        print("4. High first-token latency — consider using a smaller/faster model for routing.")
    print("5. Run tests with actual traffic patterns to validate rate limits (60/min).")
    print("6. Consider adding health checks before each test to avoid false negatives.")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
