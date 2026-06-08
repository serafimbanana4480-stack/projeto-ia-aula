"""Global pytest fixtures for the NEXUS IDE backend test suite."""

from __future__ import annotations

import json
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
        # Skip the expensive torch import (~3 s) during test Settings creation.
        "LOCAL_LLM_DEVICE": "cpu",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    from backend.config.settings import get_settings

    get_settings.cache_clear()


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
    from backend.persistence.db import init_db, close_pool

    close_pool()
    init_db()


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
