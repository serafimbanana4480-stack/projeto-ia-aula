#!/usr/bin/env python
"""Re-download the sentence-transformers/all-MiniLM-L6-v2 model with copies (no symlinks).

Workaround for Windows where HF symlink creation fails without admin/dev-mode.
This copies the actual files into the snapshot directory.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ID = "sentence-transformers/all-MiniLM-L6-v2"
HF_HOME = Path.home() / ".cache" / "huggingface"
REPO_DIR = HF_HOME / f"models--{REPO_ID.replace('/', '--')}"


def main() -> int:
    if REPO_DIR.exists():
        print(f"Removing incomplete cache at {REPO_DIR}...")
        shutil.rmtree(REPO_DIR)

    from huggingface_hub import snapshot_download
    print(f"Downloading {REPO_ID} (using local dir, no symlinks)...")
    p = snapshot_download(
        REPO_ID,
        local_dir=HF_HOME / "local-models" / REPO_ID,
        local_dir_use_symlinks=False,
        ignore_patterns=[
            "*.msgpack",
            "*.h5",
            "*.ot",
            "tf_model.*",
            "flax_model.*",
            "rust_model.*",
        ],
    )
    print(f"OK: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
