"""Global pytest fixtures for the NEXUS IDE backend test suite."""

from __future__ import annotations

import gc
import json
import os
import shutil
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import yaml

from backend.tools.ollama_client import OllamaClient

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

#: Root for machine-local pytest scratch. Gitignored; safe to delete by hand.
PYTEST_CACHE_ROOT = REPO_ROOT / ".cache" / "pytest"

#: Set to "1" to disable pruning of orphaned basetemp dirs (debugging only).
KEEP_ORPHANED_BASETEMPS_ENV = "NEXUS_PYTEST_KEEP_ORPHANED_BASETEMPS"


def registered_route_paths(app: Any) -> set[str]:
    """Return every HTTP path an app actually serves, including included routers.

    Why not ``app.openapi()["paths"]``: FastAPI emits ``UserWarning: Duplicate
    Operation ID ...`` while building the schema (a pre-existing collision in
    ``observability/routes/usage.py`` and ``orchestrator/routes/observability.py``),
    and this project runs pytest with ``filterwarnings = ["error", ...]``, so
    touching the OpenAPI schema from a test raises. Walking the router tree has
    no such side effect and is also cheaper.

    Recent FastAPI keeps ``include_router`` results as ``_IncludedRouter``
    wrapper objects rather than flattening them into ``app.routes``, so a plain
    ``app.routes`` scan sees only the handful of directly-attached routes (5
    APIRoute out of 67 entries). The walk therefore recurses through
    ``include_context``. Written defensively with ``getattr`` so a future
    FastAPI that flattens again still works.
    """
    found: set[str] = set()

    def walk(routes: Iterable[Any], prefix: str) -> None:
        for route in routes:
            path = getattr(route, "path", None)
            if isinstance(path, str):
                found.add(f"{prefix}{path}")
                continue
            context = getattr(route, "include_context", None)
            if context is None:
                continue
            inner = getattr(context, "included_router", None)
            inner_routes = getattr(inner, "routes", None)
            if not inner_routes:
                continue
            walk(inner_routes, f"{prefix}{getattr(context, 'prefix', '') or ''}")

    walk(app.routes, "")
    return found


def _process_alive(pid: int) -> bool:
    """Best-effort liveness check for a pid, without raising."""
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001 - psutil missing or refused; fall back
        return True  # assume alive: never delete on a failed check


def _prune_orphaned_basetemps(keep_pid: int) -> list[str]:
    """Delete ``basetemp-<pid>`` dirs whose owning process is gone.

    A per-process basetemp is what stops concurrent runs from racing on the
    directory wipe, but it also means nothing ever cleans up: each run leaves a
    directory behind forever. Measured on this repo, 98 abandoned runs had
    accumulated 4.7 GB under ``.cache/pytest`` and driven the volume to 0.15%
    free -- i.e. a naive per-process basetemp just relocates the original
    "grows without bound" problem.

    So each session reclaims the dirs of processes that are no longer running.
    Scope is deliberately narrow:

    * only immediate children of :data:`PYTEST_CACHE_ROOT` named
      ``basetemp-<digits>`` -- nothing else in the tree is ever a candidate;
    * only when the owning pid is provably gone (a recycled pid makes us skip,
      which merely leaves the dir for next time);
    * never the current run's own directory.

    Set ``NEXUS_PYTEST_KEEP_ORPHANED_BASETEMPS=1`` to disable.
    """
    if os.environ.get(KEEP_ORPHANED_BASETEMPS_ENV) == "1":
        return []
    removed: list[str] = []
    if not PYTEST_CACHE_ROOT.is_dir():
        return removed
    for entry in PYTEST_CACHE_ROOT.iterdir():
        if not entry.is_dir() or not entry.name.startswith("basetemp-"):
            continue
        suffix = entry.name[len("basetemp-") :]
        if not suffix.isdigit():
            continue
        pid = int(suffix)
        if pid == keep_pid or _process_alive(pid):
            continue
        try:
            shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue
        if not entry.exists():
            removed.append(entry.name)
    return removed


def _prune_old_basetemps(max_age_hours: float = 24.0) -> list[str]:
    """Remove ``basetemp-<pid>`` dirs older than *max_age_hours*.

    Catches dirs left behind by crashed/killed processes whose PID
    has since been recycled (so ``_process_alive`` lies), and general
    accumulation that the orphan prune misses. Never touches the
    current run's own directory.
    """
    removed: list[str] = []
    if not PYTEST_CACHE_ROOT.is_dir():
        return removed
    cutoff = time.time() - (max_age_hours * 3600)
    for entry in PYTEST_CACHE_ROOT.iterdir():
        if not entry.is_dir() or not entry.name.startswith("basetemp-"):
            continue
        suffix = entry.name[len("basetemp-"):]
        if not suffix.isdigit():
            continue
        pid = int(suffix)
        if pid == os.getpid():
            continue  # never prune current run's own dir
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if mtime > cutoff:
            continue
        try:
            shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue
        if not entry.exists():
            removed.append(entry.name)
    return removed


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Point ``--basetemp`` at a per-process directory under ``.cache/pytest``.

    Why this is not in ``addopts``: a single fixed ``--basetemp`` is not
    concurrency-safe. pytest wipes the whole basetemp at session start, so two
    concurrent runs (e.g. two agents, or CI plus a local run) race on that wipe
    and one dies with ``PermissionError: [WinError 32] ... is being used by
    another process``. That surfaced as ~65 spurious collection errors in
    ``backend/tests/api`` + ``backend/tests/core``.

    Why not the default (``%TEMP%\\pytest-of-<user>``): Windows antivirus and
    lock races made that location fail. ``.cache/pytest`` is project-local and
    untracked, so it keeps that property.

    An explicit ``--basetemp=...`` on the command line still wins, so ad-hoc
    runs remain possible. Orphaned directories from dead runs are reclaimed by
    :func:`_prune_orphaned_basetemps`, and dirs older than 24 h by
    :func:`_prune_old_basetemps`; together they keep this bounded.
    """
    if config.option.basetemp is not None:
        # Operator passed --basetemp explicitly; respect it verbatim.
        return
    PYTEST_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    reclaimed = _prune_orphaned_basetemps(pid)
    old_reclaimed = _prune_old_basetemps()
    for label, dirs in (("orphaned", reclaimed), ("aged", old_reclaimed)):
        if dirs:
            print(
                f"\n[conftest] reclaimed {len(dirs)} {label} pytest basetemp "
                f"dir(s): {', '.join(sorted(dirs)[:5])}"
                f"{' ...' if len(dirs) > 5 else ''}"
            )
    config.option.basetemp = str(PYTEST_CACHE_ROOT / f"basetemp-{pid}")



@pytest.fixture(autouse=True)
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch environment variables and clear the Settings cache.

    ``backend.config.settings.get_settings`` is ``@lru_cache``-d, so without
    clearing the cache a fixture-less test that runs first will poison the
    cache for later tests that use this fixture.
    """
    env = {
        "OLLAMA_HOST": "http://test-ollama:11434",
        "OLLAMA_DASHBOARD_HOST": "http://test-ollama-dash:11435",
        "REDIS_URL": "redis://test-redis:6379",
        "BRAVE_API_KEY": "test-key-123",
        "BACKEND_HOST": "127.0.0.1",
        "BACKEND_PORT": "9999",
        "LOG_LEVEL": "DEBUG",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://test-otel:4317",
        "PROMETHEUS_PORT": "9099",
        "JWT_SECRET": "test-jwt-secret-for-testing",
        "JWT_ALGORITHM": "HS256",
        # A TestClient lifespan must never start autonomous loops against the
        # developer worktree. Some of those loops create git checkpoints with
        # ``git add -A``, which made an ordinary test run commit unrelated
        # in-progress changes. Keep every background service fail-closed in
        # pytest; individual service tests instantiate their target directly.
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
        # Skip the expensive torch import (~3 s) during test Settings creation.
        "LOCAL_LLM_DEVICE": "cpu",
        # The per-run event journal writes JSONL under data/runs/; that is
        # production durability, not test output. Keep pytest off it.
        "NEXUS_EVENT_JOURNAL": "0",
        # The disk guard refuses to allocate a provider or write durable data
        # below a free-space floor. Production reads this from
        # NEXUS_DISK_GUARD_MIN_PERCENT (default 5.0%); pinning it to 0 here is
        # what makes the suite hermetic. Without this, a full developer disk
        # made ~14 tests fail with DiskPressureError from
        # orchestrator/engine.py, i.e. the suite reported the host's free space
        # instead of the code's correctness. Tests that assert the *guard's own*
        # contract pin the threshold explicitly (see tests/orchestrator/
        # test_disk_guard.py) so this global does not weaken them.
        "NEXUS_DISK_GUARD_MIN_PERCENT": "0",
        # Vibe/advanced-mode worker state is durable runtime state under
        # ``.nexus/`` by default. Leaving it there made every run of
        # ``test_chat_endpoint`` inherit the previous run's workers: a stale
        # ``turn_count`` of 9 and its history were restored, so the endpoint
        # test asserted against another run's state. Per-process scratch keeps
        # the suite hermetic and stops pytest writing into the worktree.
        "NEXUS_VIBE_STATE_ROOT": str(PYTEST_CACHE_ROOT / f"vibe-state-{os.getpid()}"),
        "NEXUS_ADVANCED_STATE_ROOT": str(PYTEST_CACHE_ROOT / f"advanced-state-{os.getpid()}"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr("backend.llm.factory._load_runtime_overrides", lambda: {})

    import backend.config.settings as settings_module

    settings_module._settings_instance = None
    cache_clear = getattr(settings_module.get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


@pytest.fixture
def models_yaml_dict() -> dict[str, Any]:
    """Parse the real models.yaml so tests validate against production config."""
    models_path = CONFIG_DIR / "models.yaml"
    with models_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture
def mock_redis() -> MagicMock:
    """Return a plain MagicMock; kept for backwards compatibility."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Ollama test doubles
# ---------------------------------------------------------------------------
def make_stream_response(tokens: Iterable[str]) -> httpx.Response:
    """Build a fake Ollama streaming response body from a sequence of tokens.

    The Ollama ``/api/chat`` endpoint returns newline-delimited JSON where each
    line contains a ``message.content`` increment and the final line has
    ``done: true``.
    """
    lines: list[str] = []
    for tok in tokens:
        lines.append(
            json.dumps(
                {
                    "message": {"role": "assistant", "content": tok},
                    "done": False,
                }
            )
        )
    lines.append(json.dumps({"done": True}))
    body = "\n".join(lines) + "\n"
    return httpx.Response(200, content=body.encode("utf-8"))


def make_single_response(content: str) -> httpx.Response:
    """Shortcut for a single-chunk completion (used by the router test)."""
    return make_stream_response([content])


@pytest.fixture
def ollama_tokens() -> list[str]:
    """Default stream of mock tokens. Override in individual tests as needed."""
    return ["Hello", ", ", "world", "!"]


@pytest.fixture
def ollama_client(ollama_tokens: list[str]) -> OllamaClient:
    """A real :class:`OllamaClient` wired to an in-process MockTransport.

    No network calls; the transport always returns the canned tokens.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return make_stream_response(ollama_tokens)

    transport = httpx.MockTransport(handler)
    return OllamaClient("http://mock", transport=transport)


# ---------------------------------------------------------------------------
# Test utilities
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_chat_request() -> dict[str, Any]:
    """Return a sample chat request for testing."""
    return {
        "message": "Hello, how are you?",
        "session_id": "test-session-123",
        "mode": "agent",
    }


@pytest.fixture
def sample_routing_decision() -> dict[str, Any]:
    """Return a sample routing decision for testing."""
    return {
        "primary_agent": "CODER",
        "secondary_agents": [],
        "requires_web_search": False,
        "thinking_mode": "fast",
        "estimated_complexity": 3,
        "task_type": "general",
        "context_needed": "low",
        "routing_confidence": 0.8,
        "routing_reason": "Test routing",
    }


class _InMemoryCache:
    """Drop-in replacement for CacheClient/SyncCacheClient used in tests.

    Avoids TCP connection attempts to Redis which add ~1-2 s per call when the
    server is not running.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ttl: int = 300) -> bool:
        self._store[key] = value
        return True

    async def delete(self, key: str) -> bool:
        self._store.pop(key, None)
        return True

    async def delete_pattern(self, pattern: str) -> int:
        matched = [k for k in self._store if pattern in k or k == pattern]
        for k in matched:
            self._store.pop(k, None)
        return len(matched)

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def close(self) -> None:
        self._store.clear()


class _InMemorySyncCache(_InMemoryCache):
    """Synchronous variant for sync_cache_result / sync cache helpers."""

    def get(self, key: str) -> str | None:  # type: ignore[override]
        return self._store.get(key)

    def set(self, key: str, value: str, ttl: int = 300) -> bool:  # type: ignore[override]
        self._store[key] = value
        return True

    def delete(self, key: str) -> bool:  # type: ignore[override]
        self._store.pop(key, None)
        return True

    def delete_pattern(self, pattern: str) -> int:  # type: ignore[override]
        matched = [k for k in self._store if pattern in k or k == pattern]
        for k in matched:
            self._store.pop(k, None)
        return len(matched)

    def exists(self, key: str) -> bool:  # type: ignore[override]
        return key in self._store

    def close(self) -> None:  # type: ignore[override]
        self._store.clear()


@pytest.fixture(autouse=True)
def mock_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace Redis cache clients with in-memory dicts for fast, isolated tests."""
    import backend.cache as cache_module

    mem_cache = _InMemoryCache()
    mem_sync_cache = _InMemorySyncCache()

    # Reset module-level singletons so each test starts with a clean cache
    cache_module._cache_client = mem_cache
    cache_module._sync_cache_client = mem_sync_cache

    monkeypatch.setattr(cache_module, "get_cache", lambda: mem_cache)
    monkeypatch.setattr(cache_module, "get_sync_cache", lambda: mem_sync_cache)


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the SQLite DB to a temporary file so tests are isolated."""
    db_file = tmp_path / "test_nexus.db"
    monkeypatch.setattr("backend.persistence.db.DB_PATH", db_file)
    monkeypatch.setattr("backend.persistence.db.MAX_POOL_SIZE", 100)
    from backend.persistence.db import close_pool, init_db

    close_pool()
    # Retry init_db on Windows: WAL/shm locks from a previous test's
    # connections may still be held by the OS briefly.
    for attempt in range(3):
        try:
            init_db()
            break
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    try:
        yield
    finally:
        # Checkpoint WAL before closing so the -wal/-shm files are
        # cleanly released and don't leave stale locks on Windows.
        try:
            from backend.persistence.db import get_connection_pool
            pool = get_connection_pool()
            if pool is not None:
                conn = pool.get_connection()
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    pool.return_connection(conn)
        except Exception:  # noqa: BLE001
            pass
        close_pool()
        gc.collect()
        # Windows needs time to release file handles on WAL/shm files.
        # Poll rather than a single short sleep.
        for _ in range(5):
            if not db_file.exists():
                break
            time.sleep(0.2)


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory with sample files.

    Returns the path to the temporary directory.
    """
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    # Create some sample files
    (project_dir / "main.py").write_text(
        "def main():\n    print('Hello, World!')\n", encoding="utf-8"
    )
    (project_dir / "README.md").write_text(
        "# Test Project\n\nThis is a test project.\n", encoding="utf-8"
    )

    # Create a subdirectory
    subdir = project_dir / "src"
    subdir.mkdir()
    (subdir / "utils.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello, {name}!'\n",
        encoding="utf-8",
    )

    return project_dir
