"""Performance benchmark script for NEXUS IDE caching & optimization improvements.

Run with: python benchmark_performance.py
"""

from __future__ import annotations

import time
import statistics


def benchmark_fast_route():
    from backend.orchestrator.router import fast_route

    queries = [
        "fix the bug in my code",
        "write a function to sort a list",
        "optimize performance of this query",
        "design the architecture for a microservice",
        "document this API endpoint",
    ]

    # Warm cache
    for q in queries:
        fast_route(q)

    times = []
    for _ in range(1000):
        for q in queries:
            t0 = time.perf_counter()
            fast_route(q)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1e6)  # microseconds

    avg = statistics.mean(times)
    p99 = sorted(times)[int(len(times) * 0.99)]
    print(f"fast_route (cached): avg={avg:.2f}µs  p99={p99:.2f}µs")


def benchmark_settings_load():
    from backend.config.settings import get_settings, load_models_config

    times = []
    for _ in range(1000):
        t0 = time.perf_counter()
        get_settings()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1e6)

    avg = statistics.mean(times)
    p99 = sorted(times)[int(len(times) * 0.99)]
    print(f"get_settings (cached): avg={avg:.2f}µs  p99={p99:.2f}µs")

    times2 = []
    for _ in range(1000):
        t0 = time.perf_counter()
        load_models_config()
        t1 = time.perf_counter()
        times2.append((t1 - t0) * 1e6)

    avg2 = statistics.mean(times2)
    p99_2 = sorted(times2)[int(len(times2) * 0.99)]
    print(f"load_models_config (cached): avg={avg2:.2f}µs  p99={p99_2:.2f}µs")


def benchmark_react_context_trim():
    from backend.agents.base import AgentBase

    class DummyAgent(AgentBase):
        name = "DUMMY"
        model_key = "nano"
        prompt_file = "router"

        async def _execute(self, request):
            yield "ok"

    agent = DummyAgent()
    big_context = "\n".join([f"Tool tool_{i} returned: {'x' * 400}" for i in range(60)])

    times = []
    for _ in range(100):
        t0 = time.perf_counter()
        agent._trim_context(big_context, 10)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1e3)  # milliseconds

    avg = statistics.mean(times)
    p99 = sorted(times)[int(len(times) * 0.99)]
    print(f"_trim_context: avg={avg:.3f}ms  p99={p99:.3f}ms")


def benchmark_registry_lazy():
    from backend.orchestrator.registry import build_default_registry, resolve

    t0 = time.perf_counter()
    reg = build_default_registry()
    t1 = time.perf_counter()
    print(f"build_default_registry (lazy proxy): {(t1-t0)*1e3:.3f}ms")

    t0 = time.perf_counter()
    agent = resolve(reg, "CODER")
    t1 = time.perf_counter()
    print(f"resolve CODER (first instantiation): {(t1-t0)*1e3:.3f}ms")


def main() -> None:
    print("=" * 60)
    print("NEXUS IDE Performance Benchmarks")
    print("=" * 60)
    benchmark_fast_route()
    benchmark_settings_load()
    benchmark_react_context_trim()
    benchmark_registry_lazy()
    print("=" * 60)


if __name__ == "__main__":
    main()
