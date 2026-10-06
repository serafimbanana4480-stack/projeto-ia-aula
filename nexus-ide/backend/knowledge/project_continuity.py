"""Durable, compact continuity state scoped to one project.

The local SQLite journal is the source of truth. ``project-state.md`` is a
small, human-readable projection that is rebuilt from that journal; it is
never treated as authoritative over the current checkout.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_DIR = Path(".nexus")
DB_NAME = "project-continuity.sqlite3"
BRIEF_NAME = "project-state.md"
MAX_CONTEXT_CHARS = 4_000
MAX_EVENTS = 1_000
MAX_RETRIEVED_EVENTS = 3
RECOVERY_AFTER_SECONDS = 10 * 60
DECISION_REVIEW_AFTER_SECONDS = 90 * 24 * 60 * 60

WRITE_TOOLS = frozenset(
    {
        "write_file", "write_file_absolute", "edit_file", "append_file",
        "apply_patch", "delete_file", "scaffold_project", "format_code",
        "run_shell", "execute_code",
    }
)
TEST_TOOLS = frozenset({"run_tests", "run_lint", "type_check"})
_IGNORED_DIRS = frozenset(
    {
        ".git", ".nexus", ".venv", "venv", "node_modules", ".next", "__pycache__",
        ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".turbo",
        "dist", "build", "coverage", "tmp", "temp", "log", "logs",
    }
)
_GENERATED_DIRS = _IGNORED_DIRS | {"site-packages"}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(\b(?:api[_-]?key|token|password|secret)\b\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def _clean(value: Any, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redigido]", text)
    return text[:limit]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _tokens(value: str) -> set[str]:
    return {item.casefold() for item in re.findall(r"[^\W_]{3,}", value, flags=re.UNICODE)}


def _file_state(root: Path, relative: str) -> str:
    path = root / relative
    try:
        stat = path.stat()
        if path.is_file():
            return f"f:{stat.st_size}:{stat.st_mtime_ns}"
        if path.is_dir():
            return f"d:{stat.st_mtime_ns}"
    except OSError:
        return "missing"
    return "other"


def _is_internal_state_path(relative: str) -> bool:
    normalized = relative.replace("\\", "/").lstrip("./")
    return normalized == ".nexus" or normalized.startswith(".nexus/")


def _is_generated_path(relative: str) -> bool:
    parts = relative.replace("\\", "/").split("/")
    return any(
        part in _GENERATED_DIRS or part.startswith(".pytest_tmp")
        for part in parts
    )


def _scan_project_files(root: Path, file_states: dict[str, str], limit: int = 2_000) -> None:
    count = 0
    try:
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [
                name for name in sorted(dirs)
                if name not in _GENERATED_DIRS and not name.startswith(".pytest_tmp")
            ]
            for name in sorted(files):
                path = Path(current) / name
                relative = path.relative_to(root).as_posix()
                if _is_internal_state_path(relative) or _is_generated_path(relative):
                    continue
                file_states[relative] = _file_state(root, relative)
                count += 1
                if count >= limit:
                    return
    except OSError:
        logger.debug("Could not fully snapshot project %s", root, exc_info=True)


def capture_project_snapshot(
    project_path: str | os.PathLike[str],
    *,
    focus_paths: list[str] | tuple[str, ...] = (),
    include_tree: bool = True,
) -> dict[str, Any]:
    """Capture a bounded, read-only snapshot of the checkout and dirty files."""
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        return {
            "project": str(root), "exists": False, "fingerprint": "",
            "observed_at": time.time(), "changed_files": [], "file_states": {},
        }

    branch = ""
    head = ""
    changed_files: list[str] = []
    file_states: dict[str, str] = {}
    source = "filesystem"
    try:
        git_root_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
        if git_root_result.returncode != 0 or not git_root_result.stdout.strip():
            raise OSError("project has no Git worktree")
        git_root = Path(git_root_result.stdout.strip()).resolve()
        project_prefix = root.relative_to(git_root).as_posix().strip(".").strip("/")
        status = subprocess.run(
            [
                "git", "-C", str(git_root), "status", "--short", "--branch",
                "--untracked-files=all", "--", project_prefix or ".",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
        if status.returncode == 0:
            source = "git"
            lines = status.stdout.splitlines()
            if lines and lines[0].startswith("## "):
                branch = _clean(lines[0][3:], 160)
            for line in lines[1:]:
                if len(line) < 4:
                    continue
                relative = line[3:].strip().strip('"').replace("\\", "/")
                if project_prefix and relative.startswith(project_prefix + "/"):
                    relative = relative[len(project_prefix) + 1 :]
                elif project_prefix and relative != project_prefix:
                    continue
                if _is_internal_state_path(relative) or _is_generated_path(relative):
                    continue
                if relative:
                    changed_files.append(relative)
            head_result = subprocess.run(
                ["git", "-C", str(git_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
            )
            if head_result.returncode == 0:
                head = _clean(head_result.stdout, 80)
            for relative in changed_files[:2_000]:
                file_states[relative] = _file_state(root, relative)
    except (OSError, subprocess.SubprocessError, ValueError):
        source = "filesystem"

    if include_tree:
        _scan_project_files(root, file_states)
    for value in focus_paths[:24]:
        candidate = Path(value).expanduser()
        absolute = candidate if candidate.is_absolute() else root / candidate
        with suppress(OSError):
            absolute = absolute.resolve()
        try:
            relative = absolute.relative_to(root).as_posix()
        except ValueError:
            continue
        if relative and not _is_internal_state_path(relative):
            file_states[relative] = _file_state(root, relative)
    if source == "filesystem":
        changed_files = []

    material = _json(
        {
            "source": source,
            "branch": branch,
            "head": head,
            "files": sorted(file_states.items()),
        }
    )
    return {
        "project": str(root),
        "exists": True,
        "source": source,
        "branch": branch,
        "head": head,
        "changed_files": changed_files[:2_000],
        "file_states": file_states,
        "fingerprint": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "observed_at": time.time(),
    }


def _snapshot_brief(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key)
        for key in ("exists", "source", "branch", "head", "fingerprint", "observed_at")
    } | {"changed_files": list(snapshot.get("changed_files") or [])[:80]}


def _changed_since(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    old = before.get("file_states") or {}
    new = after.get("file_states") or {}
    changed = {path for path in set(old) | set(new) if old.get(path) != new.get(path)}
    return sorted(changed)[:200]


def _default_state(project_path: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_path": project_path,
        "project_goal": "",
        "current_task": None,
        "completed": [],
        "blocked": [],
        "recent_tasks": [],
        "last_session": None,
        "last_observed_snapshot": None,
        "last_verified_snapshot": None,
        "next_action": "Confirmar o objetivo e observar o estado real dos ficheiros.",
        "updated_at": time.time(),
    }


def _compact_task(task: dict[str, Any]) -> dict[str, Any]:
    compact = dict(task)
    for key in ("before_snapshot", "last_tool_snapshot", "after_snapshot"):
        compact.pop(key, None)
    compact["actions"] = list(compact.get("actions") or [])[:8]
    return compact


class ProjectContinuityStore:
    """Per-project durable state and bounded retrieval over a SQLite journal."""

    def __init__(self, project_path: str | os.PathLike[str]) -> None:
        self.root = Path(project_path).expanduser().resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(str(self.root))
        self.state_dir = self.root / STATE_DIR
        self.db_path = self.state_dir / DB_NAME
        self.brief_path = self.state_dir / BRIEF_NAME
        self.project_key = os.path.normcase(str(self.root))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS continuity_state (
                    project_key TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS continuity_events (
                    event_id TEXT PRIMARY KEY,
                    project_key TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    run_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_continuity_events_project_time
                    ON continuity_events(project_key, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_continuity_events_run
                    ON continuity_events(project_key, run_id, created_at);
                CREATE TABLE IF NOT EXISTS continuity_decisions (
                    decision_id TEXT PRIMARY KEY,
                    project_key TEXT NOT NULL,
                    decision_key TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    impact TEXT NOT NULL DEFAULT '',
                    evidence_paths_json TEXT NOT NULL DEFAULT '[]',
                    evidence_fingerprints_json TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL DEFAULT 0.7,
                    source TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    superseded_by TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_continuity_decisions_project
                    ON continuity_decisions(project_key, status, updated_at DESC);
                """
            )
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(continuity_decisions)")
            }
            if "evidence_fingerprints_json" not in columns:
                conn.execute(
                    "ALTER TABLE continuity_decisions ADD COLUMN evidence_fingerprints_json TEXT NOT NULL DEFAULT '{}'"
                )
            conn.commit()

    def _state(self, conn: sqlite3.Connection) -> dict[str, Any]:
        row = conn.execute(
            "SELECT state_json FROM continuity_state WHERE project_key = ?",
            (self.project_key,),
        ).fetchone()
        if not row:
            return _default_state(str(self.root))
        try:
            state = json.loads(row["state_json"])
            return state if isinstance(state, dict) else _default_state(str(self.root))
        except (TypeError, json.JSONDecodeError):
            return _default_state(str(self.root))

    def _save_state(self, conn: sqlite3.Connection, state: dict[str, Any]) -> None:
        state["updated_at"] = time.time()
        conn.execute(
            """INSERT INTO continuity_state(project_key, state_json, updated_at)
               VALUES (?, ?, ?) ON CONFLICT(project_key) DO UPDATE SET
               state_json=excluded.state_json, updated_at=excluded.updated_at""",
            (self.project_key, _json(state), state["updated_at"]),
        )

    def _event(
        self,
        conn: sqlite3.Connection,
        *,
        event_type: str,
        content: str,
        status: str = "",
        session_id: str = "",
        run_id: str = "",
        payload: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> str:
        event_id = uuid.uuid4().hex
        at = created_at if created_at is not None else time.time()
        conn.execute(
            """INSERT INTO continuity_events
               (event_id, project_key, session_id, run_id, event_type, status,
                content, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, self.project_key, _clean(session_id, 128), _clean(run_id, 128),
                _clean(event_type, 48), _clean(status, 48), _clean(content, 500),
                _json(payload or {}), at,
            ),
        )
        conn.execute(
            """DELETE FROM continuity_events WHERE project_key = ? AND event_id IN (
                   SELECT event_id FROM continuity_events WHERE project_key = ?
                   ORDER BY created_at DESC LIMIT -1 OFFSET ?
               )""",
            (self.project_key, self.project_key, MAX_EVENTS),
        )
        return event_id

    @staticmethod
    def _run_record(run_id: str) -> dict[str, Any]:
        if not run_id:
            return {}
        try:
            from backend.persistence.db import get_session_run

            return get_session_run(run_id) or {}
        except Exception:
            return {}

    def begin_run(
        self,
        *,
        session_id: str,
        run_id: str,
        objective: str,
        snapshot: dict[str, Any] | None = None,
        model: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        """Persist the pre-change checkpoint and current task before model work."""
        stamp = now if now is not None else time.time()
        observed = snapshot or capture_project_snapshot(self.root)
        objective = _clean(objective, 600)
        with self._connect() as conn:
            state = self._state(conn)
            prior = state.get("current_task")
            if isinstance(prior, dict) and prior.get("run_id") != run_id:
                age = stamp - float(prior.get("updated_at") or stamp)
                if prior.get("status") in {"in_progress", "started", "awaiting_verification"}:
                    stored_run = self._run_record(str(prior.get("run_id") or ""))
                    stored_run_status = str(stored_run.get("status") or "")
                    if stored_run_status == "running":
                        prior_status = "in_progress"
                    elif stored_run_status == "completed":
                        # A crash may have landed after the durable run row but
                        # before the project journal. Reconcile from live files
                        # and tests; never infer completion from the row alone.
                        prior_status = "awaiting_verification"
                    elif stored_run_status in {"interrupted", "cancelled", "failed"}:
                        prior_status = "interrupted" if stored_run_status == "interrupted" else "paused"
                    elif age >= RECOVERY_AFTER_SECONDS:
                        prior_status = "interrupted"
                    else:
                        prior_status = "paused"
                    prior["status"] = prior_status
                    prior["updated_at"] = stamp
                    prior["next_action"] = (
                        "Reabrir o projeto, confirmar as alterações e retomar do último checkpoint."
                        if prior_status == "interrupted"
                        else "Retomar ou fechar esta tarefa depois de confirmar o estado real."
                    )
                    state["recent_tasks"] = [_compact_task(prior), *(state.get("recent_tasks") or [])][:8]
                    self._event(
                        conn,
                        event_type="task_recovery",
                        status=prior_status,
                        content=f"Tarefa anterior sem fecho confirmado: {prior.get('objective', '')}",
                        session_id=session_id,
                        run_id=str(prior.get("run_id") or ""),
                        payload={"age_seconds": max(0, int(age)), "snapshot": _snapshot_brief(observed)},
                        created_at=stamp,
                    )
                    if stored_run_status == "failed" and stored_run.get("error"):
                        failure = _clean(stored_run.get("error"), 220)
                        state["blocked"] = [
                            {
                                "objective": prior.get("objective", ""),
                                "problem": failure,
                                "at": stamp,
                                "run_id": prior.get("run_id", ""),
                            },
                            *(state.get("blocked") or []),
                        ][:8]
                        self._event(
                            conn,
                            event_type="failure",
                            status="failed",
                            content=f"Falha recuperada do run anterior: {failure}",
                            session_id=session_id,
                            run_id=str(prior.get("run_id") or ""),
                            payload={"recovered_from_session_run": True},
                            created_at=stamp,
                        )

            resume = bool(
                isinstance(prior, dict)
                and prior.get("status") in {"paused", "interrupted", "awaiting_verification", "blocked"}
                and re.search(r"\b(continua|continuar|retoma|retomar|resume|pick up)\b", objective, re.I)
            )
            task_objective = (
                str(prior.get("objective") or objective)
                if resume and isinstance(prior, dict)
                else objective
            )
            if resume and isinstance(prior, dict):
                previous = [
                    item for item in state.get("recent_tasks", [])
                    if not isinstance(item, dict) or item.get("run_id") != prior.get("run_id")
                ]
                state["recent_tasks"] = [_compact_task(prior), *previous][:8]
            else:
                state["recent_tasks"] = [
                    item for item in state.get("recent_tasks", [])
                    if isinstance(item, dict) and item.get("run_id") != run_id
                ][:8]
            state["current_task"] = {
                "run_id": run_id,
                "session_id": session_id,
                "objective": task_objective,
                "resume_prompt": objective if resume else "",
                "status": "in_progress",
                "started_at": stamp,
                "updated_at": stamp,
                "model": _clean(model, 128),
                "before_snapshot": observed,
                "changed_files": [],
                "actions": [],
                "verification": {"status": "not_run"},
            }
            state["last_observed_snapshot"] = _snapshot_brief(observed)
            state["last_session"] = {
                "session_id": session_id,
                "run_id": run_id,
                "started_at": stamp,
                "status": "in_progress",
                "model": _clean(model, 128),
                "objective": task_objective,
            }
            state["next_action"] = "Inspecionar os ficheiros relevantes e validar a memória contra o checkout atual."
            self._event(
                conn,
                event_type="checkpoint_before",
                status="in_progress",
                content=f"Início: {task_objective}",
                session_id=session_id,
                run_id=run_id,
                payload={"snapshot": _snapshot_brief(observed), "model": _clean(model, 128)},
                created_at=stamp,
            )
            self._save_state(conn, state)
        self._write_brief()
        return state

    def record_tool_event(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_name: str,
        phase: str,
        ok: bool | None = None,
        args: dict[str, Any] | None = None,
        result: Any = None,
        error: str = "",
    ) -> None:
        """Record an action/checkpoint without persisting raw arguments or output."""
        name = _clean(tool_name, 80)
        phase = phase.casefold()
        is_write = name in WRITE_TOOLS or any(name.endswith(f".{tool}") for tool in WRITE_TOOLS)
        is_test = name in TEST_TOOLS or any(name.endswith(f".{tool}") for tool in TEST_TOOLS)
        args = args if isinstance(args, dict) else {}
        paths = self._paths(args)
        focused_snapshot = bool(paths) and name not in {"run_shell", "execute_code"}
        snapshot = (
            capture_project_snapshot(
                self.root,
                focus_paths=paths,
                include_tree=not focused_snapshot,
            )
            if is_write
            else None
        )

        with self._connect() as conn:
            state = self._state(conn)
            task = state.get("current_task")
            if not isinstance(task, dict) or task.get("run_id") != run_id:
                task = None
            if phase in {"call", "started", "before"}:
                if task is not None:
                    task["last_tool_snapshot"] = snapshot
                    baseline = task.get("before_snapshot") or {}
                    baseline_files = baseline.setdefault("file_states", {})
                    snapshot_files = (snapshot or {}).get("file_states") or {}
                    for path in paths:
                        if (
                            isinstance(snapshot_files, dict)
                            and path not in baseline_files
                            and path in snapshot_files
                        ):
                            baseline_files[path] = snapshot_files[path]
                    task["before_snapshot"] = baseline
                    task["updated_at"] = time.time()
                    task["actions"] = [
                        {"tool": name, "status": "started", "paths": paths, "at": time.time()},
                        *(task.get("actions") or []),
                    ][:12]
                event_type = "checkpoint_before" if is_write else "action_started"
                content = f"{name} iniciado" + (f" em {', '.join(paths)}" if paths else "")
                self._event(
                    conn,
                    event_type=event_type,
                    status="started",
                    content=content,
                    session_id=session_id,
                    run_id=run_id,
                    payload={"paths": paths, "snapshot": _snapshot_brief(snapshot) if snapshot else None},
                )
                self._save_state(conn, state)
            else:
                succeeded = bool(ok)
                after = snapshot
                before = (task or {}).get("last_tool_snapshot") or {}
                changed = _changed_since(before, after) if is_write and after else []
                if task is not None:
                    task["updated_at"] = time.time()
                    task["last_tool_snapshot"] = None
                    task["actions"] = [
                        {
                            "tool": name,
                            "status": "completed" if succeeded else "failed",
                            "paths": changed or paths,
                            "at": time.time(),
                        },
                        *(task.get("actions") or []),
                    ][:12]
                    if succeeded and is_write:
                        task["declared_changed_files"] = sorted(
                            set(task.get("declared_changed_files") or []) | set(changed)
                        )[:200]
                        task["changed_files"] = sorted(
                            set(task.get("changed_files") or []) | set(changed)
                        )[:200]
                if is_test:
                    verified = self._verification_result(result, succeeded, error)
                    if task is not None and verified["status"] != "unknown":
                        task["verification"] = verified
                if not succeeded or (is_test and task and task.get("verification", {}).get("status") == "failed"):
                    approach = name + (f" em {', '.join(changed or paths)}" if changed or paths else "")
                    failure = _clean(error or self._result_error(result) or "resultado falhado", 220)
                    self._event(
                        conn,
                        event_type="failure",
                        status="failed",
                        content=f"Tentativa {approach}: {failure}",
                        session_id=session_id,
                        run_id=run_id,
                        payload={"tool": name, "paths": changed or paths, "approach_attempted": approach},
                    )
                    if task is not None:
                        state["blocked"] = [
                            {
                                "objective": task.get("objective", ""),
                                "problem": f"{name}: {_clean(error or self._result_error(result) or 'falhou', 180)}",
                                "at": time.time(),
                                "run_id": run_id,
                            },
                            *(state.get("blocked") or []),
                        ][:8]
                        state["next_action"] = (
                            "Ler a falha e confirmar o código atual antes de repetir a abordagem."
                        )
                else:
                    self._event(
                        conn,
                        event_type="checkpoint_after" if is_write else ("verification" if is_test else "action_result"),
                        status=(task or {}).get("verification", {}).get("status", "completed" if succeeded else "failed"),
                        content=(
                            f"{name} terminou" + (f"; alterados: {', '.join(changed)}" if changed else "")
                        ),
                        session_id=session_id,
                        run_id=run_id,
                        payload={
                            "paths": changed or paths,
                            "snapshot": _snapshot_brief(after) if after else None,
                            "verification": (task or {}).get("verification", {}) if is_test else None,
                            "result_summary": self._result_summary(result),
                        },
                    )
                self._save_state(conn, state)
        if is_write:
            self._write_brief()

    @staticmethod
    def _result_error(result: Any) -> str:
        if isinstance(result, dict):
            return str(result.get("error") or result.get("message") or "")
        return ""

    @staticmethod
    def _result_summary(result: Any) -> str:
        if not isinstance(result, dict):
            return ""
        for key in ("summary", "message", "status", "state"):
            value = result.get(key)
            if value:
                return _clean(value, 180)
        return ""

    @staticmethod
    def _verification_result(result: Any, tool_ok: bool, error: str) -> dict[str, Any]:
        if not tool_ok:
            return {"status": "failed", "summary": _clean(error or "ferramenta de validação falhou", 180)}
        if not isinstance(result, dict):
            text = _clean(result, 180)
            if re.search(r"\b(failed|failure|failures|error|errors|falhou|falharam)\b", text, re.I):
                return {"status": "failed", "summary": text}
            if re.search(r"\b(passed|success|passed|passaram|passou)\b", text, re.I):
                return {"status": "passed", "summary": text}
            return {"status": "unknown", "summary": "resultado sem estado verificável"}
        explicit = result.get("ok", result.get("success", result.get("passed")))
        if isinstance(explicit, bool):
            status = "passed" if explicit else "failed"
            return {"status": status, "summary": _clean(result.get("summary") or result.get("message"), 180)}
        label = str(result.get("status") or result.get("state") or "").casefold()
        if label in {"passed", "pass", "success", "completed"}:
            return {"status": "passed", "summary": _clean(result.get("summary") or label, 180)}
        if label in {"failed", "fail", "error"}:
            return {"status": "failed", "summary": _clean(result.get("summary") or label, 180)}
        text = _clean(result.get("summary") or result.get("result") or result.get("message"), 180)
        if re.search(r"\b(failed|failure|failures|error|errors|falhou|falharam)\b", text, re.I):
            return {"status": "failed", "summary": text}
        if re.search(r"\b(passed|success|passaram|passou)\b", text, re.I):
            return {"status": "passed", "summary": text}
        return {"status": "unknown", "summary": "resultado sem estado verificável"}

    def _paths(self, args: dict[str, Any]) -> list[str]:
        candidates: list[Any] = []
        for key in ("path", "file_path", "target", "paths", "files"):
            value = args.get(key)
            if isinstance(value, list):
                candidates.extend(value)
            elif value:
                candidates.append(value)
        normalized = [self._relative_path(str(item)) for item in candidates[:12] if str(item).strip()]
        return [_clean(item, 180) for item in normalized if item]

    def finish_run(
        self,
        *,
        session_id: str,
        run_id: str,
        status: str,
        verification: dict[str, Any] | None = None,
        changed_files: list[str] | tuple[str, ...] = (),
        tools: list[str] | tuple[str, ...] = (),
        error: str = "",
        answer_summary: str = "",
        model: str = "",
        snapshot: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Persist the after checkpoint and only mark changes done with evidence."""
        stamp = now if now is not None else time.time()
        if snapshot is None:
            with self._connect() as conn:
                current = self._state(conn).get("current_task") or {}
            focus_paths = [
                *list(changed_files),
                *list(current.get("declared_changed_files") or []),
            ]
            after = capture_project_snapshot(self.root, focus_paths=focus_paths)
        else:
            after = snapshot
        provided_verification = verification
        with self._connect() as conn:
            state = self._state(conn)
            task = state.get("current_task")
            if not isinstance(task, dict) or task.get("run_id") != run_id:
                return None
            if provided_verification is None:
                recorded_verification = task.get("verification") or {}
                recorded_status = recorded_verification.get("status")
                verification = {
                    "ran": recorded_status in {"passed", "failed"},
                    "ok": recorded_status == "passed",
                    "summary": recorded_verification.get("summary", ""),
                    "command": recorded_verification.get("command", ""),
                }
            else:
                verification = dict(provided_verification)
            before = task.get("before_snapshot") or {}
            actual_changes = _changed_since(before, after)
            reported_changes = {
                self._relative_path(str(item))
                for item in [*changed_files, *(task.get("declared_changed_files") or [])]
                if str(item).strip()
            }
            observed_and_declared = sorted(set(actual_changes) & reported_changes)
            verified = bool(
                verification.get("ran")
                and verification.get("ok")
                and observed_and_declared
            )
            failed_verification = bool(verification.get("ran") and not verification.get("ok"))
            if status == "completed" and verified:
                task_status = "verified"
            elif failed_verification or status == "failed":
                task_status = "blocked"
            elif status in {"interrupted", "cancelled"}:
                task_status = "interrupted" if status == "interrupted" else "paused"
            elif actual_changes or reported_changes:
                task_status = "awaiting_verification"
            else:
                task_status = "completed_read_only" if status == "completed" else status
            task.update(
                {
                    "status": task_status,
                    "updated_at": stamp,
                    "changed_files": actual_changes,
                    "reported_changed_files": sorted(reported_changes)[:200],
                    "change_evidence": "filesystem_snapshot" if actual_changes else "not_observed",
                    "verification": {
                        "status": "passed" if verified else "failed" if failed_verification else "not_run",
                        "summary": _clean(verification.get("summary"), 180),
                        "command": _clean(verification.get("command"), 180),
                        "ran": bool(verification.get("ran")),
                    },
                    "tools": [_clean(item, 80) for item in tools[-12:]],
                    "error": _clean(error, 220),
                    "answer_summary_unverified": _clean(answer_summary, 220),
                    "model": _clean(model or task.get("model"), 128),
                    "after_snapshot": _snapshot_brief(after),
                }
            )
            task.pop("before_snapshot", None)
            task.pop("last_tool_snapshot", None)
            state["last_observed_snapshot"] = _snapshot_brief(after)
            state["verification_stale"] = bool(
                state.get("last_verified_snapshot")
                and state["last_verified_snapshot"].get("fingerprint") != after.get("fingerprint")
            )
            state["last_session"] = {
                "session_id": session_id,
                "run_id": run_id,
                "started_at": (state.get("last_session") or {}).get("started_at", stamp),
                "ended_at": stamp,
                "status": status,
                "model": _clean(model or task.get("model"), 128),
                "objective": task.get("objective", ""),
                "tools": task["tools"],
            }
            if task_status == "verified":
                state["completed"] = [
                    {
                        "objective": task.get("objective", ""),
                        "verified_at": stamp,
                        "verification": task["verification"],
                        "snapshot_fingerprint": after.get("fingerprint"),
                        "changed_files": actual_changes,
                    },
                    *(state.get("completed") or []),
                ][:8]
                state["last_verified_snapshot"] = _snapshot_brief(after)
                state["verification_stale"] = False
                state["blocked"] = [
                    item for item in state.get("blocked", [])
                    if not _similar(str(item.get("objective", "")), str(task.get("objective", "")))
                ][:8]
                state["next_action"] = "Reconfirmar este resultado se o checkout mudar antes da próxima tarefa."
            elif task_status == "blocked":
                issue = _clean(error or verification.get("summary") or "A validação falhou.", 220)
                state["blocked"] = [
                    {"objective": task.get("objective", ""), "problem": issue, "at": stamp, "run_id": run_id},
                    *(state.get("blocked") or []),
                ][:8]
                state["next_action"] = "Inspecionar a falha registada, alterar a abordagem e voltar a validar."
                self._event(
                    conn,
                    event_type="failure",
                    status="failed",
                    content=f"{task.get('objective', '')}: {issue}",
                    session_id=session_id,
                    run_id=run_id,
                    payload={"verification": task["verification"], "changed_files": actual_changes},
                    created_at=stamp,
                )
            elif task_status == "awaiting_verification":
                state["next_action"] = (
                    "Verificar as alterações observadas antes de afirmar que a tarefa ficou concluída."
                    if actual_changes
                    else "O tool reportou uma alteração que o snapshot não confirmou; inspecionar o ficheiro e validar."
                )
            elif task_status == "interrupted":
                state["next_action"] = "Comparar o checkout com o checkpoint e retomar sem repetir alterações já presentes."
            elif task_status == "paused":
                state["next_action"] = "Confirmar o estado atual antes de retomar ou fechar a tarefa."
            else:
                state["next_action"] = "Usar o estado real do projeto para escolher a próxima ação."
            event_type = "checkpoint_after" if actual_changes else "run_finished"
            self._event(
                conn,
                event_type=event_type,
                status=task_status,
                content=f"{task_status}: {task.get('objective', '')}",
                session_id=session_id,
                run_id=run_id,
                payload={
                    "changed_files": actual_changes,
                    "verification": task["verification"],
                    "snapshot": _snapshot_brief(after),
                    "tools": task["tools"],
                    "answer_summary_unverified": task["answer_summary_unverified"],
                },
                created_at=stamp,
            )
            state["current_task"] = task
            self._save_state(conn, state)
        self._write_brief()
        return task

    def record_decision(
        self,
        *,
        decision_key: str,
        decision: str,
        rationale: str,
        impact: str,
        session_id: str = "",
        run_id: str = "",
        source: str = "agent_memory_tool",
        evidence_paths: list[str] | tuple[str, ...] = (),
        confidence: float = 0.75,
    ) -> str:
        """Store an explicit project decision and supersede the old same-key record."""
        key = _clean(decision_key, 100).casefold()
        if not key:
            raise ValueError("decision_key is required to replace a prior decision safely")
        decision_id = uuid.uuid4().hex
        stamp = time.time()
        paths = [self._relative_path(item) for item in evidence_paths[:12] if str(item).strip()]
        fingerprints = {path: _file_state(self.root, path) for path in paths if path}
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE continuity_decisions SET status='superseded', superseded_by=?, updated_at=?
                   WHERE project_key=? AND decision_key=? AND status IN ('active','needs_review')""",
                (decision_id, stamp, self.project_key, key),
            )
            conn.execute(
                """INSERT INTO continuity_decisions
                   (decision_id, project_key, decision_key, decision, rationale, impact,
                    evidence_paths_json, evidence_fingerprints_json, confidence, source,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (
                    decision_id, self.project_key, key, _clean(decision, 300),
                    _clean(rationale, 300), _clean(impact, 300), _json(paths), _json(fingerprints),
                    max(0.0, min(1.0, confidence)), _clean(source, 80), stamp, stamp,
                ),
            )
            self._event(
                conn,
                event_type="decision",
                status="active",
                content=f"{_clean(decision, 180)} | motivo: {_clean(rationale, 120)} | impacto: {_clean(impact, 120)}",
                session_id=session_id,
                run_id=run_id,
                payload={"decision_key": key, "evidence_paths": paths, "source": source},
                created_at=stamp,
            )
            self._save_state(conn, self._state(conn))
        self._write_brief()
        return decision_id

    def _relative_path(self, value: str) -> str:
        candidate = Path(value).expanduser()
        absolute = candidate if candidate.is_absolute() else self.root / candidate
        with suppress(OSError):
            absolute = absolute.resolve()
        try:
            return absolute.relative_to(self.root).as_posix()
        except ValueError:
            return ""

    def bootstrap_context(
        self,
        query: str,
        *,
        snapshot: dict[str, Any] | None = None,
        now: float | None = None,
        max_chars: int = MAX_CONTEXT_CHARS,
    ) -> str:
        """Reconcile durable notes with the real checkout and return a small brief."""
        stamp = now if now is not None else time.time()
        observed = snapshot or capture_project_snapshot(self.root)
        with self._connect() as conn:
            state = self._state(conn)
            state["last_observed_snapshot"] = _snapshot_brief(observed)
            rows = conn.execute(
                "SELECT * FROM continuity_decisions WHERE project_key=? AND status IN ('active','needs_review') ORDER BY updated_at DESC LIMIT 100",
                (self.project_key,),
            ).fetchall()
            decisions: list[dict[str, Any]] = []
            for row in rows:
                paths = json.loads(row["evidence_paths_json"] or "[]")
                fingerprints = json.loads(row["evidence_fingerprints_json"] or "{}")
                status = row["status"]
                evidence_changed = any(
                    _file_state(self.root, path) != fingerprints.get(path)
                    for path in paths
                    if path in fingerprints
                )
                expired = (
                    stamp - float(row["created_at"]) > DECISION_REVIEW_AFTER_SECONDS
                    and status == "active"
                )
                if evidence_changed or expired:
                    status = "needs_review"
                    conn.execute(
                        "UPDATE continuity_decisions SET status='needs_review', updated_at=? WHERE decision_id=?",
                        (stamp, row["decision_id"]),
                    )
                decisions.append(
                    {
                        "key": row["decision_key"], "decision": row["decision"],
                        "rationale": row["rationale"], "impact": row["impact"],
                        "status": status, "confidence": float(row["confidence"]),
                        "created_at": float(row["created_at"]), "evidence_paths": paths,
                    }
                )
            state["verification_stale"] = bool(
                state.get("last_verified_snapshot")
                and state["last_verified_snapshot"].get("fingerprint") != observed.get("fingerprint")
            )
            state["updated_at"] = stamp
            self._save_state(conn, state)
            event_rows = conn.execute(
                "SELECT * FROM continuity_events WHERE project_key=? ORDER BY created_at DESC LIMIT 100",
                (self.project_key,),
            ).fetchall()
            event_rows = list(event_rows)
        self._write_brief()
        return self._render_context(state, observed, decisions, event_rows, query, max_chars)

    def _render_context(
        self,
        state: dict[str, Any],
        snapshot: dict[str, Any],
        decisions: list[dict[str, Any]],
        event_rows: list[sqlite3.Row],
        query: str,
        max_chars: int,
    ) -> str:
        task = state.get("current_task") or {}
        lines = [
            "PROJECT CONTINUITY (dados históricos compactos; confirma tudo no checkout atual):",
            f"PROJECT: {self.root}",
            f"OBJECTIVO: {_clean(state.get('project_goal') or task.get('objective') or 'não registado', 260)}",
        ]
        snapshot_label = "não disponível"
        if snapshot.get("exists"):
            snapshot_label = f"{snapshot.get('source', 'filesystem')} · branch={snapshot.get('branch') or 'desconhecida'}"
            if snapshot.get("head"):
                snapshot_label += f" · HEAD={str(snapshot['head'])[:12]}"
            if snapshot.get("source") == "git":
                dirty = snapshot.get("changed_files") or []
                snapshot_label += f" · alterações presentes={len(dirty)}"
                if dirty:
                    lines.append("FICHEIROS ALTERADOS NO CHECKOUT: " + ", ".join(dirty[:8]))
            else:
                snapshot_label += " · snapshot local sem Git"
        lines.append(f"ESTADO ATUAL: observado agora: {snapshot_label}.")
        if state.get("project_goal") and task.get("objective"):
            lines.append(f"OBJETIVO DA TAREFA: {_clean(task.get('objective'), 220)}")
        current_status = str(task.get("status") or "sem tarefa em curso")
        if current_status == "awaiting_verification":
            current_status = "alterações por verificar"
        elif current_status == "interrupted":
            current_status = "interrompida; recuperar do checkpoint"
        elif current_status == "blocked":
            current_status = "bloqueada por falha"
        lines.append(f"TAREFA ATUAL: {current_status} — {_clean(task.get('objective'), 220)}")

        query_terms = _tokens(query)
        completed = sorted(
            state.get("completed") or [],
            key=lambda item: _relevance(
                query_terms,
                str(item.get("objective") or ""),
                float(item.get("verified_at") or 0),
            ),
            reverse=True,
        )
        if completed:
            lines.append("O QUE JÁ FOI FEITO (só validações explícitas):")
            for item in completed[:3]:
                stale = state.get("verification_stale") or (
                    item.get("snapshot_fingerprint") != snapshot.get("fingerprint")
                )
                label = "verificado anteriormente; checkout mudou, confirmar" if stale else "verificado"
                lines.append(f"- {label}: {_clean(item.get('objective'), 180)}")
        else:
            lines.append("O QUE JÁ FOI FEITO: sem conclusão de código validada registada.")

        if task.get("status") in {"in_progress", "started", "awaiting_verification", "interrupted", "paused"}:
            lines.append("EM CURSO: " + _clean(task.get("objective"), 220))
        actions = task.get("actions") or []
        if actions:
            lines.append("AÇÕES DA SESSÃO ATUAL:")
            for item in actions[:3]:
                target = ", ".join(item.get("paths") or [])
                lines.append(
                    f"- {item.get('status')}: {item.get('tool')}"
                    + (f" ({_clean(target, 140)})" if target else "")
                )
        resumable = [
            item for item in state.get("recent_tasks", [])
            if isinstance(item, dict)
            and item.get("status") in {"in_progress", "started", "awaiting_verification", "interrupted", "paused", "blocked"}
        ][:2]
        if resumable:
            lines.append("TAREFAS A RETOMAR OU VALIDAR:")
            for item in resumable:
                lines.append(f"- {item.get('status')}: {_clean(item.get('objective'), 180)}")
        blocked = sorted(
            state.get("blocked") or [],
            key=lambda item: _relevance(
                query_terms,
                f"{item.get('objective', '')} {item.get('problem', '')}",
                float(item.get("at") or 0),
            ),
            reverse=True,
        )
        if blocked:
            lines.append("BLOQUEIOS: " + " | ".join(
                _clean(item.get("problem"), 160) for item in blocked[:2]
            ))
        risks: list[str] = []
        if state.get("verification_stale"):
            risks.append("o checkout mudou desde a última validação registada")
        if task.get("status") == "awaiting_verification":
            risks.append("há alterações sem verificação final")
        if task.get("status") in {"interrupted", "paused"}:
            risks.append("a tarefa anterior não tem fecho confirmado")
        if risks:
            lines.append("RISCOS: " + " | ".join(risks))

        ranked_decisions = sorted(
            decisions,
            key=lambda item: _relevance(query_terms, " ".join(
                str(item.get(key) or "") for key in ("decision", "rationale", "impact", "key")
            ), float(item.get("created_at") or 0)),
            reverse=True,
        )
        chosen_decisions = ranked_decisions[:2]
        if chosen_decisions:
            lines.append("DECISÕES IMPORTANTES (registo histórico; validar com o código atual):")
            for item in chosen_decisions:
                label = "rever" if item["status"] == "needs_review" else "registada"
                lines.append(
                    f"- [{label}; confiança {item['confidence']:.2f}] {item['decision']} "
                    f"| motivo: {item['rationale']} | impacto: {item['impact']}"
                )

        relevant_events = self._relevant_events(event_rows, query_terms)
        failures = [item for item in relevant_events if item["event_type"] == "failure"]
        if failures:
            lines.append("FALHAS E TENTATIVAS ANTERIORES (não repetir sem mudança e nova verificação):")
            for item in failures[:MAX_RETRIEVED_EVENTS]:
                lines.append(f"- {_clean(item['content'], 220)}")

        next_action = state.get("next_action") or "Inspecionar o código relevante antes de agir."
        if state.get("verification_stale"):
            next_action = "O checkout mudou desde a última validação: confirmar os ficheiros e repetir a verificação relevante."
        lines.append(f"PRÓXIMA AÇÃO: {_clean(next_action, 260)}")
        last = state.get("last_session") or {}
        if last:
            when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(float(last.get("ended_at") or last.get("started_at") or 0)))
            lines.append(
                f"ÚLTIMA SESSÃO: {when} · estado={_clean(last.get('status'), 32)} "
                f"· modelo={_clean(last.get('model') or 'não indicado', 80)}"
            )
        lines.append(
            "REGRA: estado do código, diffs e testes atuais prevalecem; antes de escrever, "
            "inspeciona o alvo e compara-o com as ações registadas. Memória antiga nunca prova funcionamento."
        )
        return "\n".join(lines)[: max(1, max_chars)]

    @staticmethod
    def _relevant_events(rows: list[sqlite3.Row], terms: set[str]) -> list[dict[str, Any]]:
        selected: list[tuple[float, dict[str, Any]]] = []
        now = time.time()
        for row in rows:
            content = str(row["content"] or "")
            age_days = max(0.0, now - float(row["created_at"] or now)) / 86_400
            score = _relevance(terms, content, float(row["created_at"] or 0))
            if row["event_type"] == "failure":
                score += 0.4
            score -= min(age_days / 365, 0.2)
            selected.append((score, dict(row)))
        selected.sort(key=lambda item: item[0], reverse=True)
        return [item for _score, item in selected[:12]]

    def _write_brief(self) -> None:
        try:
            with self._connect() as conn:
                state = self._state(conn)
                rows = conn.execute(
                    "SELECT * FROM continuity_decisions WHERE project_key=? AND status IN ('active','needs_review') ORDER BY updated_at DESC LIMIT 3",
                    (self.project_key,),
                ).fetchall()
                failures = conn.execute(
                    """SELECT content, created_at FROM continuity_events
                       WHERE project_key=? AND event_type='failure'
                       ORDER BY created_at DESC LIMIT 3""",
                    (self.project_key,),
                ).fetchall()
            snapshot = state.get("last_observed_snapshot") or {}
            task = state.get("current_task") or {}
            pending_changes = bool(
                task.get("changed_files")
                and task.get("status") in {"in_progress", "awaiting_verification", "blocked", "interrupted"}
            )
            verification_stale = bool(state.get("verification_stale") or pending_changes)
            lines = [
                "# Project Brief (gerado automaticamente)",
                "",
                f"PROJECT: {self.root}",
                f"OBJECTIVO: {_clean(task.get('objective') or state.get('project_goal') or 'não registado', 260)}",
                f"ESTADO ATUAL: {task.get('status') or 'sem tarefa ativa'}; snapshot={snapshot.get('fingerprint', 'não observado')[:12]}",
                "O QUE JÁ FOI FEITO:",
            ]
            completed = state.get("completed") or []
            lines.extend(
                (
                    "- verificado anteriormente; checkout mudou: "
                    if verification_stale
                    else "- verificado: "
                ) + _clean(item.get("objective"), 180)
                for item in completed[:5]
            )
            if not completed:
                lines.append("- sem conclusão de código validada")
            lines.extend(["EM CURSO:", f"- {_clean(task.get('objective') or 'nenhuma', 220)}"])
            lines.append("BLOQUEADO:")
            lines.extend(
                f"- {_clean(item.get('problem'), 180)}" for item in (state.get("blocked") or [])[:4]
            )
            lines.append("FALHAS CONHECIDAS:")
            lines.extend(f"- {_clean(row['content'], 200)}" for row in failures)
            if not failures:
                lines.append("- nenhuma falha registada")
            lines.append("RISCOS:")
            if verification_stale:
                lines.append("- checkout alterado depois da última verificação")
            if task.get("status") in {"paused", "interrupted", "awaiting_verification"}:
                lines.append("- há uma tarefa sem fecho ou validação confirmada")
            if not verification_stale and task.get("status") not in {"paused", "interrupted", "awaiting_verification"}:
                lines.append("- sem risco de continuidade registado")
            lines.append("DECISÕES:")
            lines.extend(
                f"- [{row['decision_key']}; {row['status']}] {_clean(row['decision'], 180)} | motivo: {_clean(row['rationale'], 100)} | impacto: {_clean(row['impact'], 100)}"
                for row in rows
            )
            if not rows:
                lines.append("- nenhuma registada")
            lines.extend(["PRÓXIMA AÇÃO:", f"- {_clean(state.get('next_action'), 240)}"])
            last = state.get("last_session") or {}
            if last:
                last_at = float(last.get("ended_at") or last.get("started_at") or 0)
                last_label = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(last_at))
                lines.append(
                    f"ÚLTIMA SESSÃO: {last_label} · {_clean(last.get('status'), 32)} · "
                    f"modelo={_clean(last.get('model') or 'não indicado', 80)}"
                )
            content = "\n".join(lines).rstrip() + "\n"
            self.state_dir.mkdir(parents=True, exist_ok=True)
            temp = self.brief_path.with_name(f".{self.brief_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                with temp.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, self.brief_path)
            finally:
                with suppress(FileNotFoundError):
                    temp.unlink()
        except (OSError, sqlite3.Error):
            logger.warning("Could not refresh project brief for %s", self.root, exc_info=True)

    def record_explicit_goal(self, goal: str) -> None:
        cleaned = _clean(goal, 500)
        if not cleaned:
            return
        with self._connect() as conn:
            state = self._state(conn)
            state["project_goal"] = cleaned
            self._event(conn, event_type="project_goal", status="recorded", content=cleaned)
            self._save_state(conn, state)
        self._write_brief()


def _relevance(terms: set[str], text: str, created_at: float) -> float:
    if not terms:
        return 0.05
    content_terms = _tokens(text)
    overlap = len(terms & content_terms)
    lexical = overlap / max(1, len(terms))
    recency = 0.08 / (1 + max(0.0, time.time() - created_at) / (30 * 86_400))
    return lexical + recency


def _similar(left: str, right: str) -> bool:
    a, b = _tokens(left), _tokens(right)
    return bool(a and b and len(a & b) / max(1, len(a | b)) >= 0.35)


def load_project_continuity(
    project_path: str,
    *,
    query: str,
    session_id: str,
    run_id: str,
    model: str = "",
) -> tuple[dict[str, Any], str]:
    """Create a pre-work checkpoint and build the bounded continuity context."""
    snapshot = capture_project_snapshot(project_path)
    store = ProjectContinuityStore(project_path)
    store.begin_run(
        session_id=session_id, run_id=run_id, objective=query, snapshot=snapshot, model=model
    )
    continuity = store.bootstrap_context(query, snapshot=snapshot)
    return snapshot, continuity


def combine_project_context(project_memory: str, continuity: str, *, max_chars: int = 8_000) -> str:
    """Keep the durable project map and current continuity brief within a small budget."""
    blocks = [part.strip() for part in (continuity, project_memory) if part and part.strip()]
    if not blocks:
        return ""
    return "\n\n".join(blocks)[: max(1, max_chars)]


__all__ = [
    "MAX_CONTEXT_CHARS",
    "ProjectContinuityStore",
    "capture_project_snapshot",
    "combine_project_context",
    "load_project_continuity",
]
