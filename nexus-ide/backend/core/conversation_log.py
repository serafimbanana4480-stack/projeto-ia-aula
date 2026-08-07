"""Structured per-session conversation/execution logging.

Every significant event of an autonomous or chat run — task lifecycle, tool
calls, tool results, tool errors, recoveries, retries, verification rounds,
and the final run summary — is appended to a JSONL file under
``logs/conversations/<YYYY-MM-DD>/<session_id>.jsonl`` inside the nexus-ide
root. These logs are the audit trail used to debug failed autonomous runs
("Execução Autónoma Falhou") without digging through mixed server logs.

Design rules:
- Fire-and-forget: logging must NEVER break the run. All I/O is wrapped.
- One logger per session, process-wide, thread-safe.
- Secrets are never logged: only tool names, argument keys, paths, error
  messages, and bounded content snippets.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_NEXUS_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG_DIR = _NEXUS_ROOT / "logs" / "conversations"

# Bound snippets so a single tool result cannot bloat the JSONL file.
_MAX_SNIPPET = 500

_lock = threading.Lock()
_loggers: dict[str, "ConversationLogger"] = {}


def _snippet(value: Any, limit: int = _MAX_SNIPPET) -> Any:
    """Return a JSON-safe, size-bounded representation of *value*."""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    if len(text) > limit:
        return text[:limit] + f"...[truncated {len(text) - limit} chars]"
    return text


def _safe_arg_keys(args: Any) -> Any:
    """Log argument keys and small scalar values, never full payloads."""
    if not isinstance(args, dict):
        return _snippet(args, 200)
    safe: dict[str, Any] = {}
    for key, value in args.items():
        if key.lower() in {"content", "code", "script", "prompt", "text", "body"}:
            safe[key] = f"<{len(str(value))} chars>"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = _snippet(value, 200)
        else:
            safe[key] = f"<{type(value).__name__}>"
    return safe


class ConversationLogger:
    """Append-only JSONL event log for one session."""

    def __init__(self, session_id: str, log_dir: Path | None = None) -> None:
        self.session_id = session_id
        self._log_dir = log_dir or _DEFAULT_LOG_DIR
        self._file: Path | None = None
        self._write_lock = threading.Lock()
        self._disabled = False

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------
    def _target_file(self) -> Path:
        if self._file is None:
            day = datetime.now(UTC).strftime("%Y-%m-%d")
            safe_session = "".join(
                c if c.isalnum() or c in "-_" else "_" for c in self.session_id
            )[:80] or "unknown"
            self._file = self._log_dir / day / f"{safe_session}.jsonl"
        return self._file

    def log(self, event_type: str, **data: Any) -> None:
        """Append one event. Never raises."""
        if self._disabled:
            return
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "session_id": self.session_id,
            "event": event_type,
            **data,
        }
        try:
            line = json.dumps(record, default=str, ensure_ascii=False)
            with self._write_lock:
                target = self._target_file()
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception as exc:
            # Logging must never break the run; disable after repeated failure
            # would be overkill — degrade to the standard logger instead.
            logger.debug("ConversationLogger write failed (%s): %s", event_type, exc)

    # ------------------------------------------------------------------
    # Convenience events
    # ------------------------------------------------------------------
    def log_task_started(self, task_id: str, task_name: str, agent: str, attempt: int = 1) -> None:
        self.log(
            "task_started",
            task_id=task_id,
            task_name=_snippet(task_name, 200),
            agent=agent,
            attempt=attempt,
        )

    def log_task_completed(
        self, task_id: str, task_name: str, agent: str, *, duration_s: float | None = None
    ) -> None:
        self.log(
            "task_completed",
            task_id=task_id,
            task_name=_snippet(task_name, 200),
            agent=agent,
            duration_s=duration_s,
        )

    def log_task_failed(
        self,
        task_id: str,
        task_name: str,
        agent: str,
        error: Any,
        *,
        recovered_errors: list[str] | None = None,
        attempts: int | None = None,
    ) -> None:
        self.log(
            "task_failed",
            task_id=task_id,
            task_name=_snippet(task_name, 200),
            agent=agent,
            error=_snippet(error),
            recovered_errors=[_snippet(e, 200) for e in (recovered_errors or [])],
            attempts=attempts,
        )

    def log_tool_call(self, agent: str, tool: str, args: Any, *, iteration: int | None = None) -> None:
        self.log(
            "tool_call",
            agent=agent,
            tool=tool,
            args=_safe_arg_keys(args),
            iteration=iteration,
        )

    def log_tool_result(
        self, agent: str, tool: str, *, ok: bool, elapsed_ms: float | None = None
    ) -> None:
        self.log("tool_result", agent=agent, tool=tool, ok=ok, elapsed_ms=elapsed_ms)

    def log_tool_error(
        self,
        agent: str,
        tool: str,
        error: Any,
        *,
        iteration: int | None = None,
        recoverable: bool | None = None,
    ) -> None:
        self.log(
            "tool_error",
            agent=agent,
            tool=tool,
            error=_snippet(error),
            iteration=iteration,
            recoverable=recoverable,
        )

    def log_tool_recovered(self, agent: str, tool: str, *, recovered_from: Any = None) -> None:
        self.log(
            "tool_recovered",
            agent=agent,
            tool=tool,
            recovered_from=_snippet(recovered_from, 200),
        )

    def log_verification_round(
        self, round_no: int, *, issues_found: int, inconclusive: int = 0
    ) -> None:
        self.log(
            "verification_round",
            round=round_no,
            issues_found=issues_found,
            inconclusive=inconclusive,
        )

    def log_run_summary(
        self,
        *,
        state: str,
        completed_tasks: int,
        failed_tasks: int,
        duration_ms: int,
        errors: list[str] | None = None,
    ) -> None:
        self.log(
            "run_summary",
            state=state,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            duration_ms=duration_ms,
            errors=[_snippet(e, 200) for e in (errors or [])][:10],
        )


def get_conversation_logger(session_id: str) -> ConversationLogger:
    """Return the shared :class:`ConversationLogger` for *session_id*."""
    with _lock:
        existing = _loggers.get(session_id)
        if existing is None:
            existing = ConversationLogger(session_id)
            _loggers[session_id] = existing
        return existing
