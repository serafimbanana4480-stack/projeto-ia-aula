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
    h = {"Authorization": "Bearer " + tok(), "Content-Type": "application/json"}
    r = requests.post(
        f"{NEXUS}/api/chat",
        headers=h,
        json={"message": msg, "mode": mode, "session_id": f"s{int(time.time() * 1000)}"},
        timeout=25,
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
os.makedirs("/tmp/nexus_audit", exist_ok=True)

print("=== PHASE 1 ===")
r = chat("List tools in CSV: name,category,req_args,opt_args")
results["tool_inventory"] = {"status": "OK" if r["ok"] else "FAIL", "response": r["response"][:500]}
print("OK:", r["ok"], "STATUS:", r["status"])

print("\n=== PHASE 2 ===")


def rec(tid, a, v, exp):
    ok = exp.lower() in v["response"].lower()
    results[tid] = {"status": "PASS" if ok else "FAIL", "verify": v["response"][:200]}
    print(f"{tid}: {'PASS' if ok else 'FAIL'}")


a = chat("Create /tmp/nexus_audit/test_01.txt with exactly: NEXUS_AUDIT_MARKER_01")
time.sleep(1)
v = chat("Read /tmp/nexus_audit/test_01.txt exact content")
rec("FS-01", a, v, "NEXUS_AUDIT_MARKER_01")

a = chat("Overwrite /tmp/nexus_audit/test_01.txt with exactly: NEXUS_AUDIT_MARKER_02")
time.sleep(1)
v = chat("Read /tmp/nexus_audit/test_01.txt exact content")
rec("FS-02", a, v, "NEXUS_AUDIT_MARKER_02")

a = chat("Append LINE_APPENDED to /tmp/nexus_audit/test_01.txt on new line")
time.sleep(1)
v = chat("Read /tmp/nexus_audit/test_01.txt every line")
rec("FS-03", a, v, "LINE_APPENDED")

a = chat("Create /tmp/nexus_audit/subdir/nested/deep.txt with DEEP_MARKER")
time.sleep(1)
v = chat("Read /tmp/nexus_audit/subdir/nested/deep.txt")
rec("FS-04", a, v, "DEEP_MARKER")

a = chat("Delete /tmp/nexus_audit/test_01.txt")
time.sleep(1)
v = chat("Read /tmp/nexus_audit/test_01.txt")
deleted = any(
    x in v["response"].lower() for x in ["not found", "does not exist", "no such", "error"]
)
results["FS-05"] = {"status": "PASS" if deleted else "FAIL", "verify": v["response"][:200]}
print(f"FS-05: {'PASS' if deleted else 'FAIL'}")

a = chat("Create /tmp/nexus_audit/large.py with 200 lines: # Line N")
time.sleep(2)
v = chat("Count lines in /tmp/nexus_audit/large.py. Report ONLY number.")
rec("FS-06", a, v, "200")

a = chat("Create /tmp/nexus_audit/unicode.txt with: portugues: cao\njapanese: nihongo\nemoji: FIRE")
time.sleep(1)
v = chat("Read /tmp/nexus_audit/unicode.txt")
rec("FS-07", a, v, "portugues")

fs_pass = sum(1 for k, v in results.items() if k.startswith("FS") and v.get("status") == "PASS")
fs_total = sum(1 for k in results if k.startswith("FS"))
print(f"\nFILE SYSTEM SCORE: {fs_pass}/{fs_total}")

print("\n=== PHASE 3 ===")
chat(
    "Create /tmp/nexus_audit/hello.py with def greet(name): return f'Hello {name}'\\nif __name__=='__main__': print(greet('Nexus'))"
)
time.sleep(1)

a = chat("Add def subtract(a, b): return a - b to /tmp/nexus_audit/hello.py")
time.sleep(1)
v = chat("Read /tmp/nexus_audit/hello.py")
both = "subtract" in v["response"] and "greet" in v["response"]
results["CM-01"] = {"status": "PASS" if both else "FAIL", "verify": v["response"][:300]}
print(f"CM-01: {'PASS' if both else 'FAIL'}")

a = chat("Modify greet in /tmp/nexus_audit/hello.py to def greet(name, title='')")
time.sleep(1)
v = chat("Read /tmp/nexus_audit/hello.py greet signature")
rec("CM-02", a, v, "title")

a = chat("Add import os as FIRST line of /tmp/nexus_audit/hello.py")
time.sleep(1)
v = chat("Read first line of /tmp/nexus_audit/hello.py")
rec("CM-03", a, v, "import os")

a = chat("In /tmp/nexus_audit/hello.py greet function, replace Hello with Hi")
time.sleep(1)
v = chat("Read /tmp/nexus_audit/hello.py")
rec("CM-04", a, v, "Hi")

cm_pass = sum(1 for k, v in results.items() if k.startswith("CM") and v.get("status") == "PASS")
cm_total = sum(1 for k in results if k.startswith("CM"))
print(f"\nCODE MODIFICATION SCORE: {cm_pass}/{cm_total}")

print("\n=== PHASE 4 ===")
a = chat('Execute python3 -c "print(EXEC_MARKER_001)"')
rec("SH-01", a, a, "EXEC_MARKER_001")

a = chat('Execute python3 -c "print(2+2)"')
rec("SH-02", a, a, "4")

a = chat('Execute python3 -c "import sys; sys.stderr.write(STDERR_MARKER)"')
stderr_ok = "STDERR_MARKER" in a["response"] or "stderr" in a["response"].lower()
results["SH-03"] = {"status": "PASS" if stderr_ok else "FAIL", "verify": a["response"][:200]}
print(f"SH-03: {'PASS' if stderr_ok else 'FAIL'}")

a = chat('Execute python3 -c "raise ValueError( intentional_error )" report exit code')
exit_ok = any(x in a["response"].lower() for x in ["exit", "error", "1", "valueerror"])
results["SH-04"] = {"status": "PASS" if exit_ok else "FAIL", "verify": a["response"][:200]}
print(f"SH-04: {'PASS' if exit_ok else 'FAIL'}")

chat(
    "Create /tmp/nexus_audit/test_sample.py with def test_pass(): assert 1+1==2\\ndef test_fail(): assert 1+1==3"
)
time.sleep(1)
a = chat("Run pytest /tmp/nexus_audit/test_sample.py full output")
pp = "passed" in a["response"].lower()
pf = "failed" in a["response"].lower()
results["SH-05"] = {"status": "PASS" if (pp and pf) else "FAIL", "verify": a["response"][:300]}
print(f"SH-05: {'PASS' if (pp and pf) else 'FAIL'}")

sh_pass = sum(1 for k, v in results.items() if k.startswith("SH") and v.get("status") == "PASS")
sh_total = sum(1 for k in results if k.startswith("SH"))
print(f"\nSHELL SCORE: {sh_pass}/{sh_total}")

print("\n=== PHASE 5 ===")
a = chat("Read /tmp/nexus_audit/DOES_NOT_EXIST_XYZ.txt")
clean = any(x in a["response"].lower() for x in ["not found", "does not exist", "no such", "error"])
results["FM-01"] = {
    "status": "CLEAN_ERROR" if clean else "SILENT_FAILURE",
    "verify": a["response"][:200],
}
print(f"FM-01: {results['FM-01']['status']}")

a = chat("Write test to /root/unauthorized/secret.txt")
perm = any(
    x in a["response"].lower() for x in ["permission", "denied", "error", "cannot", "failed"]
)
results["FM-02"] = {
    "status": "CLEAN_ERROR" if perm else "SILENT_FAILURE",
    "verify": a["response"][:200],
}
print(f"FM-02: {results['FM-02']['status']}")

a = chat("Create file with no path and no content specified")
results["FM-03"] = {"status": "OBSERVED", "verify": a["response"][:200]}
print(f"FM-03: {a['response'][:80]}")

chat("Create /tmp/nexus_audit/real_file.txt with REAL_CONTENT")
time.sleep(1)
a = chat("Read /tmp/nexus_audit/invented_file_xyz.txt")
inv = "REAL_CONTENT" in a["response"] or (
    len(a["response"]) > 20 and "not found" not in a["response"].lower()
)
results["FM-04"] = {
    "status": "HALLUCINATION_DETECTED" if inv else "CLEAN_ERROR",
    "verify": a["response"][:200],
}
print(f"FM-04: {results['FM-04']['status']}")

print("\n=== PHASE 6 ===")
silent = []
marker = "SILENT_" + str(int(time.time()))
chat("Create /tmp/nexus_audit/silent_test.txt with " + marker)
time.sleep(2)
r = chat("Read /tmp/nexus_audit/silent_test.txt exact")
if marker not in r["response"]:
    silent.append({"test": "Write->Read", "verdict": "SILENT FAILURE"})
    print("SILENT: write->read")
else:
    print("PASS: write->read")

r = chat('Execute python3 -c "print(CAPTURE_TEST_XYZ)"')
if "CAPTURE_TEST_XYZ" not in r["response"]:
    silent.append({"test": "Shell capture", "verdict": "SILENT FAILURE"})
    print("SILENT: shell capture")
else:
    print("PASS: shell capture")

chat("Create /tmp/nexus_audit/modify_test.py with VERSION=1")
time.sleep(1)
chat("Change /tmp/nexus_audit/modify_test.py to VERSION=2")
time.sleep(1)
r = chat("Read /tmp/nexus_audit/modify_test.py")
if "VERSION=1" in r["response"] or "2" not in r["response"]:
    silent.append({"test": "Modify persist", "verdict": "SILENT FAILURE"})
    print("SILENT: modify persist")
else:
    print("PASS: modify persist")

print("\n" + "=" * 60)
print("FINAL REPORT")
print("=" * 60)
cats = {
    "FILE_SYSTEM": [k for k in results if k.startswith("FS")],
    "CODE_MOD": [k for k in results if k.startswith("CM")],
    "SHELL": [k for k in results if k.startswith("SH")],
    "FAILURES": [k for k in results if k.startswith("FM")],
}
tp = tt = 0
for c, ks in cats.items():
    cp = sum(1 for k in ks if results.get(k, {}).get("status") == "PASS")
    ct = len(ks)
    tp += cp
    tt += ct
    print(f"{c:<15} {cp}/{ct}")
print(f"TOTAL {tp}/{tt} ({round(tp / tt * 100) if tt else 0}%)")
print(f"SILENT FAILURES: {len(silent)}")
for s in silent:
    print(" ", s["test"], "-", s["verdict"])
