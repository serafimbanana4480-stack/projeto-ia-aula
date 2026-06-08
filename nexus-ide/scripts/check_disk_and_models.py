"""Diagnostic script to find HF cache and check disk."""
import os
import shutil
from pathlib import Path

# Check disk space
total, used, free = shutil.disk_usage("C:\\")
print(f"Disk C: free={free/1024**3:.2f} GB / total={total/1024**3:.2f} GB")

# Check env vars
print("\nEnvironment:")
for k in ["HF_HOME", "TRANSFORMERS_CACHE", "HF_HUB_CACHE", "USERPROFILE", "HOME"]:
    val = os.environ.get(k, "NOT SET")
    print(f"  {k} = {val!r}")

# Check default HF cache locations
print("\nSearching for HF cache:")
search_paths = [
    Path(os.environ.get("HF_HOME", "")) / "hub" if os.environ.get("HF_HOME") else None,
    Path.home() / ".cache" / "huggingface" / "hub",
    Path("C:/Users/rodri/.cache/huggingface/hub"),
    Path("D:/huggingface/hub"),
    Path("C:/huggingface/hub"),
]
for p in search_paths:
    if p is None:
        continue
    print(f"  Checking {p}...")
    if p.exists():
        print(f"    EXISTS")
        for d in p.iterdir():
            if d.is_dir():
                s = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                print(f"      {d.name}: {s/1024**3:.2f} GB")
    else:
        print(f"    not found")
