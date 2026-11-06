"""Fase 1b — real-subprocess restart test for checkpoint/resume/idempotência.

This is the test that proves the durable run state survives the thing every
durable run state claims to survive: the process going away.

The backend is started here as a real ``uvicorn`` subprocess — no
``TestClient``, no in-process lifespan shortcut — listening on a free port, with
its own database and log directory under ``tmp_path``.  The model is a real HTTP
server (a threading ``http.server`` in this same process) speaking the Ollama
protocol, so the backend talks to a provider over a socket exactly as it would
in production, and the script controls every reply it gives.

The choreography:

1. start the backend and drive one turn whose script is ``write_file`` then
   ``BLOCK`` — the write runs for real, its checkpoints and its idempotency-ledger
   entry are persisted, and the turn is *parked inside the model call*;
2. ``SIGKILL`` the process, which is the whole point: no shutdown hook, no
   ``finally``, nothing graceful;
3. start a second backend against the same database and assert the run is
   discoverable as incomplete;
4. resume it through the API and assert the state that comes back is the
   checkpoint the dead process actually wrote;
5. continue the turn with the same idempotency key and assert the run is
   adopted rather than duplicated, that the already-confirmed side effect is not
   recorded twice, and that it only reaches ``COMPLETED`` with a satisfied
   definition of done.

A fallback that runs two ``python -m pytest`` processes against a shared
database is deliberately not implemented: the subprocess form is reachable (a
scripted Ollama provider needs no API keys), and a shared-database variant would
test something weaker while looking like it tested the same thing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from backend.orchestrator.routes.chat_primary import (
    PRIMARY_DOD_ANSWER,
    PRIMARY_DOD_VERIFIED,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
STARTUP_TIMEOUT_S = 150.0

logger = logging.getLogger(__name__)

WRITE_FILE_TOOL = "write_file"
BLOCK = "BLOCK"
# The prompt-based tool-call delimiter the primary agent parses. Assembled from
# parts so the test source never has to contain the literal marker (which is
# indistinguishable from a real call to anything reading this file).
TOOL_TAG_OPEN = "<" + "tool_call" + ">"
TOOL_TAG_CLOSE = "</" + "tool_call" + ">"


def _tool_call(name: str, arguments: dict[str, Any]) -> str:
    return f"{TOOL_TAG_OPEN}{json.dumps({'name': name, 'arguments': arguments}, sort_keys=True)}{TOOL_TAG_CLOSE}"


class ScriptedProvider:
    """Thread-safe queue of replies; exhausting the script parks the caller.

    A parked reply holds the request (and therefore the whole turn, and
    therefore the durable run) in place until :meth:`release` is called or the
    gate times out. That is what makes an *in-flight* run observable: the test
    can look at the database while the backend is still inside the turn.
    """

    def __init__(self, *, block_timeout: float = 300.0) -> None:
        self.replies: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self._gate = threading.Event()
        self._parked = threading.Event()
        self._block_timeout = block_timeout
        self._lock = threading.Lock()

    @property
    def parked(self) -> bool:
        """Whether the scripted model is currently holding a reply back."""
        return self._parked.is_set()

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.calls)

    def release(self) -> None:
        """Let a parked request fail fast instead of waiting for the gate."""
        self._gate.set()

    def next_reply(self) -> str | None:
        """The next scripted reply, or ``None`` once the gate is exhausted."""
        while True:
            with self._lock:
                reply = self.replies.pop(0) if self.replies else None
            if reply is not None and reply != BLOCK:
                return reply
            # Nothing scripted left (or an explicit BLOCK): hold the request.
            self._parked.set()
            self._gate.wait(timeout=self._block_timeout)
            self._parked.clear()
            self._gate.clear()
            return None

    def record(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.calls.append(payload)


class _ProviderHandler(BaseHTTPRequestHandler):
    """The smallest possible Ollama-compatible provider."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # keep the test output readable
        pass

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        server = self.server  # type: ignore[assignment]
        server.script.record(payload)  # type: ignore[attr-defined]
        if self.path.endswith("/api/chat"):
            text = server.script.next_reply()  # type: ignore[attr-defined]
            if text is None:
                self._send_json({"error": "no scripted reply left"})
                return
            body = (
                json.dumps({"message": {"role": "assistant", "content": text}, "done": False})
                + "\n"
                + json.dumps({"done": True, "prompt_eval_count": 5, "eval_count": 8})
                + "\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json({})

    def do_GET(self) -> None:
        if self.path.endswith("/api/tags"):
            self._send_json({"models": [{"name": "scripted:latest"}]})
            return
        self._send_json({"object": "list", "data": [{"id": "scripted:latest"}]})


# ---------------------------------------------------------------------------
# the subprocess under test
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_db_rows(db_path: Path, table: str) -> list[dict[str, Any]]:
    """Every row of one table, straight from SQLite (no ORM, no cache)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


def _run_rows(db_path: Path) -> list[dict[str, Any]]:
    return _read_db_rows(db_path, "run_state")


def _side_effects(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    return [
        row
        for row in _read_db_rows(db_path, "run_side_effects")
        if str(row["run_id"]) == run_id
    ]


def _phases(db_path: Path, run_id: str) -> list[str]:
    return [
        str(row["phase"])
        for row in _read_db_rows(db_path, "run_checkpoints")
        if str(row["run_id"]) == run_id
    ]


class BackendUnderTest:
    """One real ``uvicorn`` process, with the log it writes on disk."""

    def __init__(
        self,
        port: int,
        db_path: Path,
        log_path: Path,
        ollama_host: str,
        *,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.db_path = db_path
        self.log_path = log_path
        self._token: str | None = None
        self._script: ScriptedProvider | None = None
        env = dict(os.environ)
        env.update(
            {
                "NEXUS_DB_PATH": str(db_path),
                "NEXUS_BACKGROUND_SERVICES": "off",
                "NEXUS_EVENT_JOURNAL": "0",
                "LOG_LEVEL": "INFO",
                "LLM_PROVIDER": "ollama",
                "MULTI_LLM_ENABLED": "false",
                # The child reads both inherited environment and the repo's
                # runtime settings.json. Never let an exhausted scripted
                # Ollama response fall through to the operator's cloud keys.
                "NEXUS_TEST_DISABLE_REMOTE_FALLBACKS": "true",
                "NEXUS_AUTONOMOUS_AUDIT_PASS": "auto",
                "NEXUS_ENABLE_OLLAMA": "true",
                "NEXUS_FREE_ONLY": "false",
                "OLLAMA_HOST": ollama_host,
                # The repo's live advanced-mode state has ``autonomous`` armed,
                # which routes every project request to the legacy planner and
                # would bypass the primary lane this test exercises. Point the
                # orchestrator at the throwaway root instead of touching the
                # operator's state on disk.
                "NEXUS_ADVANCED_STATE_ROOT": str(log_path.parent / "advanced-state"),
                # Prompt-based tool calling: the scripted replies use the
                # delimited marker, so the OpenAI ``tools`` schema must not
                # take over the protocol.
                "NEXUS_NATIVE_TOOL_CALLING": "0",
                # The default heartbeat cadence is 30s: a turn parked for two
                # seconds would leave none. Shortening it makes the heartbeat
                # checkpoint (and the liveness it implies) part of what the
                # kill and the resume actually exercise.
                "NEXUS_PRIMARY_HEARTBEAT_INTERVAL": "1",
                "JWT_SECRET": "test-run-resume-e2e-secret-2026-10-23",
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": str(REPO_ROOT),
            }
        )
        if env_overrides:
            env.update(env_overrides)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as handle:
            self._log_handle = handle
            self.process = subprocess.Popen(
                [
                    str(PYTHON),
                    "-m",
                    "backend.tests.integration.run_backend_subprocess",
                    "--port",
                    str(port),
                ],
                cwd=str(REPO_ROOT),
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

    # -- lifecycle ------------------------------------------------------
    def wait_ready(self, timeout: float = STARTUP_TIMEOUT_S) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(
                    f"backend exited early with {self.process.returncode}; "
                    f"tail of {self.log_path}:\n{self.tail()}"
                )
            try:
                with urllib.request.urlopen(self.base_url + "/health", timeout=2) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                time.sleep(1.0)
        raise AssertionError(f"backend not ready after {timeout}s:\n{self.tail()}")

    def alive(self) -> bool:
        return self.process.poll() is None

    def kill(self) -> None:
        if self.process.poll() is not None:
            self._close_log()
            return
        self.process.kill()
        self.process.wait(timeout=60)
        self._close_log()

    def _close_log(self) -> None:
        with contextlib.suppress(Exception):
            self._log_handle.close()

    # -- introspection --------------------------------------------------
    def log_text(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def tail(self, limit: int = 4000) -> str:
        return self.log_text()[-limit:]

    # -- HTTP -----------------------------------------------------------
    def token(self) -> str:
        if self._token is None:
            body = json.dumps(
                {
                    "email": f"e2e{uuid.uuid4().hex[:10]}@example.com",
                    "password": "Passw0rd!23",
                    "full_name": "Run Resume E2E",
                }
            ).encode()
            request = urllib.request.Request(
                self.base_url + "/api/auth/register",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                self._token = str(json.loads(response.read())["access_token"])
        return self._token

    def _authorised(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = json.dumps(body if body is not None else {}).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())

    def get(self, path: str, token: str) -> dict[str, Any]:
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())

    def post(self, path: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._authorised(path, token=token, method="POST", body=body or {})

    def chat(
        self,
        *,
        token: str,
        session_id: str,
        message: str,
        project: Path,
        key: str,
        timeout: float = 240.0,
        until_parked: bool = False,
    ) -> list[dict[str, Any]]:
        body = json.dumps(
            {
                "message": message,
                "session_id": session_id,
                "mode": "auto",
                # This harness's Ollama server only exposes one concrete model.
                # Pin it explicitly so PRIMARY never has to resolve a cloud
                # tier ID against the local scripted provider.
                "provider": "ollama",
                "model": "scripted:latest",
                "project_path": str(project),
                "autonomous": True,
            }
        ).encode()
        request = urllib.request.Request(
            self.base_url + "/api/chat",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Idempotency-Key": key,
            },
        )
        frames: list[dict[str, Any]] = []
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if line.startswith("data:"):
                        frame = json.loads(line[5:].strip() or "{}")
                        frames.append(frame)
                        if frame.get("type") == "done":
                            break
                    if until_parked and self.provider_parked():
                        break
        except Exception as exc:  # noqa: BLE001 - a killed process ends the stream
            logger.info("chat stream ended with %s: %s", type(exc).__name__, exc)
        return frames

    def provider_parked(self) -> bool:
        """Whether the scripted model this backend talks to is parked."""
        return bool(getattr(self, "_script", None) and self._script.parked)


@pytest.fixture()
def harness(tmp_path: Path) -> Any:
    """A scripted Ollama provider plus the paths one backend run uses."""
    script = ScriptedProvider(block_timeout=90.0)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
    server.script = script  # type: ignore[attr-defined]
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield {
            "provider": script,
            "db": tmp_path / "nexus.db",
            "project": tmp_path / "project",
            "logs": tmp_path / "logs",
            "ollama": f"http://127.0.0.1:{server.server_address[1]}",
        }
    finally:
        script.release()
        server.shutdown()


@pytest.mark.timeout(900)
def test_real_restart_resumes_the_run_the_process_left_open(
    harness: dict[str, Any],
) -> None:
    """Kill a real backend mid-turn, restart it, resume the run, finish it."""
    script: ScriptedProvider = harness["provider"]
    db: Path = harness["db"]
    project: Path = harness["project"]
    project.mkdir(parents=True, exist_ok=True)

    query = "Cria o ficheiro notas.txt no projeto com o conteudo pedido."
    write_args = {"path": "notas.txt", "content": "checkpoint fase 1b"}
    idempotency_key = f"restart-{uuid.uuid4().hex[:10]}"
    session_id = f"e2e-{uuid.uuid4().hex[:8]}"

    # -- process 1: run the turn, park it inside the model call, kill it ----
    script.replies = [_tool_call(WRITE_FILE_TOOL, write_args)]
    first = BackendUnderTest(_free_port(), db, harness["logs"] / "first.log", harness["ollama"])
    first.wait_ready()
    first._script = script
    try:
        token = first.token()
        assert first.get("/api/runs/resumable", token)["runs"] == []

        first.chat(
            token=token,
            session_id=session_id,
            message=query,
            project=project,
            key=idempotency_key,
            until_parked=True,
        )
        assert script.parked, "the model must be parked inside the turn"

        runs = _run_rows(db)
        assert len(runs) == 1, (
            f"exactly one durable run, got {[r['run_id'] for r in runs]}; "
            f"log tail:\n{first.tail()}"
        )
        run_id = str(runs[0]["run_id"])
        assert str(runs[0]["state"]) != "completed"
        assert str(runs[0]["goal"]) == query
        assert str(runs[0]["session_id"]) == session_id

        phases = _phases(db, run_id)
        assert phases, "checkpoints must be persisted before the kill"
        # The turn is parked mid-cycle, so the model cycle never completes:
        # ``after_task`` cannot be there. What must be there is the bracket
        # around the real-world write and the heartbeats that kept the run
        # alive while it waited — those are the resume surface.
        for phase in ("before_side_effect", "after_side_effect", "heartbeat"):
            assert phase in phases, f"{phase} missing from {phases}"

        effects_before = _side_effects(db, run_id)
        assert len(effects_before) == 1, effects_before
        assert str(effects_before[0]["kind"]) == WRITE_FILE_TOOL
        assert (project / "notas.txt").exists(), "the write must be real"
    finally:
        first.kill()
    assert not first.alive(), "the killed process must not exist"

    # -- process 2: same database, brand new process ----------------------
    script.replies = [
        _tool_call(WRITE_FILE_TOOL, write_args),
        "notas.txt confirmado.",
        "A auditoria confirma o ficheiro. Não encontrou outra melhoria segura dentro do âmbito.",
    ]
    second = BackendUnderTest(
        _free_port(), db, harness["logs"] / "second.log", harness["ollama"]
    )
    second.wait_ready()
    second._script = script
    try:
        log = second.log_text()
        assert any(
            "incomplete run at startup" in line for line in log.splitlines()
        ), f"the restart must log the incomplete run; tail:\n{second.tail()}"

        resumable = second.get("/api/runs/resumable", token)
        listed = [str(entry["run_id"]) for entry in resumable["runs"]]
        assert run_id in listed, f"the run must be listed as resumable: {listed}"
        entry = next(item for item in resumable["runs"] if item["run_id"] == run_id)
        assert str(entry["state"]) == "recovering", entry["state"]
        assert str(entry["goal"]) == query
        assert str(entry["session_id"]) == session_id

        resumed = second.post(f"/api/runs/{run_id}/resume", token)
        assert str(resumed["run_id"]) == run_id
        assert str(resumed["state"]) == "recovering"
        assert str(resumed["resumable"]) in {"True", "true"}
        # Whatever the run was doing when it died, the checkpoint that comes
        # back is one of the phases this lane actually writes.
        assert str(resumed["phase"]) in {
            "after_side_effect",
            "before_side_effect",
            "after_task",
            "after_verification",
            "heartbeat",
        }, resumed
        assert resumed["checkpoint"], resumed

        # The restored state is the one the dead process persisted: the newest
        # checkpoint on disk is the one the API hands back.
        restored = dict(resumed["checkpoint"])
        assert restored.get("checkpoint_id"), restored
        assert restored.get("phase") == str(resumed["phase"])
        assert restored.get("created_at"), restored
        if str(resumed["phase"]) == "heartbeat":
            assert "signal" in restored, restored
        else:
            assert "idempotency_key" in restored or "task_id" in restored, restored

        rows = [row for row in _run_rows(db) if row["run_id"] == run_id]
        assert len(rows) == 1
        assert str(rows[0]["state"]) == "recovering"

        # -- continue: same session+query+key must adopt the run ------------
        frames = second.chat(
            token=token,
            session_id=session_id,
            message=query,
            project=project,
            key=idempotency_key,
        )
        assert frames, "the continuation must stream something"

        rows = [row for row in _run_rows(db) if row["run_id"] == run_id]
        assert len(rows) == 1, "a retried request must not create a second run"
        final = rows[0]
        assert str(final["state"]) == "completed", final["state"]
        dod = json.loads(str(final["dod_results_json"]) or "[]")
        verdicts = {str(item["requirement"]): str(item["verdict"]) for item in dod}
        assert verdicts.get(PRIMARY_DOD_ANSWER) == "PASS", dod
        assert verdicts.get(PRIMARY_DOD_VERIFIED) == "PASS", dod

        effects_after = _side_effects(db, run_id)
        assert len(effects_after) == 1, (
            "the already-confirmed side effect must not be recorded twice: "
            f"{[str(e['idempotency_key']) for e in effects_after]}"
        )
        assert (project / "notas.txt").exists()
    finally:
        second.kill()


@pytest.mark.timeout(600)
def test_idempotency_key_does_not_duplicate_a_running_run(
    harness: dict[str, Any],
) -> None:
    """A client retry with the same key reuses the durable run in flight."""
    script: ScriptedProvider = harness["provider"]
    project: Path = harness["project"]
    project.mkdir(parents=True, exist_ok=True)
    db: Path = harness["db"]

    query = "Cria o ficheiro ola.txt com ola."
    key = f"idem-{uuid.uuid4().hex[:10]}"
    script.replies = [_tool_call(WRITE_FILE_TOOL, {"path": "ola.txt", "content": "ola"})]

    backend = BackendUnderTest(_free_port(), db, harness["logs"] / "retry.log", harness["ollama"])
    backend.wait_ready()
    backend._script = script
    try:
        token = backend.token()
        backend.chat(
            token=token,
            session_id="retry-session",
            message=query,
            project=project,
            key=key,
            until_parked=True,
        )
        assert script.parked, "the first turn must still be in flight"

        runs = _run_rows(db)
        assert len(runs) == 1, [str(row["run_id"]) for row in runs]
        run_id = str(runs[0]["run_id"])
        assert str(runs[0]["state"]) != "completed"
        provider_calls_before_retry = script.call_count

        # The retry runs while the first turn is still parked: it must attach
        # to the existing event stream without calling the provider twice.
        with ThreadPoolExecutor(max_workers=1) as pool:
            retry = pool.submit(
                backend.chat,
                token=token,
                session_id="retry-session",
                message=query,
                project=project,
                key=key,
                until_parked=True,
            )
            time.sleep(1.0)
            rows = _run_rows(db)
            assert len(rows) == 1, (
                "the retry must not create a second durable run: "
                f"{[str(row['run_id']) for row in rows]}"
            )
            assert str(rows[0]["run_id"]) == run_id
            assert script.call_count == provider_calls_before_retry, (
                "an idempotent retry must not add another provider call"
            )
            script.release()
            retry.result(timeout=180)

        rows = _run_rows(db)
        assert len(rows) == 1, (
            "the retry must not create a second durable run: "
            f"{[str(row['run_id']) for row in rows]}"
        )
        assert str(rows[0]["run_id"]) == run_id
        # Releasing the gate lets the parked requests fail loudly (the scripted
        # provider has nothing left to say), so the run's final state here is
        # whatever that failure produces. The invariant under test is the run
        # *identity* above, not the outcome of a script the test never wrote.
        assert str(rows[0]["state"]) in {
            "completed",
            "failed",
            "cancelled",
            "running",
            "paused",
            "recovering",
        }, rows[0]["state"]
    finally:
        script.release()
        backend.kill()
