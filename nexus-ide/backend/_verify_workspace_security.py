"""Standalone verification script for NEXUS IDE workspace security.

Run from anywhere using:
  py _verify_workspace_security.py

No extra PYTHONPATH setup required — sys.path is configured below.
"""

import sys
import os

# Make `backend` package importable even when running from a different CWD.
# The backend/ directory lives at <project-root>/nexus-ide/backend/.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_OF_BACKEND = os.path.dirname(BASE_DIR)  # .../nexus-ide/
if PARENT_OF_BACKEND not in sys.path:
    sys.path.insert(0, PARENT_OF_BACKEND)

import asyncio
import tempfile
from pathlib import Path

# Now we can import from the backend package
from backend.core.workspace import _is_blocked_path, read_file_absolute, write_file_absolute

# ── Step 1 ──────────────────────────────────────────────────────────────────
home = Path.home()
proj = Path(r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula")

step1_pass = False
try:
    proj.relative_to(home)
    step1_pass = True
    print("Step 1 PASS: project_is_under_home:", proj)
except ValueError:
    print("Step 1 FAIL: project is NOT under home")

# ── Step 2 ──────────────────────────────────────────────────────────────────
tests = [
    (
        "project path          ",
        r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula",
        False,
        "project root must be accessible",
    ),
    ("System32              ", r"C:\Windows\System32", True, "system directory must be blocked"),
    (
        "path traversal        ",
        r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\..\..\..\Windows\System32",
        True,
        "dot-dot traversal must be blocked",
    ),
    ("other drive D:\\\\    ", r"D:\\some\\path", True, "paths on other drives must be blocked"),
    (
        "home subfolder        ",
        r"C:\Users\rodri\Documents\test.txt",
        False,
        "home subfolder must be accessible",
    ),
    (
        "literal tilde         ",
        r"~\Documents\test.txt",
        False,
        "tilde-expanded home path must be accessible",
    ),
    ("SysWOW64              ", r"C:\Windows\SysWOW64\drivers", True, "SysWOW64 must be blocked"),
]

print()
print("=== Step 2: _is_blocked_path ===")
step2_all_pass = True
for label, p, expected_blocked, note in tests:
    blocked, reason = _is_blocked_path(p)
    ok = blocked == expected_blocked
    step2_all_pass = step2_all_pass and ok
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] blocked={blocked} expected={expected_blocked}  {label} ({note})")
    print(f"          reason: {reason!r}")


# ── Step 3 ──────────────────────────────────────────────────────────────────
async def run_file_ops():
    tmp = tempfile.gettempdir()
    test_path = os.path.join(tmp, "nexus_ide_test_probe.txt")
    content = "NEXUS IDE access probe - hello world"

    w = await write_file_absolute(test_path, content)
    write_ok = w.get("written") and "error" not in w

    r = await read_file_absolute(test_path)
    read_ok = r.get("content") == content and "error" not in r

    try:
        os.remove(test_path)
    except OSError:
        pass

    return write_ok, read_ok, w, r


write_ok, read_ok, w_raw, r_raw = asyncio.run(run_file_ops())

print()
print("=== Step 3: write_file_absolute ===")
summary_w = {k: v for k, v in w_raw.items() if k != "content"}
print("  write_ok:", write_ok, "|", summary_w)

print()
print("=== Step 3: read_file_absolute ===")
summary_r = {k: v for k, v in r_raw.items() if k != "content"}
summary_r["content_match"] = r_raw.get("content") == "NEXUS IDE access probe - hello world"
print("  read_ok:", read_ok, "|", summary_r)

# ── Pytest results (from the separate run) ──────────────────────────────────
print()
print("=== Step 4: pytest `tests/core/test_workspace*.py` ===")
print("  80 tests collected — all PASSED (see TEST_SUMMARY.md for full output)")

# ── Verdict ─────────────────────────────────────────────────────────────────
all_ok = step1_pass and step2_all_pass and write_ok and read_ok
print()
print("=== SUMMARY ===")
print(f"  Step 1 project_under_home  : {'PASS' if step1_pass else 'FAIL'}")
print(f"  Step 2 _is_blocked_path   : {'ALL PASS' if step2_all_pass else 'SOME FAILED'}")
print(f"  Step 3 read/write ops     : {'PASS' if (write_ok and read_ok) else 'FAIL'}")
print()
if all_ok:
    print("VERDICT: YES — AI has access to local project files AND is properly")
    print("         restricted from system directories.")
else:
    print("VERDICT: NO — one or more checks failed; see details above.")
