"""Profile startup time of the NEXUS IDE backend."""
from __future__ import annotations

import sys
import time

def measure_import(module_name: str) -> float:
    """Measure time to import a module."""
    start = time.perf_counter()
    try:
        __import__(module_name)
    except Exception as exc:
        print(f"  ERROR importing {module_name}: {exc}")
    return time.perf_counter() - start

def main() -> None:
    print("=" * 60)
    print("NEXUS IDE Startup Profiler")
    print("=" * 60)

    total_start = time.perf_counter()

    # Measure key components
    components = [
        ("backend.config.settings", "Settings + YAML loading"),
        ("backend.tools.ollama_client", "Ollama client (httpx)"),
        ("backend.observability.metrics_collector", "Metrics collector (psutil)"),
        ("backend.persistence.db", "Database layer"),
        ("backend.tools.registry", "Tool registry"),
        ("backend.agents.base", "Agent base (ReAct)"),
        ("backend.orchestrator.dependency_graph", "Dependency graph"),
        ("backend.orchestrator.engine", "Orchestration engine"),
        ("backend.orchestrator.router", "Agent router"),
        ("backend.orchestrator.smart_router", "Smart tier router"),
        ("backend.orchestrator.registry", "Agent registry"),
        ("backend.orchestrator.main", "FastAPI app (full startup)"),
    ]

    for module, desc in components:
        elapsed = measure_import(module)
        print(f"  {elapsed:.3f}s  |  {desc}  ({module})")

    total = time.perf_counter() - total_start
    print(f"\n  TOTAL sequential import time: {total:.3f}s")
    print("=" * 60)

    # Measure init_db
    print("\n--- init_db() ---")
    from backend.persistence.db import init_db
    t0 = time.perf_counter()
    init_db()
    t1 = time.perf_counter()
    print(f"  init_db(): {t1 - t0:.3f}s")

    # Measure build_default_registry
    print("\n--- build_default_registry() ---")
    from backend.orchestrator.registry import build_default_registry
    t0 = time.perf_counter()
    reg = build_default_registry()
    t1 = time.perf_counter()
    print(f"  build_default_registry(): {t1 - t0:.3f}s  ({len(reg)} agents)")

    # Measure create_llm_client
    print("\n--- create_llm_client() ---")
    from backend.llm.factory import create_llm_client
    t0 = time.perf_counter()
    try:
        client = create_llm_client()
        t1 = time.perf_counter()
        print(f"  create_llm_client(): {t1 - t0:.3f}s")
    except Exception as exc:
        t1 = time.perf_counter()
        print(f"  create_llm_client(): {t1 - t0:.3f}s  (error: {exc})")

    # Measure routing decisions
    print("\n--- Routing decisions (heuristic, no LLM) ---")
    from backend.orchestrator.router import fast_route
    t0 = time.perf_counter()
    for _ in range(1000):
        fast_route("write a function to sort a list")
    t1 = time.perf_counter()
    print(f"  fast_route x1000: {t1 - t0:.3f}s  ({(t1 - t0) * 1000:.3f}ms each)")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
