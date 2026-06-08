#!/usr/bin/env python
"""Install NEXUS / LUSO AI IDE model stack — CPU-optimized.

Replaces the legacy Ollama-based install-models.sh with an airllm-native
downloader. Models are pulled from HuggingFace and stored in the local
HF cache (~/.cache/huggingface/hub).

This stack is tuned for CPU-only machines (no GPU). For GPU machines
edit MODELS to use larger checkpoints.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

# ─── Model stack ───────────────────────────────────────────────────────────
# (HF repo id, tier label, expected size, description)
# Sizes are for the safetensors download (post-2024 HF default).
MODELS: list[tuple[str, str, str, str]] = [
    # ── Tier 1: Embeddings (smallest, always needed) ──
    (
        "sentence-transformers/all-MiniLM-L6-v2",
        "EMBED",
        "~95 MB",
        "Sentence embeddings for similarity/memory",
    ),
    # ── Tier 2: Router/Micro (lightest chat) ──
    (
        "Qwen/Qwen2.5-0.5B-Instruct",
        "MICRO",
        "~1.0 GB",
        "Router, classification, trivial Q&A",
    ),
    # ── Tier 3: Fast/General (best quality/speed ratio) ──
    (
        "Qwen/Qwen2.5-1.5B-Instruct",
        "FAST",
        "~3.0 GB",
        "General tasks, summarisation, formatting",
    ),
    # ── Tier 4: Coder (code-specialized, small) ──
    (
        "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "CODER",
        "~3.0 GB",
        "Code generation, refactoring, debugging",
    ),
    # ── Tier 5: Reasoning (chain-of-thought) ──
    (
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
        "REASON",
        "~3.0 GB",
        "Multi-step reasoning with thinking traces",
    ),
]

HF_HOME = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
HF_HUB = HF_HOME / "hub"
# On Windows, symlinks require admin/dev-mode. Use local-models/ which
# always copies (no symlink needed). This is the only directory airllm
# provider will look at via `_LOCAL_MODELS_DIR`.
HF_LOCAL = HF_HOME / "local-models"


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def dir_size(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def ensure_model(repo_id: str) -> None:
    """Download a HF model if not already cached. Idempotent.

    Uses ``local_dir`` so files are COPIED (not symlinked) — this is the
    only safe strategy on Windows where symlink creation requires
    admin/dev-mode. The download path is the airllm provider's lookup
    path (see ``backend.llm.airllm_provider._LOCAL_MODELS_DIR``).
    """
    from huggingface_hub import snapshot_download

    local_dir = HF_LOCAL / repo_id
    if local_dir.exists():
        # Verify the snapshot has actual model weights
        files = list(local_dir.iterdir()) if local_dir.is_dir() else []
        has_weights = any(
            f.suffix in (".safetensors", ".bin") and f.stat().st_size > 1024
            for f in files
        )
        if has_weights:
            size = sum(f.stat().st_size for f in files if f.is_file())
            print(f"  [OK]  {repo_id}  ({human_bytes(size)}, {len(files)} files)")
            return

    print(f"  [GET] {repo_id} ...", flush=True)
    t0 = time.time()
    try:
        path = snapshot_download(
            repo_id=repo_id,
            local_dir=local_dir,
            ignore_patterns=[
                "*.msgpack",
                "*.h5",
                "*.ot",
                "tf_model.*",
                "flax_model.*",
                "rust_model.*",
                "*.tflite",
            ],
        )
        elapsed = time.time() - t0
        size = dir_size(Path(path))
        print(
            f"  [OK]  {repo_id}  "
            f"({human_bytes(size)} in {elapsed:.1f}s)"
        )
    except Exception as exc:
        print(f"  [ERR] {repo_id}: {exc}", file=sys.stderr)


def main() -> int:
    print("=" * 70)
    print("  NEXUS / LUSO AI IDE — Model Stack Installer (airllm)")
    print("=" * 70)
    print(f"\n  HF cache: {HF_HUB}")
    print(f"  Free disk: {human_bytes(shutil.disk_usage('C:').free)} on C:")
    print()
    print("  Models to install:")
    for repo_id, tier, size, desc in MODELS:
        print(f"    - {tier:<7} {size:<8} {repo_id}")
        print(f"             {desc}")
    print()

    total_before = sum(dir_size(HF_HUB / f"models--{r.replace('/', '--')}") for r, *_ in MODELS)
    if total_before > 0:
        print(f"  [INFO] Already have {human_bytes(total_before)} cached.\n")

    for repo_id, tier, size, desc in MODELS:
        try:
            ensure_model(repo_id)
        except KeyboardInterrupt:
            print("\n  [ABORT] User interrupted")
            return 1
        except Exception as exc:
            print(f"  [ERR] {repo_id}: {type(exc).__name__}: {exc}", file=sys.stderr)

    print("\n" + "=" * 70)
    print("  Stack ready. Recommended models.yaml aliases:")
    print("=" * 70)
    print("    micro/nano    -> qwen2.5:0.5b       (MICRO)")
    print("    fast/small    -> qwen2.5:1.5b       (FAST)")
    print("    medium/coder  -> qwen2.5-coder:1.5b (CODER)")
    print("    reason/large  -> deepseek-r1:1.5b   (REASON)")
    print("    embed         -> nomic-embed-text    (EMBED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
