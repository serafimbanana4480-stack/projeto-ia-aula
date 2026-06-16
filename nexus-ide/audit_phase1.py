import jwt, requests, json, time, os, sys

os.chdir(r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide")

NEXUS = "http://localhost:8000"
SECRET = "4hD3jNzDt0mcH1n9jGDluQW5kCIkFs5b7hrdtDnJDE0"
OUT = (
    r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide\audit_results.json"
)


def tok():
    return jwt.encode(
        {"sub": "a749f196dc84408b", "email": "test@test.com", "exp": int(time.time()) + 3600},
        SECRET,
        algorithm="HS256",
    )


def chat(msg, mode="agent"):
    h = {"Authorization": f"Bearer {tok()}", "Content-Type": "application/json"}
    r = requests.post(
        f"{NEXUS}/api/chat",
        headers=h,
        json={"message": msg, "mode": mode, "session_id": f"s{int(time.time() * 1000)}"},
        timeout=30,
        stream=True,
    )
    if r.status_code != 200:
        return {"ok": False, "response": r.text[:300], "status": r.status_code}
    out = ""
    for line in r.iter_lines():
        if line:
            try:
                d = json.loads(line[6:]) if line.startswith(b"data: ") else json.loads(line)
                out += d.get("content", d.get("message", "")) if isinstance(d, dict) else str(d)
            except Exception:
                out += line.decode("utf-8", errors="replace")
    return {"ok": True, "response": out, "status": 200}


results = {}

# Phase 1 - Tool Inventory
print("=== PHASE 1 ===")
r = chat("List every tool, format: name | category | req_args | opt_args. One per line.")
results["tool_inventory"] = {"status": r["status"], "response": r["response"]}
print(f"OK={r['ok']} STATUS={r['status']}")
print(r["response"][:1000])

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("Saved")
