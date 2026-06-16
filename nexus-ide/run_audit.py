import requests
import json
import time
import os
import sys
import jwt
import sqlite3

# Configure paths before imports that rely on CWD
os.chdir(r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide")
sys.path.insert(0, os.getcwd())

NEXUS_URL = "http://localhost:8000"
RESULTS_PATH = (
    r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide\audit_results.json"
)

# Read actual secret from .env
SECRET = "4hD3jNzDt0mcH1n9jGDluQW5kCIkFs5b7hrdtDnJDE0"

results = {}


def make_token(sub="a749f196dc84408b", email="test@test.com"):
    payload = {"sub": sub, "email": email, "exp": int(time.time()) + 7200}
    return jwt.encode(payload, SECRET, algorithm="HS256")


def nexus_chat(message, mode="agent"):
    token = make_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(
            f"{NEXUS_URL}/api/chat",
            headers=headers,
            json={
                "message": message,
                "mode": mode,
                "session_id": f"audit_{int(time.time() * 1000)}",
                "provider": "ollama",
                "model": "micro",
            },
            timeout=30,
            stream=True,
        )
        if resp.status_code != 200:
            return {"status": resp.status_code, "response": resp.text[:300], "ok": False}
        full_response = ""
        for line in resp.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                if decoded.startswith("data: "):
                    try:
                        event = json.loads(decoded[6:])
                        full_response += event.get("content", "")
                    except Exception:
                        full_response += decoded
        return {"status": 200, "response": full_response, "ok": True}
    except Exception as e:
        return {"status": 0, "response": str(e), "ok": False}


def record(test_id, action, verify, expected):
    passed = expected.lower() in verify["response"].lower()
    results[test_id] = {
        "status": "PASS" if passed else "FAIL",
        "verify": verify["response"][:300],
        "expected": expected,
    }
    print(f"{test_id}: {'PASS' if passed else 'FAIL'}")


os.makedirs("/tmp/nexus_audit", exist_ok=True)

# ===========================
# PHASE 1 — TOOL INVENTORY
# ===========================
print("=== PHASE 1: TOOL INVENTORY ===")
r = nexus_chat(
    "List every tool you have available in STRICT CSV format: "
    "tool_name, category, required_args, optional_args. "
    "One tool per line. No explanation. No preamble. No markdown."
)
results["tool_inventory"] = {"status": "OK", "response": r["response"][:1000]}
print("PHASE1 OK:", r["ok"], "STATUS:", r["status"], "RESPONSE:", r["response"][:500])

# ===========================
# PHASE 2 — FILE SYSTEM
# ===========================
print("\n=== PHASE 2: FILE SYSTEM ===")

a = nexus_chat("Create file /tmp/nexus_audit/test_01.txt with exact content: NEXUS_AUDIT_MARKER_01")
time.sleep(1)
v = nexus_chat("Read /tmp/nexus_audit/test_01.txt exact content")
record("FS-01-CREATE", a, v, "NEXUS_AUDIT_MARKER_01")

a = nexus_chat("Overwrite /tmp/nexus_audit/test_01.txt with exact: NEXUS_AUDIT_MARKER_02")
time.sleep(1)
v = nexus_chat("Read /tmp/nexus_audit/test_01.txt exact content")
record("FS-02-OVERWRITE", a, v, "NEXUS_AUDIT_MARKER_02")

a = nexus_chat("Append LINE_APPENDED to /tmp/nexus_audit/test_01.txt on a new line")
time.sleep(1)
v = nexus_chat("Read /tmp/nexus_audit/test_01.txt every line")
record("FS-03-APPEND", a, v, "LINE_APPENDED")

a = nexus_chat("Create file /tmp/nexus_audit/subdir/nested/deep.txt with content DEEP_MARKER")
time.sleep(1)
v = nexus_chat("Read /tmp/nexus_audit/subdir/nested/deep.txt exact content")
record("FS-04-NESTED", a, v, "DEEP_MARKER")

a = nexus_chat("Delete file /tmp/nexus_audit/test_01.txt")
time.sleep(1)
v = nexus_chat("Try reading /tmp/nexus_audit/test_01.txt, does it exist?")
deleted = any(
    x in v["response"].lower() for x in ["not found", "does not exist", "no such", "error"]
)
results["FS-05-DELETE"] = {"status": "PASS" if deleted else "FAIL", "verify": v["response"][:200]}
print(f"FS-05-DELETE: {'PASS' if deleted else 'FAIL'}")

a = nexus_chat("Create /tmp/nexus_audit/large.py with 200 lines, each line: # Line N")
time.sleep(2)
v = nexus_chat("Count total lines in /tmp/nexus_audit/large.py. Report ONLY the number.")
record("FS-06-LARGE", a, v, "200")

a = nexus_chat(
    "Create /tmp/nexus_audit/unicode.txt with exactly: português: ção\njapanese: 日本語\nemoji: 🔥"
)
time.sleep(1)
v = nexus_chat("Read /tmp/nexus_audit/unicode.txt byte by byte")
record("FS-07-UNICODE", a, v, "português")

fs_pass = sum(1 for k, v in results.items() if k.startswith("FS") and v.get("status") == "PASS")
fs_total = sum(1 for k in results if k.startswith("FS"))
print(f"\nFILE SYSTEM SCORE: {fs_pass}/{fs_total}")

# ===========================
# PHASE 3 — CODE MODIFICATION
# ===========================
print("\n=== PHASE 3: CODE MODIFICATION ===")
nexus_chat(
    "Create /tmp/nexus_audit/hello.py with: def greet(name): return f'Hello {name}'\nif __name__=='__main__': print(greet('Nexus'))"
)
time.sleep(1)

a = nexus_chat("Add function def subtract(a, b): return a - b to /tmp/nexus_audit/hello.py")
time.sleep(1)
v = nexus_chat("Read /tmp/nexus_audit/hello.py, does both greet() and subtract() exist?")
both = "subtract" in v["response"] and "greet" in v["response"]
results["CM-01-ADD-FUNC"] = {"status": "PASS" if both else "FAIL", "verify": v["response"][:300]}
print(f"CM-01-ADD-FUNC: {'PASS' if both else 'FAIL'}")

a = nexus_chat("Modify greet() in /tmp/nexus_audit/hello.py to: def greet(name, title='')")
time.sleep(1)
v = nexus_chat("Read /tmp/nexus_audit/hello.py, show exact signature of greet")
record("CM-02-MODIFY", a, v, "title")

a = nexus_chat("Add 'import os' as FIRST line of /tmp/nexus_audit/hello.py")
time.sleep(1)
v = nexus_chat("Read first line of /tmp/nexus_audit/hello.py exactly")
record("CM-03-IMPORT", a, v, "import os")

a = nexus_chat("In /tmp/nexus_audit/hello.py inside greet() only, replace 'Hello' with 'Hi'")
time.sleep(1)
v = nexus_chat("Read /tmp/nexus_audit/hello.py, what does greet() return?")
record("CM-04-REPLACE", a, v, "Hi")

cm_pass = sum(1 for k, v in results.items() if k.startswith("CM") and v.get("status") == "PASS")
cm_total = sum(1 for k in results if k.startswith("CM"))
print(f"\nCODE MODIFICATION SCORE: {cm_pass}/{cm_total}")

# ===========================
# PHASE 4 — SHELL EXECUTION
# ===========================
print("\n=== PHASE 4: SHELL EXECUTION ===")

a = nexus_chat('Execute: python3 -c "print(EXEC_MARKER_001)"')
record("SH-01-BASIC", a, a, "EXEC_MARKER_001")

a = nexus_chat('Execute: python3 -c "print(2 + 2)"')
record("SH-02-ARITH", a, a, "4")

a = nexus_chat('Execute: python3 -c "import sys; sys.stderr.write(STDERR_MARKER)"')
stderr_ok = "STDERR_MARKER" in a["response"] or "stderr" in a["response"].lower()
results["SH-03-STDERR"] = {"status": "PASS" if stderr_ok else "FAIL", "verify": a["response"][:200]}
print(f"SH-03-STDERR: {'PASS' if stderr_ok else 'FAIL'}")

a = nexus_chat("Execute: python3 -c \"raise ValueError('intentional_error')\" and report exit code")
exit_ok = any(x in a["response"].lower() for x in ["exit", "error", "1", "valueerror"])
results["SH-04-EXIT"] = {"status": "PASS" if exit_ok else "FAIL", "verify": a["response"][:200]}
print(f"SH-04-EXIT: {'PASS' if exit_ok else 'FAIL'}")

nexus_chat(
    "Create /tmp/nexus_audit/test_sample.py with: def test_pass(): assert 1+1==2\ndef test_fail(): assert 1+1==3"
)
time.sleep(1)
a = nexus_chat("Run pytest /tmp/nexus_audit/test_sample.py show full output with pass/fail")
one_pass = "passed" in a["response"].lower()
one_fail = "failed" in a["response"].lower()
results["SH-05-PYTEST"] = {
    "status": "PASS" if (one_pass and one_fail) else "FAIL",
    "verify": a["response"][:300],
}
print(f"SH-05-PYTEST: {'PASS' if (one_pass and one_fail) else 'FAIL'}")

sh_pass = sum(1 for k, v in results.items() if k.startswith("SH") and v.get("status") == "PASS")
sh_total = sum(1 for k in results if k.startswith("SH"))
print(f"\nSHELL SCORE: {sh_pass}/{sh_total}")

# ===========================
# PHASE 5 — FAILURE MODES
# ===========================
print("\n=== PHASE 5: FAILURE MODES ===")

a = nexus_chat("Read file /tmp/nexus_audit/DOES_NOT_EXIST_XYZ_987654.txt")
clean = any(x in a["response"].lower() for x in ["not found", "does not exist", "no such", "error"])
hallucinated = len(a["response"]) > 50 and not clean
results["FM-01-NOT-EXIST"] = {
    "status": "CLEAN_ERROR" if clean else ("HALLUCINATED" if hallucinated else "SILENT_FAILURE"),
    "verify": a["response"][:200],
}
print(f"FM-01-NOT-EXIST: {results['FM-01-NOT-EXIST']['status']}")

a = nexus_chat("Write 'test' to /root/unauthorized/secret.txt")
perm_err = any(
    x in a["response"].lower() for x in ["permission", "denied", "error", "cannot", "failed"]
)
results["FM-02-INVALID-PATH"] = {
    "status": "CLEAN_ERROR" if perm_err else "SILENT_FAILURE",
    "verify": a["response"][:200],
}
print(f"FM-02-INVALID-PATH: {results['FM-02-INVALID-PATH']['status']}")

a = nexus_chat("Create a file with no path and no content specified")
results["FM-03-EMPTY"] = {"status": "OBSERVED", "verify": a["response"][:200]}
print(f"FM-03-EMPTY: {a['response'][:100]}")

nexus_chat("Create /tmp/nexus_audit/real_file.txt with REAL_CONTENT")
time.sleep(1)
a = nexus_chat("Read /tmp/nexus_audit/invented_file_xyz.txt")
invented = "REAL_CONTENT" in a["response"] or (
    len(a["response"]) > 20 and "not found" not in a["response"].lower()
)
results["FM-04-HALLUCINATION"] = {
    "status": "HALLUCINATION_DETECTED" if invented else "CLEAN_ERROR",
    "verify": a["response"][:200],
}
print(f"FM-04-HALLUCINATION: {results['FM-04-HALLUCINATION']['status']}")

# ===========================
# PHASE 6 — SILENT FAILURES
# ===========================
print("\n=== PHASE 6: SILENT FAILURE DETECTION ===")
silent_failures = []

marker = f"SILENT_TEST_{int(time.time())}"
nexus_chat(f"Create /tmp/nexus_audit/silent_test.txt with content: {marker}")
time.sleep(2)
r = nexus_chat("Read /tmp/nexus_audit/silent_test.txt, show exact content")
if marker not in r["response"]:
    silent_failures.append({"test": "Write→Read consistency", "verdict": "SILENT FAILURE"})
    print("SILENT FAILURE: write→read inconsistency")
else:
    print("PASS: write→read consistent")

r = nexus_chat('Execute: python3 -c "print(CAPTURE_TEST_XYZ)"')
if "CAPTURE_TEST_XYZ" not in r["response"]:
    silent_failures.append({"test": "Shell output capture", "verdict": "SILENT FAILURE"})
    print("SILENT FAILURE: shell output not captured")
else:
    print("PASS: shell output captured")

nexus_chat("Create /tmp/nexus_audit/modify_test.py with content: VERSION=1")
time.sleep(1)
nexus_chat("Change /tmp/nexus_audit/modify_test.py content to: VERSION=2")
time.sleep(1)
r = nexus_chat("Read /tmp/nexus_audit/modify_test.py, what is VERSION value?")
if "VERSION=1" in r["response"] or "2" not in r["response"]:
    silent_failures.append({"test": "File modification persistence", "verdict": "SILENT FAILURE"})
    print("SILENT FAILURE: modification not persisted")
else:
    print("PASS: file modification persisted")

print(f"\nSILENT FAILURES DETECTED: {len(silent_failures)}")
for sf in silent_failures:
    print(f"  ⚠ {sf['test']}: {sf['verdict']}")

# ===========================
# FINAL REPORT
# ===========================
print("\n" + "=" * 60)
print("NEXUS IDE TOOL RELIABILITY AUDIT — FINAL REPORT")
print("=" * 60)

categories = {
    "TOOL_INVENTORY": [k for k in results if k in ("tool_inventory",)],
    "FILE_SYSTEM": [k for k in results if k.startswith("FS")],
    "CODE_MODIFICATION": [k for k in results if k.startswith("CM")],
    "SHELL_EXECUTION": [k for k in results if k.startswith("SH")],
    "FAILURE_HANDLING": [k for k in results if k.startswith("FM")],
}

total_pass = 0
total_tests = 0

for cat, keys in categories.items():
    cat_pass = sum(1 for k in keys if results.get(k, {}).get("status") == "PASS")
    cat_total = len(keys)
    total_pass += cat_pass
    total_tests += cat_total
    bar = "█" * cat_pass + "░" * (cat_total - cat_pass)
    print(f"{cat:<25} {cat_pass}/{cat_total}  [{bar}]")

print(f"\nOVERALL SCORE: {total_pass}/{total_tests}")
print(f"RELIABILITY:   {round(total_pass / total_tests * 100) if total_tests > 0 else 0}%")
print(f"\nSILENT FAILURES: {len(silent_failures)}")
for sf in silent_failures:
    print(f"  ⚠ {sf['test']}: {sf['verdict']}")

failures = [(k, v) for k, v in results.items() if v.get("status") == "FAIL"]
print(f"\nCRITICAL FAILURES ({len(failures)}):")
for k, v in failures:
    print(f"  ✗ {k}: {v.get('verify', '')[:100]}")

print("\nSINGLE HIGHEST RISK:")
if silent_failures:
    print(f"  {silent_failures[0]['test']} — {silent_failures[0]['verdict']}")
elif failures:
    print(f"  {failures[0][0]} — tool failed with no recovery")
else:
    print("  No critical failures detected")

print("\nRECOMMENDED IMMEDIATE ACTION:")
if silent_failures:
    print("  Silent failures detected — add post-write read-back verification to execute_tool()")
elif any("CM" in k for k, v in failures):
    print("  Code modification unreliable — implement apply_diff instead of full file overwrite")
elif any("SH" in k for k, v in failures):
    print("  Shell output not captured — fix stdout/stderr piping in shell_runner.py")
else:
    print("  Run extended stress test with 50+ sequential tool calls to find collapse point")

# Save results
with open(RESULTS_PATH, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nResults saved to: {RESULTS_PATH}")
