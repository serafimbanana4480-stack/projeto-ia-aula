"""Subprocess entry point for the Fase 1b restart test.

The backend is started for real (a ``uvicorn`` process), so the test needs a way
to make it use the scripted Ollama provider instead of whatever
``data/settings.json`` pins. That file lives outside this test's ownership and is
mirrored on disk for other workstreams, so patching it is not an option: this
bootstrap patches the *factory* instead, exactly the seam
``backend/tests/e2e_audit_harness.py`` already uses in-process.

Order matters. ``backend.orchestrator.main`` binds ``create_llm_client`` into its
own namespace at import time (``main.py``: ``from backend.llm import
create_llm_client``), so the factory must be patched *before* ``main`` is
imported — which is why this module exists instead of a ``--reload-dir`` flag.

Usage::

    python -m backend.tests.integration.run_backend_subprocess --port NNNN
"""

from __future__ import annotations

import argparse
import os
import sys


def _patch_provider() -> None:
    """Force the local Ollama provider, pointing at the scripted server."""
    from backend.llm.factory import create_llm_client as _original

    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

    def _scripted(**overrides: object):  # noqa: ANN002 - mirrors the real signature
        kwargs: dict[str, object] = {
            "multi_llm_enabled": False,
            "llm_provider": "ollama",
            "ollama_host": host,
            "free_only": False,
        }
        kwargs.update(overrides)
        try:
            return _original(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover - startup must still boot
            print(f"[run_backend_subprocess] provider patch failed: {exc}", file=sys.stderr)
            return _original()

    import backend.llm as llm_pkg

    llm_pkg.create_llm_client = _scripted  # type: ignore[assignment]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    # Importing the app is what binds ``create_llm_client`` into main's
    # namespace, so this has to happen after the patch and before the import.
    _patch_provider()

    import uvicorn

    from backend.orchestrator import main as app_main

    uvicorn.run(
        app_main.app,
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
