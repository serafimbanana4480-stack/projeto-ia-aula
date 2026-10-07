"""Integration smoke test for NEXUS IDE."""
import backend.tools.file_ops
import backend.tools.git_tools
import backend.tools.shell_runner
from backend.tools.registry import _registry, get_tool

print("Tools registered:", len(_registry))
for name in ["read_file", "write_file", "run_shell", "git_status", "list_files"]:
    t = get_tool(name)
    status = "OK" if t and t.handler else "MISSING"
    print(f"  {name}: {status}")

from backend.auth.service import AuthService
s = AuthService()
tok = s.create_access_token({"user": "test"})
print("JWT token created, len:", len(tok))

from backend.mcp.nexus_server import _SAFE_EXACT_TOOLS
print("MCP safe tools:", len(_SAFE_EXACT_TOOLS))

from backend.memory.advanced_memory import AdvancedMemorySystem
print("Memory system OK")

from backend.persistence.db import log_tool_execution
print("Persistence OK")

from backend.runtime.triage import triage_request
d = triage_request("hello world")
print("Triage conversational:", d.request_class.value)
d2 = triage_request("cria um plano para refactorar o modulo de auth e depois executa")
print("Triage planned:", d2.request_class.value)

print("\nALL SMOKE TESTS PASSED")