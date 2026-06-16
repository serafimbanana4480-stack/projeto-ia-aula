import json, sys, time

# Directly insert argparse for win32 argv compatibility
sys.path.insert(0, ".")

# Reconstruct results from phases 1-5 that already ran successfully
results = {}
results["FS-01-CREATE"] = {"status": "FAIL", "verify": "", "expected": "NEXUS_AUDIT_MARKER_01"}
results["FS-02-OVERWRITE"] = {"status": "FAIL", "verify": "", "expected": "NEXUS_AUDIT_MARKER_02"}
results["FS-03-APPEND"] = {"status": "FAIL", "verify": "", "expected": "LINE_APPENDED"}
results["FS-04-NESTED"] = {"status": "FAIL", "verify": "", "expected": "DEEP_MARKER"}
results["FS-05-DELETE"] = {"status": "PASS", "verify": "file deleted", "expected": ""}
results["FS-06-LARGE"] = {"status": "PASS", "verify": "200 lines", "expected": "200"}
results["FS-07-UNICODE"] = {"status": "FAIL", "verify": "", "expected": "portugu\u00eas"}
results["CM-01-ADD-FUNC"] = {"status": "FAIL", "verify": "", "expected": ""}
results["CM-02-MODIFY"] = {"status": "PASS", "verify": "title parameter", "expected": "title"}
results["CM-03-IMPORT"] = {"status": "FAIL", "verify": "", "expected": "import os"}
results["CM-04-REPLACE"] = {"status": "PASS", "verify": "Hi", "expected": "Hi"}
results["SH-01-BASIC"] = {"status": "FAIL", "verify": "", "expected": "EXEC_MARKER_001"}
results["SH-02-ARITH"] = {"status": "PASS", "verify": "4", "expected": "4"}
results["SH-03-STDERR"] = {"status": "FAIL", "verify": "", "expected": ""}
results["SH-04-EXIT"] = {"status": "PASS", "verify": "error/exit reported", "expected": ""}
results["SH-05-PYTEST"] = {"status": "FAIL", "verify": "", "expected": "pass/fail both"}
results["FM-01-NOT-EXIST"] = {"status": "CLEAN_ERROR", "verify": "not found", "expected": ""}
results["FM-02-INVALID-PATH"] = {
    "status": "CLEAN_ERROR",
    "verify": "permission denied",
    "expected": "",
}
results["FM-03-EMPTY"] = {"status": "OBSERVED", "verify": "routing", "expected": ""}
results["FM-04-HALLUCINATION"] = {"status": "CLEAN_ERROR", "verify": "not found", "expected": ""}

import requests, json, time, os, sys, jwt

os.chdir(r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide")
NEXUS = "http://localhost:8000"
SECRET = "4hD3jNzDt0mcH1n9jGDluQW5kCIkFs5b7hrdtDnJDE0"


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


silent_failures = []

# Test 1: Write -> Read consistency
os.makedirs("/tmp/nexus_audit", exist_ok=True)
marker = f"SILENT_TEST_{int(time.time())}"
r = chat(f"Create /tmp/nexus_audit/silent_test.txt with content: {marker}")
print(f"SILENT_WRITE_OK: {r['ok']}")
time.sleep(2)
r = chat("Read /tmp/nexus_audit/silent_test.txt, show exact content")
print(f"SILENT_READ_OK: {r['ok']}")
if marker not in r["response"]:
    silent_failures.append(
        {
            "test": "Write->Read consistency",
            "verdict": "SILENT FAILURE",
            "read_back": r["response"][:150],
        }
    )
    print("SILENT FAILURE: write->read inconsistency")
else:
    print("PASS: write->read consistent")

# Test 2: Shell output capture
r = chat('Execute: python3 -c "print(CAPTURE_TEST_XYZ)"')
print(f"SHELL_CAPTURE_OK: {r['ok']}")
if "CAPTURE_TEST_XYZ" not in r["response"]:
    silent_failures.append(
        {"test": "Shell output capture", "verdict": "SILENT FAILURE", "got": r["response"][:150]}
    )
    print("SILENT FAILURE: shell output not captured")
else:
    print("PASS: shell output captured")

# Test 3: File modification persistence
chat("Create /tmp/nexus_audit/modify_test.py with content: VERSION=1")
time.sleep(1)
chat("Change /tmp/nexus_audit/modify_test.py to: VERSION=2")
time.sleep(1)
r = chat("Read /tmp/nexus_audit/modify_test.py, what is VERSION value?")
print(f"MODIFY_READ_OK: {r['ok']}")
if "VERSION=1" in r["response"] or "2" not in r["response"]:
    silent_failures.append(
        {
            "test": "File modification persistence",
            "verdict": "SILENT FAILURE",
            "got": r["response"][:150],
        }
    )
    print("SILENT FAILURE: modification not persisted")
else:
    print("PASS: file modification persisted")

# ===== FINAL REPORT =====
print("\n" + "=" * 60)
print("NEXUS IDE TOOL RELIABILITY AUDIT - FINAL REPORT")
print("=" * 60)

categories = {
    "TOOL_INVENTORY": ["tool_inventory"],
    "FILE_SYSTEM": [k for k in results if k.startswith("FS")],
    "CODE_MODIFICATION": [k for k in results if k.startswith("CM")],
    "SHELL_EXECUTION": [k for k in results if k.startswith("SH")],
    "FAILURE_HANDLING": [k for k in results if k.startswith("FM")],
}
total_pass = 0
total_tests = 0

scoreboard = {
    "FS-01-CREATE": "FAIL",
    "FS-02-OVERWRITE": "FAIL",
    "FS-03-APPEND": "FAIL",
    "FS-04-NESTED": "FAIL",
    "FS-05-DELETE": "PASS",
    "FS-06-LARGE": "PASS",
    "FS-07-UNICODE": "FAIL",
    "CM-01-ADD-FUNC": "FAIL",
    "CM-02-MODIFY": "PASS",
    "CM-03-IMPORT": "FAIL",
    "CM-04-REPLACE": "PASS",
    "SH-01-BASIC": "FAIL",
    "SH-02-ARITH": "PASS",
    "SH-03-STDERR": "FAIL",
    "SH-04-EXIT": "PASS",
    "SH-05-PYTEST": "FAIL",
    "FM-01-NOT-EXIST": "CLEAN_ERROR",
    "FM-02-INVALID-PATH": "CLEAN_ERROR",
    "FM-03-EMPTY": "OBSERVED",
    "FM-04-HALLUCINATION": "CLEAN_ERROR",
}

for cat, keys in categories.items():
    cat_pass = sum(1 for k in keys if scoreboard.get(k) == "PASS")
    cat_total = len(keys)
    total_pass += cat_pass
    total_tests += cat_total
    bar = "=" * cat_pass + " " * (cat_total - cat_pass)
    print(f"{cat:<25} {cat_pass}/{cat_total}  [{bar}]")

print(f"\nOVERALL SCORE: {total_pass}/{total_tests}")
print(f"RELIABILITY:   {round(total_pass / total_tests * 100) if total_tests > 0 else 0}%")

print(f"\nSILENT FAILURES: {len(silent_failures)}")
for sf in silent_failures:
    print(f"  - {sf['test']}: {sf['verdict']}")
    print(f"    read_back/context: {sf.get('read_back', sf.get('got', ''))[:120]}")

failures = [(k, v) for k, v in scoreboard.items() if v == "FAIL"]
print(f"\nCRITICAL FAILURES ({len(failures)}):")
for k, v in failures:
    print(f"  X {k}: {v}")

print("\nSINGLE HIGHEST RISK:")
if silent_failures:
    print(f"  {silent_failures[0]['test']} -- {silent_failures[0]['verdict']}")
elif failures:
    print(f"  {failures[0][0]} -- tool failed with no recovery")
else:
    print("  No critical failures detected")

print("\nRECOMMENDED IMMEDIATE ACTION:")
if silent_failures:
    print("  Silent failures detected -- add post-write read-back verification to execute_tool()")
elif any("CM" in k for k, v in scoreboard.items() if v == "FAIL"):
    print("  Code modification unreliable -- implement apply_diff instead of full file overwrite")
elif any("SH" in k for k, v in scoreboard.items() if v == "FAIL"):
    print("  Shell output not captured -- fix stdout/stderr piping in shell_runner.py")
else:
    print("  Run extended stress test with 50+ sequential tool calls to find collapse point")

report_path = (
    r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide\audit_report.txt"
)
with open(report_path, "w", encoding="utf-8") as f:
    f.write(
        f"OVERALL: {total_pass}/{total_tests} ({round(total_pass / total_tests * 100) if total_tests > 0 else 0}%)\n"
    )
    f.write(f"SILENT_FAILURES: {len(silent_failures)}\n")
    for k, v in scoreboard.items():
        f.write(f"{k}: {v}\n")

print(f"\nReport saved: {report_path}")
