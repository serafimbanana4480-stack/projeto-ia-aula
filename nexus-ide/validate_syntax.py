"""Validate Python syntax of all modified/new files."""
import ast
import sys
from pathlib import Path

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

root = Path(r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide")
errors = []

for rel_path in FILES:
    full_path = root / rel_path
    if not full_path.exists():
        errors.append(f"❌ NOT FOUND: {rel_path}")
        continue
    try:
        source = full_path.read_text(encoding="utf-8")
        ast.parse(source)
        print(f"✅ {rel_path}")
    except SyntaxError as e:
        errors.append(f"❌ SYNTAX ERROR: {rel_path}:{e.lineno}: {e.msg}")
        print(f"❌ {rel_path}:{e.lineno}: {e.msg}")

if errors:
    print(f"\n⚠️ {len(errors)} file(s) with errors:")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print(f"\n✅ ALL {len(FILES)} files have valid Python syntax")
