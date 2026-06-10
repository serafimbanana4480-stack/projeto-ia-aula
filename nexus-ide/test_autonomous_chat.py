import httpx
import json
import sys

url = "http://localhost:8000/api/chat"

# Test 1: Ask the agent to read a file (requires tool use)
payload1 = {
    "session_id": "test-auto-001",
    "message": "Read the README.md file and tell me what this project is about",
    "mode": "agent"
}

print("[TEST 1] Autonomous agent chat with tool use...")
try:
    with httpx.stream("POST", url, json=payload1, headers={"Accept": "text/event-stream"}, timeout=30.0) as response:
        print(f"Status: {response.status_code}")
        tokens = []
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                try:
                    event = json.loads(data)
                    events.append(event)
                    if event.get('type') == 'token':
                        tokens.append(event.get('content', ''))
                except:
                    pass
        full_response = ''.join(tokens)
        print(f"Response: {full_response[:300]}...")
        print(f"Events: {[e.get('type') for e in events]}")
except Exception as e:
    print(f"Error: {e}")

# Test 2: Plan mode
print("\n[TEST 2] Plan mode...")
payload2 = {
    "session_id": "test-plan-001",
    "message": "Create a plan to improve the backend performance",
    "mode": "plan"
}
try:
    with httpx.stream("POST", url, json=payload2, headers={"Accept": "text/event-stream"}, timeout=30.0) as response:
        tokens = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                try:
                    event = json.loads(data)
                    if event.get('type') == 'token':
                        tokens.append(event.get('content', ''))
                except:
                    pass
        print(f"Plan response: {''.join(tokens)[:300]}...")
except Exception as e:
    print(f"Error: {e}")

# Test 3: Auto mode
print("\n[TEST 3] Auto mode (autonomous execution)...")
payload3 = {
    "session_id": "test-auto-002",
    "message": "List all Python files in the backend directory",
    "mode": "auto"
}
try:
    with httpx.stream("POST", url, json=payload3, headers={"Accept": "text/event-stream"}, timeout=30.0) as response:
        tokens = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                try:
                    event = json.loads(data)
                    if event.get('type') == 'token':
                        tokens.append(event.get('content', ''))
                except:
                    pass
        print(f"Auto response: {''.join(tokens)[:300]}...")
except Exception as e:
    print(f"Error: {e}")
