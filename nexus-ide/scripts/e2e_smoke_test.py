"""End-to-end smoke test: real prompt against the local airllm model stack.

Verifies that:
1. Model aliases resolve to local file paths (no Hub download).
2. The airllm provider can actually generate text on this CPU machine.
3. Streaming works.
4. Embeddings work with the local sentence-transformers model.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_model_resolution() -> bool:
    section("Test 1: Model alias resolution (registry + local path)")
    from backend.llm.airllm_provider import (
        DEFAULT_MODEL_REGISTRY,
        _resolve_local_path,
        _resolve_model_id,
    )

    # Expected: ALL these aliases should have a local copy on disk
    aliases_to_test = [
        "qwen2.5:0.5b",
        "qwen2.5:1.5b",
        "qwen2.5-coder:1.5b",
        "deepseek-r1:1.5b",
        "nomic-embed-text",
    ]
    ok = True
    for alias in aliases_to_test:
        resolved = _resolve_model_id(alias)
        local = _resolve_local_path(DEFAULT_MODEL_REGISTRY.get(alias, alias))
        local_marker = "(LOCAL)" if local else "(HUB ONLY)"
        print(f"  {alias:<25} -> {resolved[:60]:<60} {local_marker}")
        if not local:
            print(f"  WARNING: {alias} expected to have a local copy")
            ok = False
    return ok


async def test_chat() -> tuple[bool, float, str]:
    section("Test 2: Real chat with Qwen2.5-1.5B-Instruct (CPU)")
    from backend.llm.airllm_provider import AirLLMProvider

    provider = AirLLMProvider(device="cpu")
    prompt = "Q: What is 2+2? A:"
    print(f"  Prompt: {prompt!r}")
    print("  Streaming response:")
    print("  ", end="", flush=True)
    tokens: list[str] = []
    t0 = time.time()
    try:
        async for tok in provider.chat_stream(
            "qwen2.5:1.5b",
            [{"role": "user", "content": "What is 2+2? Answer in one short sentence."}],
            options={"max_tokens": 30, "temperature": 0.3, "timeout_seconds": 600},
        ):
            tokens.append(tok)
            sys.stdout.write(tok)
            sys.stdout.flush()
        elapsed = time.time() - t0
        text = "".join(tokens)
        print()
        print(f"\n  Result: {len(tokens)} tokens in {elapsed:.1f}s")
        # Be lenient: model can answer with "4", "four", "2+2=4", etc.
        is_correct = bool(tokens) and any(
            k in text.lower() for k in ["4", "four", "equals four", "=4"]
        )
        return is_correct, elapsed, text
    except Exception as e:
        print(f"\n  ERROR: {type(e).__name__}: {e}")
        return False, 0.0, ""
    finally:
        await provider.aclose()


async def test_embedding() -> bool:
    section("Test 3: Local sentence-transformers embedding")
    from backend.llm.airllm_provider import AirLLMProvider

    provider = AirLLMProvider(device="cpu")
    try:
        # embed(texts: list[str], model: str) — note positional order
        vecs = await provider.embed(["hello world", "goodbye"], "nomic-embed-text")
        vec = vecs[0]
        print(f"  Vector dim: {len(vec)}")
        print(f"  Norm: {sum(v*v for v in vec)**0.5:.3f}")
        # All-MiniLM-L6-v2 produces 384-dim vectors
        return len(vec) == 384
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        return False
    finally:
        await provider.aclose()


async def test_coder() -> tuple[bool, float, str]:
    section("Test 4: Coder agent with Qwen2.5-Coder-1.5B (CPU)")
    from backend.llm.airllm_provider import AirLLMProvider

    provider = AirLLMProvider(device="cpu")
    prompt = "Write a Python hello world function in one line:"
    print(f"  Prompt: {prompt!r}")
    print("  Streaming response:")
    print("  ", end="", flush=True)
    tokens: list[str] = []
    t0 = time.time()
    try:
        async for tok in provider.chat_stream(
            "qwen2.5-coder:1.5b",
            [{"role": "user", "content": "Write a Python hello world function in one line."}],
            options={"max_tokens": 50, "temperature": 0.2, "timeout_seconds": 600},
        ):
            tokens.append(tok)
            sys.stdout.write(tok)
            sys.stdout.flush()
        elapsed = time.time() - t0
        text = "".join(tokens)
        print()
        print(f"\n  Result: {len(tokens)} tokens in {elapsed:.1f}s")
        # Check if the response contains "def" or "print" (Python code markers)
        has_code = any(k in text for k in ["def ", "print(", "Hello"])
        return has_code, elapsed, text
    except Exception as e:
        print(f"\n  ERROR: {type(e).__name__}: {e}")
        return False, 0.0, ""
    finally:
        await provider.aclose()


async def main() -> int:
    print()
    print("*" * 70)
    print("* NEXUS IDE — End-to-End airllm smoke test")
    print("*" * 70)

    # Check disk
    import shutil
    total, used, free = shutil.disk_usage("C:\\")
    print(f"\nDisk: {free/1024**3:.1f} GB free of {total/1024**3:.1f} GB")

    # Check models
    local_dir = Path.home() / ".cache" / "huggingface" / "local-models"
    print(f"\nLocal models: {local_dir}")
    if local_dir.exists():
        for d in local_dir.iterdir():
            if d.is_dir():
                s = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                print(f"  {d.name}: {s/1024**3:.2f} GB")

    results = {}

    # 1. Resolution
    results["resolve"] = test_model_resolution()

    # 2. Chat with 1.5B
    ok, t, text = await test_chat()
    results["chat_1.5b"] = ok
    results["chat_1.5b_time"] = t

    # 3. Embedding
    results["embed"] = await test_embedding()

    # 4. Coder
    ok, t, text = await test_coder()
    results["coder"] = ok
    results["coder_time"] = t

    # Summary
    print()
    print("=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    for k, v in results.items():
        marker = "[OK]" if v else "[FAIL]"
        print(f"  {marker} {k} = {v}")
    all_ok = all(v for k, v in results.items() if k != "chat_1.5b_time" and k != "coder_time")
    print()
    print(f"  Overall: {'ALL GREEN' if all_ok else 'SOME FAILURES'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
