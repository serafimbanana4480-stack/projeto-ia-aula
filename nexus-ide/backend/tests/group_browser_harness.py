"""Start the disposable real backend used by ``frontend/e2e/group-runtime.spec.ts``.

Run this from ``nexus-ide/`` in one terminal, then run the Playwright spec from
``frontend/`` with ``NEXUS_GROUP_E2E=1``.  The harness binds the backend to the
port the frontend's ``.env.local`` expects (8000 by default), keeps a loopback
scripted provider alive, and writes the evidence location to
``NEXUS_BROWSER_READY_FILE`` so an orchestrating script can wait for it.

Stop it by creating ``NEXUS_BROWSER_HARNESS_STOP`` (the test orchestrator does
this) or with Ctrl+C.  It owns only disposable state under ``NEXUS_E2E_ROOT``.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx

from backend.tests.support.group_harness import GroupHarness
from backend.tests.support.scripted_provider import tool_call

ROOT = Path(os.environ.get("NEXUS_E2E_ROOT") or Path(__file__).resolve().parents[2] / ".cache" / "browser-e2e")
READY = Path(os.environ.get("NEXUS_BROWSER_READY_FILE") or ROOT / "ready.json")
STOP = Path(os.environ.get("NEXUS_BROWSER_HARNESS_STOP") or ROOT / "stop")
PORT = int(os.environ.get("NEXUS_E2E_BACKEND_PORT", "8000"))


def responder(call) -> str:
    if "E2E-TOOL" in call.prompt_text:
        if "CANARY-BROWSER-7F3A" in call.prompt_text:
            return "Token lido do ficheiro: CANARY-BROWSER-7F3A"
        return tool_call("read_file", {"path": "canary.txt"})
    marker = re.search(r"E2E-RESPOSTA-\d+", call.prompt_text)
    if marker:
        return f"Confirmado pelo runtime: {marker.group(0)}"
    return "Resposta determinística do harness."


def main() -> None:
    root = Path(os.environ.get("NEXUS_E2E_ROOT") or ROOT)
    root.mkdir(parents=True, exist_ok=True)
    if STOP.exists():
        STOP.unlink()
    harness = GroupHarness(root, backend_port=PORT)
    try:
        harness.__enter__()
        harness.provider.set_responder(responder)
        login = httpx.post(
            f"{harness.handle.base_url}/api/auth/login",
            json={"email": "admin@nexus-ide.com", "password": "5748"},
            timeout=30.0,
        )
        login.raise_for_status()
        access_token = str(login.json().get("access_token") or "")
        if not access_token:
            raise RuntimeError("login did not return an access token")
        # The browser authenticates as the seeded admin; the project used by
        # the tool read must be registered by that same principal.
        harness.client.headers["Authorization"] = f"Bearer {access_token}"
        project = harness.register_project()
        canary = harness.handle.workspace / "canary.txt"
        canary.write_text("CANARY-BROWSER-7F3A\n", encoding="utf-8")
        payload = {
            "backend_url": harness.handle.base_url,
            "provider_url": harness.provider.url,
            "db_path": str(harness.handle.db_path),
            "workspace": str(harness.handle.workspace),
            "log_path": str(harness.handle.log_path),
            "evidence_dir": str(harness.evidence_dir),
            "user": login.json().get("user"),
            "project_name": project.get("name"),
            "project_id": project.get("id"),
            "project_path": project.get("path"),
            "canary": str(canary),
        }
        READY.parent.mkdir(parents=True, exist_ok=True)
        READY.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps({"ready": str(READY), **payload}, indent=2), flush=True)
        while not STOP.exists():
            time.sleep(0.25)
    finally:
        harness.__exit__()


if __name__ == "__main__":
    main()
