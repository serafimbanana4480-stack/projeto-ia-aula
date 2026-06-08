#!/usr/bin/env python3
"""
NEXUS IDE Mission Control Dashboard - Online Backend Test
Tests the dashboard with backend and Ollama running.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = "http://localhost:3000"
API_URL = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
OUTPUT_DIR = Path(__file__).parent / "test_output_online"
OUTPUT_DIR.mkdir(exist_ok=True)

REPORT = {
    "timestamp": datetime.now().isoformat(),
    "api_tests": {},
    "ui_tests": {},
    "screenshots": [],
    "console_errors": [],
    "issues": [],
    "summary": {},
}


def log(msg: str):
    try:
        print(f"[TEST] {msg}")
    except UnicodeEncodeError:
        print(f"[TEST] {msg.encode('ascii', 'replace').decode('ascii')}")


def api_get(endpoint: str, timeout: int = 10) -> tuple[int, dict | str, float]:
    """Call a GET endpoint and return (status, body, elapsed_ms)."""
    url = f"{API_URL}{endpoint}"
    start = time.time()
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            elapsed = (time.time() - start) * 1000
            try:
                return resp.status, json.loads(body), elapsed
            except json.JSONDecodeError:
                return resp.status, body, elapsed
    except urllib.error.HTTPError as e:
        elapsed = (time.time() - start) * 1000
        body = e.read().decode("utf-8", errors="replace") if e.read() else ""
        return e.code, body, elapsed
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return 0, str(e), elapsed


# ===========================================================================
# 1. API Endpoint Tests
# ===========================================================================
def test_api_endpoints():
    log("=== Testing API Endpoints ===")
    endpoints = [
        "/health",
        "/api/bus/topics",
        "/api/agents/instances",
        "/api/overseer/dashboard",
        "/api/missions",
    ]

    for ep in endpoints:
        status, body, elapsed = api_get(ep)
        ok = status == 200
        REPORT["api_tests"][ep] = {
            "status": status,
            "ok": ok,
            "elapsed_ms": round(elapsed, 2),
            "body_preview": str(body)[:300] if isinstance(body, str) else json.dumps(body)[:300],
        }
        marker = "[OK]" if ok else "[FAIL]"
        log(f"{marker} {ep} -> {status} ({elapsed:.1f}ms)")
        if not ok:
            REPORT["issues"].append(f"API {ep} returned {status}")


# ===========================================================================
# 2. Playwright UI Tests
# ===========================================================================
def test_ui():
    log("=== Starting Playwright UI Tests ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # Collect console messages
        console_logs = []
        page.on("console", lambda msg: console_logs.append({
            "type": msg.type,
            "text": msg.text,
            "location": str(msg.location),
        }))

        # Collect page errors
        page_errors = []
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        # --- Navigate to Mission Control ---
        log("Navigating to /mission-control ...")
        start = time.time()
        page.goto(f"{BASE_URL}/mission-control", wait_until="networkidle", timeout=30000)
        load_time = (time.time() - start) * 1000
        REPORT["ui_tests"]["page_load_ms"] = round(load_time, 2)
        log(f"Page loaded in {load_time:.1f}ms")

        # Wait for API data to load
        log("Waiting for API data to load...")
        time.sleep(3)

        # Screenshot 1: Initial load
        ss1 = OUTPUT_DIR / "01_mission_control_initial.png"
        page.screenshot(path=str(ss1), full_page=True)
        REPORT["screenshots"].append(str(ss1))
        log(f"Screenshot saved: {ss1}")

        # --- Check panels for data ---
        log("Checking Mission Control panels...")
        panels = {
            "active_missions": [
                "Active Missions",
                "Missões Ativas",
                "mission",
            ],
            "agent_grid": [
                "Agent Grid",
                " agent",
                "agents",
            ],
            "quality_gates": [
                "Quality Gates",
                "Qualidade",
                "quality",
            ],
            "system_health": [
                "System Health",
                "Saúde",
                "health",
                "CPU",
                "RAM",
            ],
        }

        page_content = page.content()
        for panel_name, keywords in panels.items():
            found = any(kw.lower() in page_content.lower() for kw in keywords)
            REPORT["ui_tests"][f"panel_{panel_name}_found"] = found
            marker = "[OK]" if found else "[FAIL]"
            log(f"{marker} Panel '{panel_name}' detected: {found}")

        # --- Test Chat ---
        log("Testing chat functionality...")
        try:
            # Try to find chat input
            chat_input = page.locator("textarea[placeholder*='mensagem' i], textarea[placeholder*='message' i], input[placeholder*='mensagem' i], input[placeholder*='message' i], [data-testid='chat-input']").first
            if chat_input.count() == 0:
                # Fallback: any textarea or input near "chat"
                chat_input = page.locator("textarea").first
            
            if chat_input.count() > 0:
                chat_input.scroll_into_view_if_needed()
                chat_input.fill("hello")
                log("Typed 'hello' into chat input")

                # Find send button
                send_btn = page.locator("button:has-text('Send'), button:has-text('Enviar'), button[type='submit']").first
                if send_btn.count() > 0:
                    send_btn.click()
                    log("Clicked send button")
                else:
                    # Try pressing Enter
                    chat_input.press("Enter")
                    log("Pressed Enter to send")

                # Wait for response
                time.sleep(8)

                # Screenshot 2: After chat
                ss2 = OUTPUT_DIR / "02_mission_control_chat.png"
                page.screenshot(path=str(ss2), full_page=True)
                REPORT["screenshots"].append(str(ss2))
                log(f"Screenshot saved: {ss2}")

                # Check if response appeared
                response_found = page.locator("text=hello").count() > 1 or page.locator(".message, .chat-message, [data-testid='chat-message']").count() > 1
                REPORT["ui_tests"]["chat_response_found"] = response_found
                log(f"Chat response detected: {response_found}")
            else:
                log("[FAIL] Chat input not found")
                REPORT["issues"].append("Chat input not found")
                REPORT["ui_tests"]["chat_response_found"] = False
        except Exception as e:
            log(f"[FAIL] Chat test error: {e}")
            REPORT["issues"].append(f"Chat test error: {e}")
            REPORT["ui_tests"]["chat_response_found"] = False

        # --- Test Navigation ---
        log("Testing navigation...")
        nav_links = [
            ("/", "Home"),
            ("/mission-control", "Mission Control"),
            ("/workspace", "Workspace"),
        ]
        for path, name in nav_links:
            try:
                page.goto(f"{BASE_URL}{path}", wait_until="networkidle", timeout=15000)
                time.sleep(1)
                ss = OUTPUT_DIR / f"03_nav_{name.lower().replace(' ', '_')}.png"
                page.screenshot(path=str(ss), full_page=True)
                REPORT["screenshots"].append(str(ss))
                log(f"[OK] Navigated to {name} ({path})")
            except Exception as e:
                log(f"[FAIL] Navigation to {name} failed: {e}")
                REPORT["issues"].append(f"Navigation to {name} failed: {e}")

        # --- Test Responsive Layout ---
        log("Testing responsive layout...")
        for width, label in [(1280, "desktop"), (768, "tablet"), (375, "mobile")]:
            page.set_viewport_size({"width": width, "height": 900})
            page.goto(f"{BASE_URL}/mission-control", wait_until="networkidle", timeout=15000)
            time.sleep(1)
            ss = OUTPUT_DIR / f"04_responsive_{label}.png"
            page.screenshot(path=str(ss), full_page=True)
            REPORT["screenshots"].append(str(ss))
            log(f"[OK] Responsive screenshot: {label} ({width}px)")

        # --- Console Errors ---
        log("Collecting console messages...")
        errors = [c for c in console_logs if c["type"] == "error"]
        warnings = [c for c in console_logs if c["type"] == "warning"]
        REPORT["console_errors"] = errors
        REPORT["ui_tests"]["console_error_count"] = len(errors)
        REPORT["ui_tests"]["console_warning_count"] = len(warnings)
        log(f"Console errors: {len(errors)}, warnings: {len(warnings)}")
        for err in errors[:10]:
            log(f"  ERROR: {err['text'][:150]}")

        # --- Page Errors ---
        REPORT["ui_tests"]["page_error_count"] = len(page_errors)
        for err in page_errors[:5]:
                log(f"  [PAGE ERROR] {err[:150]}")

        browser.close()


# ===========================================================================
# 3. Report Generation
# ===========================================================================
def generate_report():
    log("=== Generating Report ===")
    report_path = OUTPUT_DIR / "mission_control_online_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(REPORT, f, indent=2, ensure_ascii=False)
    log(f"Report saved: {report_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("NEXUS IDE Mission Control - ONLINE TEST REPORT")
    print("=" * 60)
    print(f"\nTimestamp: {REPORT['timestamp']}")

    print("\n--- API Tests ---")
    api_ok = 0
    api_total = 0
    for ep, result in REPORT["api_tests"].items():
        api_total += 1
        if result["ok"]:
            api_ok += 1
        print(f"  {'[OK]' if result['ok'] else '[FAIL]'} {ep} -> HTTP {result['status']} ({result['elapsed_ms']}ms)")
    print(f"\nAPI Success Rate: {api_ok}/{api_total}")

    print("\n--- UI Tests ---")
    print(f"  Page Load: {REPORT['ui_tests'].get('page_load_ms', 'N/A')}ms")
    print(f"  Console Errors: {REPORT['ui_tests'].get('console_error_count', 'N/A')}")
    print(f"  Console Warnings: {REPORT['ui_tests'].get('console_warning_count', 'N/A')}")
    print(f"  Page Errors: {REPORT['ui_tests'].get('page_error_count', 'N/A')}")
    print(f"  Chat Response: {'[OK]' if REPORT['ui_tests'].get('chat_response_found') else '[FAIL]'}")
    print(f"  Panel - Active Missions: {'[OK]' if REPORT['ui_tests'].get('panel_active_missions_found') else '[FAIL]'}")
    print(f"  Panel - Agent Grid: {'[OK]' if REPORT['ui_tests'].get('panel_agent_grid_found') else '[FAIL]'}")
    print(f"  Panel - Quality Gates: {'[OK]' if REPORT['ui_tests'].get('panel_quality_gates_found') else '[FAIL]'}")
    print(f"  Panel - System Health: {'[OK]' if REPORT['ui_tests'].get('panel_system_health_found') else '[FAIL]'}")

    print("\n--- Issues Found ---")
    if REPORT["issues"]:
        for issue in REPORT["issues"]:
            print(f"  [FAIL] {issue}")
    else:
        print("  [OK] No issues found")

    print("\n--- Screenshots ---")
    for ss in REPORT["screenshots"]:
        print(f"  📸 {ss}")

    print("\n--- Overall Assessment ---")
    if api_ok == api_total and not REPORT["issues"]:
        print("[OK] ALL TESTS PASSED - Backend is online and responding correctly")
    elif api_ok == api_total:
        print("[WARN] API OK but UI issues detected")
    else:
        print("[FAIL] SOME TESTS FAILED - See details above")
    print("=" * 60)


def main():
    log("NEXUS IDE Mission Control - Online Backend Test Starting")
    log(f"Frontend: {BASE_URL}")
    log(f"Backend: {API_URL}")
    log(f"Ollama: {OLLAMA_URL}")
    log(f"Output: {OUTPUT_DIR}")

    # Pre-flight checks
    _, _, _ = api_get("/health")

    test_api_endpoints()
    test_ui()
    generate_report()

    # Exit code: 0 if all API OK and no critical issues
    api_all_ok = all(r["ok"] for r in REPORT["api_tests"].values())
    sys.exit(0 if api_all_ok else 1)


if __name__ == "__main__":
    main()
