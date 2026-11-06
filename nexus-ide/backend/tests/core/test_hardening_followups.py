"""Regression tests for the confirmed hardening defects (audit 2026-10).

Each test names the defect it pins, so a regression points straight at the
code that has to be fixed:

* D1 — ``backend/core/workspace_shell.py::execute_python`` started the child
  interpreter with no ``env=``, so the REST route
  ``POST /api/workspace/execute_python`` handed the whole server environment
  (provider API keys, ``SECRET_KEY``) to model-supplied code.
* D2 — ``backend/sandbox/executor.py::_execute_subprocess`` merged
  ``os.environ`` into the child environment, so every caller of the executor
  leaked the server environment.
* D3 — ``backend/observability/log_store.py`` hard-coded the database file
  and ignored ``NEXUS_DB_PATH``: a relocated database split the data, with
  the structured logs always going to the repository copy.
* D4 — ``backend/knowledge/persistent_memory.py`` bound its path at import
  time, so the fixture that redirects ``backend.persistence.db.DB_PATH`` did
  not redirect it and the memories were written to the real database, even
  under pytest.
* D5 — the suite pinned a JWT secret shorter than the hardened minimum.
* D6 — ``.env.example`` shipped a secret that could be copied verbatim.
* D7 — the placeholder "ghost" sessions fabricated by a tool audit.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from backend.core.workspace_shell import execute_python
from backend.observability.log_store import LogStore
from backend.sandbox.executor import SandboxExecutor

#: The repository root (``.env.example`` lives there).
REPO_ROOT = Path(__file__).resolve().parents[3]

#: A credential-shaped variable name: the scrubber drops every variable whose
#: name looks like it carries a secret, so this one is a faithful probe.
CREDENTIAL_ENV_NAME = "OPENROUTER_API_KEY"

#: The value the probe expects to find in the child when the environment is
#: NOT scrubbed.  It must never show up in the output.
CREDENTIAL_VALUE = "sk-or-v1-THIS-VALUE-MUST-NEVER-REACH-THE-CHILD"

#: Program run by the child process.  ``os.environ`` is blocked by the
#: sandbox, but a single variable can be read with ``os.getenv`` — which is
#: exactly what an attacker would use to exfiltrate a key.
ENV_PROBE = (
    "import os\n"
    f"print('SECRET=' + os.getenv('{CREDENTIAL_ENV_NAME}', 'ABSENT'))\n"
    "print('VISIBLE=' + ('yes' if any(os.getenv(n) for n in "
    "('PATH', 'SYSTEMROOT', 'TEMP', 'TMP')) else 'no'))\n"
)


def _read_env_values(text: str) -> dict[str, str]:
    """Parse the ``KEY=value`` assignments of a dotenv body.

    Mirrors python-dotenv: comments are ignored and the last assignment of a
    name wins.
    """
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        values[key.strip()] = raw_value.strip()
    return values


# ---------------------------------------------------------------------------
# D1 — the workspace Python route must not leak the server environment
# ---------------------------------------------------------------------------


async def test_workspace_execute_python_environment_has_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``execute_python`` must run the child with a scrubbed environment.

    The REST route ``POST /api/workspace/execute_python`` runs model-supplied
    code.  Before the fix the child inherited the whole server environment,
    so ``os.getenv("OPENROUTER_API_KEY")`` returned the real key.
    """
    monkeypatch.setenv(CREDENTIAL_ENV_NAME, CREDENTIAL_VALUE)

    result = await execute_python(ENV_PROBE, cwd=str(tmp_path))

    assert result.get("returncode") == 0, result
    stdout = str(result.get("stdout", ""))
    assert CREDENTIAL_VALUE not in stdout, "the child process saw the server secret"
    assert "SECRET=ABSENT" in stdout, stdout
    # The environment is scrubbed, not emptied: the child still gets the
    # harmless variables it needs to run.
    assert "VISIBLE=yes" in stdout, stdout


# ---------------------------------------------------------------------------
# D2 — the sandbox executor must not leak the server environment
# ---------------------------------------------------------------------------


async def test_sandbox_executor_environment_has_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The sandbox executor's subprocess fallback must scrub the environment.

    Every caller of the executor (not only ``execute_code``) ran the
    model-supplied code with ``{**os.environ, **env}``, which handed over the
    provider API keys.
    """
    monkeypatch.setenv(CREDENTIAL_ENV_NAME, CREDENTIAL_VALUE)

    async def _docker_unavailable() -> bool:
        return False

    executor = SandboxExecutor()
    # Force the local fallback: the Docker path already runs the code inside
    # a container, this defect is in the subprocess path.
    monkeypatch.setattr(executor, "check_docker", _docker_unavailable)

    result = await executor.execute(
        ENV_PROBE,
        language="python",
        timeout=60,
        cwd=str(tmp_path),
    )

    assert result.exit_code == 0, result.stderr
    assert CREDENTIAL_VALUE not in result.stdout, "the child process saw the server secret"
    assert "SECRET=ABSENT" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# D3 — the structured log store must honour NEXUS_DB_PATH
# ---------------------------------------------------------------------------


async def test_log_store_honours_the_database_path_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A relocated database must receive the structured logs as well.

    The store used a hard-coded path, so the sessions went to the configured
    file while the structured logs always went to the repository copy.
    """
    relocated = tmp_path / "relocated.db"
    monkeypatch.setenv("NEXUS_DB_PATH", str(relocated))
    message = "structured log goes to the relocated database"

    store = LogStore()
    await store.insert("INFO", message)
    await store.drain(timeout=10)

    assert relocated.exists(), "the log store ignored NEXUS_DB_PATH"
    with closing(sqlite3.connect(str(relocated))) as conn:
        rows = conn.execute("SELECT message FROM structured_logs").fetchall()
    assert [row[0] for row in rows] == [message]

    # ...and nothing was written to the default database.
    from backend.persistence import db as persistence_db

    default_db = Path(persistence_db.DB_PATH)
    assert default_db != relocated
    with closing(sqlite3.connect(str(default_db))) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM structured_logs WHERE message = ?", (message,)
        ).fetchone()[0]
    assert count == 0, "the log was written to the default database as well"


# ---------------------------------------------------------------------------
# D4 — the persistent memory store must follow the database override
# ---------------------------------------------------------------------------


async def test_persistent_memory_honours_the_database_path_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The memories must land in the database the rest of the app uses.

    The path used to be bound at import time, so the fixture that redirects
    ``backend.persistence.db.DB_PATH`` did not redirect it and every memory
    was written to the real database — even under pytest.
    """
    from backend.knowledge import persistent_memory as pm_module
    from backend.knowledge.memory import EmbeddingService, MemoryType
    from backend.persistence import db as persistence_db

    db_file = Path(persistence_db.DB_PATH)

    service = EmbeddingService()

    async def _fast_embed(text: str) -> list[float]:
        return service._fallback_embed(text)

    monkeypatch.setattr(service, "embed", _fast_embed)

    store = pm_module.PersistentMemoryStore(embedding_service=service, max_memories=10)
    content = "the memory must land in the overridden database"
    memory = await store.store(content, memory_type=MemoryType.PROJECT, project_id="proj-1")

    with closing(sqlite3.connect(str(db_file))) as conn:
        rows = conn.execute(
            "SELECT content FROM persistent_memories WHERE id = ?", (memory.memory_id,)
        ).fetchall()
    assert [row[0] for row in rows] == [content], (
        "the memory was not written to the overridden database"
    )
    assert store.stats()["persistent_db"] == str(db_file)


# ---------------------------------------------------------------------------
# D5 — the suite's JWT secret must satisfy the hardened minimum
# ---------------------------------------------------------------------------


def test_the_test_jwt_secret_is_long_enough() -> None:
    """The pinned test secret must pass the production secret checks.

    The hardened settings refuse any secret shorter than
    ``MIN_SECRET_LENGTH``; the suite used to pin a 28-character value that
    only survived because of a narrow exemption in the settings module.
    """
    from backend.config import settings as settings_module

    secret = os.environ.get("JWT_SECRET", "")
    assert secret, "the suite must pin a JWT secret"
    assert len(secret) >= settings_module.MIN_SECRET_LENGTH, (
        f"the pinned test JWT secret is {len(secret)} characters; "
        f"{settings_module.MIN_SECRET_LENGTH} are required"
    )
    assert not settings_module.is_placeholder_secret(secret)
    assert settings_module.describe_secret_problem("JWT_SECRET", secret) is None


# ---------------------------------------------------------------------------
# D6 — .env.example must not ship a usable secret
# ---------------------------------------------------------------------------


def test_env_example_does_not_ship_a_usable_secret() -> None:
    """The example configuration must not contain a copy-and-paste secret.

    A published secret is a public secret: a token signed with it can be
    forged by anyone who can read the repository.  The hardened settings
    refuse to start with one, so the example has to ship an empty value and
    tell the operator how to generate a real one.
    """
    env_example = REPO_ROOT / ".env.example"
    text = env_example.read_text(encoding="utf-8")
    values = _read_env_values(text)

    for name in ("SECRET_KEY", "JWT_SECRET"):
        assert values.get(name, "") == "", (
            f"{name} must ship empty in .env.example, not {values.get(name)!r}"
        )

    # The value that used to be published must be gone for good.
    assert "change-this-secret-in-production-use-env-var" not in text
    assert "development-secret-key-change-in-production" not in text

    # ...and the operator must be told how to generate a real one.
    assert 'secrets.token_urlsafe(48)' in text


# ---------------------------------------------------------------------------
# D7 — the placeholder "ghost" sessions must be removable
# ---------------------------------------------------------------------------


def test_ghost_sessions_are_removed() -> None:
    """A session whose title is its id and that has no messages is a ghost.

    A tool audit inserted those placeholder rows for unknown session ids.
    They are not conversations, but they show up in the session list and in
    ``count_active_sessions()``.  The cleanup must remove them, leave every
    real session alone, and be idempotent.
    """
    from backend.observability.log_store import remove_ghost_sessions
    from backend.persistence import db as persistence_db

    db_file = Path(persistence_db.DB_PATH)
    ghost_id = "ghost-session-without-messages"
    titled_id = "session-titled-like-its-id"
    real_id = "a-real-session"

    with closing(sqlite3.connect(str(db_file))) as conn:
        conn.execute("INSERT INTO sessions (id, title) VALUES (?, ?)", (ghost_id, ghost_id))
        conn.execute("INSERT INTO sessions (id, title) VALUES (?, ?)", (titled_id, titled_id))
        conn.execute(
            "INSERT INTO sessions (id, title) VALUES (?, ?)", (real_id, "A real conversation")
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)",
            ("message-for-titled-session", titled_id, "user", "hello"),
        )
        conn.commit()

    removed = remove_ghost_sessions()
    assert removed == 1, "the ghost session (title = id, no messages) was not removed"

    # Idempotent: a second run has nothing left to remove.
    assert remove_ghost_sessions() == 0

    with closing(sqlite3.connect(str(db_file))) as conn:
        remaining = {
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM sessions WHERE id IN (?, ?, ?)",
                (ghost_id, titled_id, real_id),
            )
        }
    assert ghost_id not in remaining
    assert titled_id in remaining, "a session that has messages must never be removed"
    assert real_id in remaining
