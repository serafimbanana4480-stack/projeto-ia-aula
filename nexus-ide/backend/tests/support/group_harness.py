"""One disposable group-runtime environment: provider + real backend + state."""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from backend.tests.support.group_runtime import (
    BackgroundComposer,
    latest_group_run,
    send_composer,
)
from backend.tests.support.nexus_backend import (
    BackendHandle,
    BackendProcess,
    auth_headers,
    create_bot,
    create_group,
    dump_state,
    make_token,
    write_json_evidence,
)
from backend.tests.support.scripted_provider import LoopbackProvider


def _evidence_root() -> Path:
    configured = os.environ.get("NEXUS_E2E_EVIDENCE_DIR", "").strip()
    if configured:
        return Path(configured)
    temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")
    stamp = time.strftime("%Y%m%dT%H%M%S")
    return temp / "opencode" / f"nexus-e2e-group-{stamp}-{os.getpid()}"


@dataclass
class GroupHarness:
    """Real uvicorn backend + loopback model provider + disposable DB."""

    root: Path
    provider: LoopbackProvider = field(init=False)
    backend: BackendProcess = field(init=False)
    handle: BackendHandle = field(init=False)
    client: httpx.Client = field(init=False)
    token: str = field(init=False)
    user_id: str = "e2e-user"
    backend_port: int | None = None
    evidence_dir: Path = field(init=False)
    evidence: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.evidence_dir = _evidence_root() / self.root.name
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.provider = LoopbackProvider()
        self.backend = BackendProcess(
            provider_url="",  # set after the provider binds its port
            root=self.root,
            jwt_secret=os.environ.get(
                "JWT_SECRET",
                "e2e-only-jwt-secret-with-more-than-thirty-two-characters",
            ),
            port=self.backend_port,
        )

    # ------------------------------------------------------------------
    def __enter__(self) -> GroupHarness:
        self.provider.start()
        self.backend.provider_url = self.provider.url
        self.handle = self.backend.start()
        self.token = make_token(self.user_id)
        self.client = httpx.Client(
            base_url=self.handle.base_url,
            headers=auth_headers(self.token),
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        self.evidence["provider_url"] = self.provider.url
        self.evidence["db_path"] = str(self.handle.db_path)
        self.evidence["workspace"] = str(self.handle.workspace)
        self.evidence["log_path"] = str(self.handle.log_path)
        return self

    def __exit__(self, *_exc: object) -> None:
        with contextlib.suppress(Exception):
            self.client.close()
        self.backend.stop(kill=True)
        self.provider.close()

    # ------------------------------------------------------------------
    def restart_backend(self) -> BackendHandle:
        self.handle = self.backend.restart()
        with contextlib.suppress(Exception):
            self.client.close()
        self.client = httpx.Client(
            base_url=self.handle.base_url,
            headers=auth_headers(self.token),
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        self.evidence.setdefault("restarts", []).append(
            {"at": time.time(), "db_path": str(self.handle.db_path)}
        )
        return self.handle

    # ------------------------------------------------------------------
    def register_project(self, *, name: str = "E2E workspace") -> dict[str, Any]:
        """Register the disposable workspace, exactly as the UI does.

        The file/tool boundary refuses arbitrary directories; the test must not
        bypass it.  Creating the project through the real API keeps the
        confinement check active for the whole scenario.
        """
        response = self.client.post(
            "/api/projects",
            json={"name": name, "path": str(self.handle.workspace), "trust": True},
        )
        response.raise_for_status()
        project = response.json()["project"]
        self.evidence["project"] = {"id": project.get("id"), "path": project.get("path")}
        return project

    def seed(self, *, bot_names: list[str], group_name: str = "E2E group") -> dict[str, Any]:
        bots = [create_bot(self.client, name=name) for name in bot_names]
        group = create_group(self.client, name=group_name, bot_ids=[bot["id"] for bot in bots])
        self.evidence["bots"] = [
            {
                "id": bot["id"],
                "name": bot["name"],
                "session_id": bot.get("session_id"),
                "model": bot.get("model"),
                "provider": bot.get("provider"),
            }
            for bot in bots
        ]
        self.evidence["group"] = {"id": group["id"], "name": group["name"]}
        return {"bots": bots, "group": group}

    def send(
        self,
        group_id: str,
        message: str,
        *,
        project_path: str = "",
        timeout: float = 120.0,
    ):
        started = time.monotonic()
        result = send_composer(
            self.client,
            group_id,
            message,
            project_path=project_path,
            timeout=timeout,
        )
        self.evidence.setdefault("requests", []).append(
            {
                "group_id": group_id,
                "message": message,
                "status": result.status_code,
                "content_type": result.content_type,
                "frames": len(result.frames),
                "run_ids": result.run_ids,
                "error": result.error,
                "duration_s": round(time.monotonic() - started, 3),
            }
        )
        return result

    def background_send(
        self, group_id: str, message: str, *, project_path: str = ""
    ) -> BackgroundComposer:
        started = time.monotonic()
        call = BackgroundComposer(
            base_url=self.handle.base_url,
            token=self.token,
            group_id=group_id,
            message=message,
            project_path=project_path,
        ).start()
        self.evidence.setdefault("requests", []).append(
            {
                "group_id": group_id,
                "message": message,
                "background": True,
                "started_at": started,
            }
        )
        return call

    # ------------------------------------------------------------------
    def run_row(self, group_id: str, *, request: str | None = None) -> dict[str, Any] | None:
        return latest_group_run(self.handle.db_path, group_id, request=request)

    def state(self, run_id: str) -> dict[str, Any]:
        return dump_state(self.handle.db_path, run_id)

    def write_evidence(self, name: str, extra: dict[str, Any] | None = None) -> Path:
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_s": round(time.monotonic() - self.started_at, 3),
            "provider": self.provider.snapshot(),
            "backend_log_tail": self.backend.log_tail(self.handle, 80),
            **self.evidence,
        }
        if extra:
            payload.update(extra)
        return write_json_evidence(self.evidence_dir / f"{name}.json", payload)


def provider_transcript(provider: LoopbackProvider) -> str:
    return json.dumps(provider.snapshot(), ensure_ascii=False, indent=2)


__all__ = ["GroupHarness", "provider_transcript"]
