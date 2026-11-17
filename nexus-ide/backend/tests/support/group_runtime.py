"""SSE and durable-state helpers for the group-runtime end-to-end tests."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from backend.tests.support.nexus_backend import fetch_all, fetch_one


@dataclass
class ComposerResult:
    status_code: int
    content_type: str
    frames: list[dict[str, Any]] = field(default_factory=list)
    body: str = ""
    error: str = ""

    @property
    def run_ids(self) -> list[str]:
        found: list[str] = []
        for frame in self.frames:
            for candidate in (
                frame.get("run_id"),
                (frame.get("data") or {}).get("run_id") if isinstance(frame.get("data"), dict) else None,
            ):
                if isinstance(candidate, str) and candidate and candidate not in found:
                    found.append(candidate)
        return found

    @property
    def event_types(self) -> list[str]:
        return [str(frame.get("type") or "") for frame in self.frames]

    @property
    def text(self) -> str:
        chunks: list[str] = []
        for frame in self.frames:
            if str(frame.get("type") or "") in {"token", "message_delta"}:
                content = frame.get("content")
                if isinstance(content, str):
                    chunks.append(content)
        return "".join(chunks)


def _parse_sse_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def send_composer(
    client: httpx.Client,
    group_id: str,
    message: str,
    *,
    project_path: str = "",
    timeout: float = 120.0,
) -> ComposerResult:
    """POST one normal composer message and collect the streamed frames.

    The composer endpoint is the existing ``/api/bot-groups/{id}/messages``
    contract: a normal message has no attachment and no @mention.  An optional
    project root is the workspace selection, not an attachment.
    """
    url = f"/api/bot-groups/{group_id}/messages"
    payload: dict[str, Any] = {"message": message}
    if project_path:
        payload["project_path"] = project_path
    try:
        with client.stream(
            "POST", url, json=payload, timeout=timeout
        ) as response:
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                body = response.read().decode("utf-8", "replace")
                return ComposerResult(
                    status_code=response.status_code,
                    content_type=content_type,
                    body=body,
                )
            frames: list[dict[str, Any]] = []
            lines: list[str] = []
            for line in response.iter_lines():
                lines.append(line)
                parsed = _parse_sse_line(line)
                if parsed is not None:
                    frames.append(parsed)
            return ComposerResult(
                status_code=response.status_code,
                content_type=content_type,
                frames=frames,
                body="\n".join(lines),
            )
    except Exception as exc:  # noqa: BLE001 - tests report the real failure
        return ComposerResult(
            status_code=0,
            content_type="",
            error=f"{type(exc).__name__}: {exc}",
        )


class BackgroundComposer:
    """Run one composer stream on a worker thread.

    Used by kill/restart tests: the HTTP request is genuinely in flight when
    the backend process is killed.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        group_id: str,
        message: str,
        project_path: str = "",
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.token = token
        self.group_id = group_id
        self.message = message
        self.project_path = project_path
        self.timeout = timeout
        self.transport = transport
        self.frames: list[dict[str, Any]] = []
        self.result: ComposerResult | None = None
        self.done = threading.Event()
        self._thread: threading.Thread | None = None
        self._response: httpx.Response | None = None
        self._client: httpx.Client | None = None
        self._exc: BaseException | None = None

    def start(self) -> BackgroundComposer:
        thread = threading.Thread(target=self._run, name="group-composer", daemon=True)
        thread.start()
        self._thread = thread
        return self

    def _run(self) -> None:
        try:
            client = httpx.Client(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                transport=self.transport,
            )
            self._client = client
            payload: dict[str, Any] = {"message": self.message}
            if self.project_path:
                payload["project_path"] = self.project_path
            with client.stream(
                "POST",
                f"/api/bot-groups/{self.group_id}/messages",
                json=payload,
            ) as response:
                self._response = response
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    body = response.read().decode("utf-8", "replace")
                    self.result = ComposerResult(
                        status_code=response.status_code,
                        content_type=content_type,
                        body=body,
                    )
                    return
                for line in response.iter_lines():
                    parsed = _parse_sse_line(line)
                    if parsed is not None:
                        self.frames.append(parsed)
                self.result = ComposerResult(
                    status_code=response.status_code,
                    content_type=content_type,
                    frames=list(self.frames),
                )
        except BaseException as exc:  # noqa: BLE001 - deliberate: report it
            self._exc = exc
            self.result = ComposerResult(
                status_code=0,
                content_type="",
                frames=list(self.frames),
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if self._client is not None:
                with contextlib.suppress(Exception):
                    self._client.close()
            self.done.set()

    def wait(self, timeout: float = 30.0) -> bool:
        return self.done.wait(timeout=timeout)

    def abort(self) -> None:
        """Client-side stop (the UI's abort button)."""
        try:
            if self._response is not None:
                self._response.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._client is not None:
                self._client.close()
        except Exception:  # noqa: BLE001
            pass

    @property
    def run_ids(self) -> list[str]:
        merged = list(self.frames)
        if self.result is not None:
            merged.extend(self.result.frames)
        found: list[str] = []
        for frame in merged:
            for candidate in (
                frame.get("run_id"),
                (frame.get("data") or {}).get("run_id") if isinstance(frame.get("data"), dict) else None,
            ):
                if isinstance(candidate, str) and candidate and candidate not in found:
                    found.append(candidate)
        return found


# ----------------------------------------------------------------------
# Durable-state polling
# ----------------------------------------------------------------------
def latest_group_run(
    db_path: Path, group_id: str, *, request: str | None = None
) -> dict[str, Any] | None:
    query = "SELECT * FROM bot_group_runs WHERE group_id = ?"
    params: tuple[Any, ...] = (group_id,)
    if request is not None:
        query += " AND request = ?"
        params += (request,)
    query += " ORDER BY rowid DESC LIMIT 1"
    try:
        return fetch_one(db_path, query, params)
    except sqlite3.Error:
        return None


def wait_for(
    predicate: Callable[[], Any],
    *,
    timeout: float = 30.0,
    interval: float = 0.05,
    description: str = "condition",
) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout:.1f}s waiting for {description}")


def wait_for_group_run(
    db_path: Path,
    group_id: str,
    *,
    request: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    return wait_for(
        lambda: latest_group_run(db_path, group_id, request=request),
        timeout=timeout,
        description="the group run row to be created",
    )


def wait_for_terminal(
    db_path: Path,
    group_id: str,
    run_id: str,
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    def row() -> dict[str, Any] | None:
        candidate = latest_group_run(db_path, group_id)
        if candidate is None or str(candidate.get("id")) != run_id:
            return None
        status = str(candidate.get("status") or "")
        if status in {"completed", "failed", "cancelled", "interrupted"}:
            return candidate
        return None

    return wait_for(row, timeout=timeout, description=f"run {run_id} to become terminal")


def group_messages(db_path: Path, group_id: str) -> list[dict[str, Any]]:
    try:
        return fetch_all(
            db_path,
            "SELECT * FROM bot_group_messages WHERE group_id = ? ORDER BY rowid",
            (group_id,),
        )
    except sqlite3.Error:
        return []


def run_messages(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    try:
        return fetch_all(
            db_path,
            "SELECT * FROM bot_group_messages WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        )
    except sqlite3.Error:
        return []


def session_messages(db_path: Path, session_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        db_path,
        "SELECT * FROM messages WHERE session_id = ? ORDER BY rowid",
        (session_id,),
    )


def runtime_seq_problems(frames: list[dict[str, Any]]) -> list[str]:
    """Check the authoritative runtime sequence carried alongside the relay.

    The group stream wraps runtime events in its own composer frames.  Frames
    derived from a runtime event must carry that event's ``runtime_seq`` and
    those values must be strictly increasing; a relay cannot renumber a runtime
    event.  Composer-only frames (user_message/decision) have no runtime_seq.
    """
    problems: list[str] = []
    seen: dict[str, int] = {}
    for index, frame in enumerate(frames):
        kind = str(frame.get("type") or "")
        runtime_seq = frame.get("runtime_seq")
        if runtime_seq is None and isinstance(frame.get("data"), dict):
            runtime_seq = frame["data"].get("runtime_seq")
        if kind in {"token", "agent_tool", "agent_message"} and not isinstance(
            runtime_seq, int
        ):
            problems.append(f"frame {index} ({kind}) has no integer runtime_seq")
            continue
        if not isinstance(runtime_seq, int):
            continue
        run_id = frame.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            run_id = ""
        previous = seen.get(run_id)
        if previous is not None and runtime_seq <= previous:
            problems.append(
                f"frame {index} runtime_seq={runtime_seq} is not greater than {previous}"
            )
        seen[run_id] = runtime_seq
    return problems


def frame_envelope_problems(frames: list[dict[str, Any]]) -> list[str]:
    """Check the ``(run_id, seq)`` total-order contract on relayed frames."""
    problems: list[str] = []
    seen: dict[str, int] = {}
    for index, frame in enumerate(frames):
        run_id = frame.get("run_id")
        seq = frame.get("seq")
        data = frame.get("data")
        if not isinstance(run_id, str) or not run_id:
            run_id = data.get("run_id") if isinstance(data, dict) else None
        if not isinstance(seq, int):
            seq = data.get("seq") if isinstance(data, dict) else None
        if not isinstance(run_id, str) or not run_id:
            problems.append(f"frame {index} ({frame.get('type')!r}) has no run_id")
            continue
        if not isinstance(seq, int):
            problems.append(f"frame {index} ({frame.get('type')!r}) has no integer seq")
            continue
        previous = seen.get(run_id)
        if previous is not None and seq <= previous:
            problems.append(
                f"frame {index} seq={seq} is not greater than previous seq={previous}"
            )
        seen[run_id] = seq
    return problems


__all__ = [
    "BackgroundComposer",
    "ComposerResult",
    "frame_envelope_problems",
    "group_messages",
    "runtime_seq_problems",
    "latest_group_run",
    "run_messages",
    "send_composer",
    "session_messages",
    "wait_for",
    "wait_for_group_run",
    "wait_for_terminal",
]
