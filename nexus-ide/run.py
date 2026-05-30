"""Entry point for running the NEXUS IDE backend on Windows.

Using a dedicated script instead of ``python -m uvicorn`` avoids the
multiprocessing RuntimeError on Windows when ``--reload`` is enabled.
See: https://github.com/encode/uvicorn/issues/1558
"""

import sys
from pathlib import Path

# Ensure project root is on PYTHONPATH so ``backend.*`` imports resolve
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "backend.orchestrator.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
