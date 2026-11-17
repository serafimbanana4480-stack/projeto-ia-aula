"""Launch the real NEXUS backend (uvicorn) against disposable state.

The group-runtime closeout tests must prove behaviour across a real process
boundary (kill/restart, startup recovery, SQLite durability).  An in-process
``TestClient`` cannot provide that proof.  This helper therefore starts the
actual FastAPI application with ``uvicorn`` and points it at:

* a temporary SQLite database (``NEXUS_DB_PATH``);
* a temporary project/workspace root;
* a loopback Ollama-compatible provider owned by the test process.

Only the provider is scripted.  The coordinator, persistence, tool registry,
routes and event stream are the production implementations.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
"""``.../nexus-ide``; the directory pytest runs from."""

#: Every remote credential is removed from the child environment.  A test that
#: accidentally falls through the provider chain must fail closed, not spend.
_SECRET_ENV_NAMES = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "KIMI_API_KEY",
    "KILO_API_KEY",
    "OPENCODE_GO_API_KEY",
    "BRAVE_API_KEY",
)

_LAUNCHER = r"""
import os
import sys

repo = sys.argv[1]
provider_url = sys.argv[2]
host = sys.argv[3]
port = int(sys.argv[4])
sys.path.insert(0, repo)

from backend.llm.factory import create_llm_client

# The disposable E2E process must never read the operator's live
# data/settings.json: that file can select a paid provider even when the child
# env names a loopback provider. The orchestrator points this at a path that
# does not exist; the factory then falls back to the explicit child env.
from pathlib import Path as _Path
import backend.llm.factory as _factory_module
_factory_module.RUNTIME_SETTINGS_PATH = _Path(
    os.environ.get("NEXUS_E2E_SETTINGS_PATH", "/nonexistent/nexus-e2e-settings.json")
)

def _scripted_factory(*args, **kwargs):
    kwargs.update(
        llm_provider="ollama",
        ollama_host=provider_url,
        free_only=False,
        multi_llm_enabled=False,
        nexus_enable_ollama=True,
    )
    return create_llm_client(*args, **kwargs)

import backend.llm as llm_package
llm_package.create_llm_client = _scripted_factory

from backend.orchestrator import main as main_module
main_module.create_llm_client = _scripted_factory

import uvicorn
uvicorn.run(
    main_module.app,
    host=host,
    port=port,
    log_level=os.environ.get("NEXUS_E2E_UVICORN_LOG_LEVEL", "info"),
    access_log=False,
    lifespan="on",
)
"""


@dataclass
class BackendHandle:
    """One live backend process and the disposable state it owns."""

    process: subprocess.Popen[bytes]
    base_url: str
    db_path: Path
    workspace: Path
    log_path: Path
    env: dict[str, str]


class BackendProcess:
    """Start/stop the real backend with a loopback scripted provider."""

    def __init__(
        self,
        *,
        provider_url: str,
        root: Path,
        jwt_secret: str,
        extra_env: dict[str, str] | None = None,
        port: int | None = None,
    ) -> None:
        self.provider_url = provider_url
        self.root = root
        self.fixed_port = port
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / "nexus.db"
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.log_path = root / "backend.log"
        self.jwt_secret = jwt_secret
        self.extra_env = dict(extra_env or {})
        self.handle: BackendHandle | None = None
        self._log_handle: Any = None
        self._port = 0

    # ------------------------------------------------------------------
    def _clean_env(self) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in _SECRET_ENV_NAMES and not key.startswith("NEXUS_")
        }
        env.update(
            {
                "PYTHONPATH": str(REPO_ROOT),
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
                "LLM_PROVIDER": "ollama",
                "OLLAMA_HOST": self.provider_url,
                "OLLAMA_DASHBOARD_HOST": self.provider_url,
                "OLLAMA_DEFAULT_MODEL": "scripted:latest",
                "OLLAMA_CODER_MODEL": "scripted:latest",
                "OLLAMA_FAST_MODEL": "scripted:latest",
                "NEXUS_ENABLE_OLLAMA": "true",
                "NEXUS_FREE_ONLY": "false",
                "MULTI_LLM_ENABLED": "false",
                "NEXUS_TEST_DISABLE_REMOTE_FALLBACKS": "true",
                "NEXUS_TEST_MODEL": "scripted:latest",
                "NEXUS_E2E_SETTINGS_PATH": str(self.root / "settings-none.json"),
                "NEXUS_DAILY_BUDGET_USD": "5.0",
                "NEXUS_DB_PATH": str(self.db_path),
                "NEXUS_EVENT_JOURNAL": "0",
                "NEXUS_ADVISOR_ENABLED": "false",
                "NEXUS_BACKGROUND_SERVICES": "off",
                "NEXUS_ENABLE_BACKGROUND_WORKERS": "false",
                "NEXUS_ENABLE_DASHBOARD_AGENT": "false",
                "NEXUS_ENABLE_GUARDIAN_AGENT": "false",
                "NEXUS_ENABLE_AUTO_CORRECTION": "false",
                "NEXUS_ENABLE_EXEC_ENGINE": "false",
                "NEXUS_ENABLE_CONTINUOUS_IMPROVEMENT": "false",
                "NEXUS_ENABLE_SELF_IMPROVEMENT": "false",
                "NEXUS_ENABLE_SELF_HEALING": "false",
                "NEXUS_ENABLE_AI_ORCHESTRATOR": "false",
                "NEXUS_ENABLE_AUTO_TRIGGER": "false",
                "NEXUS_ENABLE_SESSION_GC": "false",
                "NEXUS_DISK_GUARD_MIN_PERCENT": "0",
                "NEXUS_ALLOW_DEGRADED_STARTUP": "true",
                "NEXUS_VIBE_STATE_ROOT": str(self.root / "vibe-state"),
                "NEXUS_ADVANCED_STATE_ROOT": str(self.root / "advanced-state"),
                "NEXUS_GROUP_TURN_TIMEOUT_SECONDS": "30",
                "NEXUS_GROUP_RUN_MAX_SECONDS": "120",
                "JWT_SECRET": self.jwt_secret,
                "SECRET_KEY": self.jwt_secret,
                "JWT_ALGORITHM": "HS256",
                "NEXUS_DEFAULT_EMAIL": "admin@nexus-ide.com",
                "NEXUS_DEFAULT_PASSWORD": "5748",
                "ALLOW_SELF_REGISTRATION": "true",
                "BACKEND_HOST": "127.0.0.1",
                "ENVIRONMENT": "development",
                "LOG_LEVEL": "INFO",
                "NEXUS_E2E_UVICORN_LOG_LEVEL": "info",
            }
        )
        env.update(self.extra_env)
        return env

    def start(self, *, timeout: float = 90.0) -> BackendHandle:
        from backend.tests.support.scripted_provider import free_port

        self._port = self.fixed_port or free_port()
        host = "127.0.0.1"
        env = self._clean_env()
        self._log_handle = self.log_path.open("ab")
        self._log_handle.write(
            f"\n===== start {time.strftime('%Y-%m-%dT%H:%M:%S')} port={self._port} "
            f"db={self.db_path} provider={self.provider_url} =====\n".encode()
        )
        self._log_handle.flush()
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                _LAUNCHER,
                str(REPO_ROOT),
                self.provider_url,
                host,
                str(self._port),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        base_url = f"http://{host}:{self._port}"
        self.handle = BackendHandle(
            process=process,
            base_url=base_url,
            db_path=self.db_path,
            workspace=self.workspace,
            log_path=self.log_path,
            env=env,
        )
        self.wait_ready(self.handle, timeout=timeout)
        return self.handle

    def wait_ready(self, handle: BackendHandle, *, timeout: float = 90.0) -> None:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            if handle.process.poll() is not None:
                tail = self.log_tail(handle, 80)
                raise RuntimeError(
                    f"backend exited during startup rc={handle.process.returncode}\n{tail}"
                )
            try:
                response = httpx.get(f"{handle.base_url}/health", timeout=1.0)
                if response.status_code == 200:
                    self.wait_db_ready(handle, timeout=max(1.0, deadline - time.monotonic()))
                    return
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            except Exception as exc:  # noqa: BLE001 - startup polling
                last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.15)
        raise RuntimeError(f"backend did not become ready: {last_error}\n{self.log_tail(handle, 80)}")

    def wait_db_ready(self, handle: BackendHandle, *, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with sqlite3.connect(handle.db_path, timeout=1.0) as conn:
                    tables = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                if "bot_group_runs" in tables and "run_state" in tables:
                    return
            except sqlite3.Error:
                pass
            time.sleep(0.1)
        raise RuntimeError("backend health is up but the database schema is not ready")

    # ------------------------------------------------------------------
    def stop(self, *, kill: bool = False, timeout: float = 20.0) -> int | None:
        handle = self.handle
        if handle is None:
            return None
        process = handle.process
        if process.poll() is None:
            if kill:
                process.kill()
            else:
                process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if self._log_handle is not None:
            self._log_handle.write(
                f"===== stop {time.strftime('%Y-%m-%dT%H:%M:%S')} rc={process.returncode} =====\n".encode()
            )
            self._log_handle.flush()
            self._log_handle.close()
            self._log_handle = None
        self.handle = None
        return process.returncode

    def restart(self, *, timeout: float = 90.0) -> BackendHandle:
        self.stop(kill=True)
        # Keep the same database and workspace; only the process is new.
        return self.start(timeout=timeout)

    def log_tail(self, handle: BackendHandle | None = None, lines: int = 120) -> str:
        path = handle.log_path if handle is not None else self.log_path
        try:
            raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(raw[-lines:])

    def __enter__(self) -> BackendHandle:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop(kill=True)


# ----------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------
def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_token(user_id: str = "e2e-user", email: str = "e2e@test.local") -> str:
    from backend.middleware.auth import create_access_token

    return create_access_token({"sub": user_id, "email": email})


def create_bot(
    client: httpx.Client,
    *,
    name: str,
    provider: str = "ollama",
    model: str = "scripted:latest",
    capabilities: dict[str, bool] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "description": "Test bot",
        "instructions": "Responde de forma factual.",
        "provider": provider,
        "model": model,
    }
    if capabilities is not None:
        payload["capabilities"] = capabilities
    response = client.post("/api/bots", json=payload)
    response.raise_for_status()
    return response.json()


def create_group(client: httpx.Client, *, name: str, bot_ids: list[str]) -> dict[str, Any]:
    response = client.post("/api/bot-groups", json={"name": name, "bot_ids": bot_ids})
    response.raise_for_status()
    return response.json()


# ----------------------------------------------------------------------
# SQLite helpers (read-only observations; never used to fabricate state)
# ----------------------------------------------------------------------
def connect_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def table_columns(db_path: Path, table: str) -> set[str]:
    with connect_ro(db_path) as conn:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def fetch_all(db_path: Path, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect_ro(db_path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def fetch_one(db_path: Path, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = fetch_all(db_path, query, params)
    return rows[0] if rows else None


def dump_state(db_path: Path, run_id: str) -> dict[str, Any]:
    """Collect the durable evidence for one run, tolerating schema gaps."""
    state: dict[str, Any] = {"run_id": run_id}
    try:
        state["run_state"] = fetch_one(
            db_path, "SELECT * FROM run_state WHERE run_id = ?", (run_id,)
        )
    except sqlite3.Error as exc:
        state["run_state_error"] = str(exc)
    try:
        state["bot_group_run"] = fetch_one(
            db_path, "SELECT * FROM bot_group_runs WHERE id = ?", (run_id,)
        )
    except sqlite3.Error as exc:
        state["bot_group_run_error"] = str(exc)
    try:
        state["tasks"] = fetch_all(
            db_path, "SELECT * FROM bot_group_run_tasks WHERE run_id = ? ORDER BY position", (run_id,)
        )
    except sqlite3.Error as exc:
        state["tasks_error"] = str(exc)
    try:
        rows = fetch_all(
            db_path,
            "SELECT * FROM bot_group_run_records WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        )
        for row in rows:
            try:
                row["payload"] = json.loads(row.get("payload") or "{}")
            except (TypeError, ValueError):
                row["payload"] = {}
        state["records"] = rows
    except sqlite3.Error as exc:
        state["records_error"] = str(exc)
    try:
        state["checkpoints"] = fetch_all(
            db_path, "SELECT * FROM run_checkpoints WHERE run_id = ? ORDER BY created_at", (run_id,)
        )
    except sqlite3.Error as exc:
        state["checkpoints_error"] = str(exc)
    try:
        state["side_effects"] = fetch_all(
            db_path, "SELECT * FROM run_side_effects WHERE run_id = ?", (run_id,)
        )
    except sqlite3.Error as exc:
        state["side_effects_error"] = str(exc)
    try:
        state["session_runs"] = fetch_all(
            db_path, "SELECT * FROM session_runs WHERE id = ? OR correlation_id = ?", (run_id, run_id)
        )
    except sqlite3.Error as exc:
        state["session_runs_error"] = str(exc)
    return state


def write_json_evidence(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


__all__ = [
    "BackendHandle",
    "BackendProcess",
    "REPO_ROOT",
    "auth_headers",
    "connect_ro",
    "create_bot",
    "create_group",
    "dump_state",
    "fetch_all",
    "fetch_one",
    "make_token",
    "table_columns",
    "write_json_evidence",
]
