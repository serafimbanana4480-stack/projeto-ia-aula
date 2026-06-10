import httpx
import json
import sys

url = "http://localhost:8000/api/chat"
payload = {
    "session_id": "test-autonomy-001",
    "message": "Read the README.md file and tell me what this project is about in one sentence.",
    "mode": "agent",
    "project_path": "."
}

print("[TEST] Testing autonomous agent with tool usage...")
try:
    with httpx.stream("POST", url, json=payload, headers={"Accept": "text/event-stream"}, timeout=60.0) as response:
        print(f"[TEST] Status: {response.status_code}")
        if response.status_code != 200:
            print(f"[FAIL] Status: {response.status_code}")
            print(response.text())
            sys.exit(1)

        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                try:
                    event = json.loads(data)
                    events.append(event)
                    t = event.get('type')
                    if t in ('routing', 'agent_started', 'agent_finished', 'done', 'error'):
                        print(f"[EVENT] {t}: agent={event.get('agent')}")
                    elif t == 'tool_call':
                        print(f"[EVENT] {t}: {event.get('content', '')[:100]}")
                    elif t == 'token':
                        print(f"[EVENT] {t}: {event.get('content', '')[:80]}")
                    else:
                        print(f"[EVENT] {t}: {str(event)[:100]}")
                except json.JSONDecodeError:
                    pass

        types = [e.get("type") for e in events]
        print(f"\n[TEST] Events: {types}")

        has_tool = "tool_call" in types or "tool_result" in types
        print(f"[TEST] Used tools: {has_tool}")

        if "error" in types:
            print("[FAIL] Error events found")
            sys.exit(1)
        if "done" not in types:
            print("[FAIL] No done event")
            sys.exit(1)

        print("[PASS] Autonomous chat completed successfully")
        sys.exit(0)

except Exception as exc:
    print(f"[EXCEPTION] {exc}")
    sys.exit(1)
