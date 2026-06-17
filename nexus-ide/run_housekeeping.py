"""
Run ALL housekeeping tasks:
  Task A: Validate syntax of all modified files
  Task B: Delete original verify/benchmark files after copying to scripts/
  Task C: Delete stale standalone audit/reliability files
"""

import os
import sys
import shutil

ROOT = r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide"

# ── Task A: Validate syntax ──────────────────────────────────────────────
print("=" * 60)
print("  TASK A: VALIDATE SYNTAX")
print("=" * 60)

FILES = [
    "backend/agents/base.py",
    "backend/tools/embeddings.py",
    "backend/tools/registry.py",
    "backend/token_management.py",
    "backend/cache/__init__.py",
    "backend/cache/semantic_cache.py",
    "backend/cache/tool_result_cache.py",
    "backend/cache/vector_store.py",
    "backend/orchestrator/routing_config.py",
    "backend/observability/metrics.py",
    "backend/tests/test_improvements.py",
]

import ast

errors = []

for rel_path in FILES:
    full_path = os.path.join(ROOT, rel_path)
    if not os.path.exists(full_path):
        errors.append(f"NOT FOUND: {rel_path}")
        print(f"  ⚠️  {rel_path} — NOT FOUND")
        continue
    try:
        with open(full_path, encoding="utf-8") as f:
            source = f.read()
        ast.parse(source)
        print(f"  ✅ {rel_path}")
    except SyntaxError as e:
        errors.append(f"SYNTAX ERROR: {rel_path}:{e.lineno}: {e.msg}")
        print(f"  ❌ {rel_path}:{e.lineno}: {e.msg}")

if errors:
    print(f"\n⚠️  {len(errors)} file(s) with errors:")
    for e in errors:
        print(f"  {e}")
else:
    print(f"\n✅ ALL {len(FILES)} files have valid Python syntax")

# ── Task B: Delete originals after copy ──────────────────────────────────
print(f"\n{'=' * 60}")
print("  TASK B: DELETE ORIGINAL FILES (ALREADY COPIED TO scripts/)")
print("=" * 60)

original_files = [
    ("verify_improvements.py", "scripts/verify_improvements.py"),
    ("benchmark_improvements.py", "scripts/benchmark_improvements.py"),
    ("delete_files.py", "scripts/delete_files.py"),
]

for src_name, dst_rel in original_files:
    src = os.path.join(ROOT, src_name)
    dst = os.path.join(ROOT, dst_rel)
    if os.path.exists(src):
        if os.path.exists(dst):
            os.remove(src)
            print(f"  ✅ {src_name} → deleted (copy exists at {dst_rel})")
        else:
            print(f"  ⚠️  {src_name} exists but copy not found at {dst_rel} — skipping delete")
    else:
        print(f"  ⚠️  {src_name} — not found, nothing to delete")

# ── Task C: Delete stale standalone files ────────────────────────────────
print(f"\n{'=' * 60}")
print("  TASK C: DELETE STALE STANDALONE FILES")
print("=" * 60)

stale_files = [
    "audit_report.txt",
    "audit_finalize.py",
    "audit_phase1.py",
    "run_audit.py",
    "run_audit_post_fix.py",
    "reliability_audit.py",
    "reliability_audit_results.json",
    "backend\\_verify_workspace_security.py",
]

for rel_path in stale_files:
    full_path = os.path.join(ROOT, rel_path)
    if os.path.exists(full_path):
        os.remove(full_path)
        print(f"  ✅ {rel_path} — deleted")
    else:
        print(f"  ⚠️  {rel_path} — not found, nothing to delete")

# ── Summary ──────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print("  HOUSKEEPING COMPLETE")
print("=" * 60)
print("\nRun `python validate_syntax.py` to re-check syntax.")
print("Run `python run_housekeeping.py` to repeat all tasks.")
