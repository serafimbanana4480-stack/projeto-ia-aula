"""Atomic, session-scoped persistence for Infinity Vibe worker history."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

STORE_VERSION = 1
MAX_STORE_BYTES = 16 * 1024 * 1024


class VibeStateStore:
    """Persist one chat session without exposing its ID in the file name."""

    def __init__(self, root: str | Path, session_id: str) -> None:
        self.session_id = str(session_id or "").strip()
        if not self.session_id:
            raise ValueError("a chat session id is required for Vibe persistence")
        self.root = Path(root).expanduser().resolve()
        digest = hashlib.sha256(self.session_id.encode("utf-8")).hexdigest()
        self.path = self.root / f"{digest}.json"

    @classmethod
    def for_session(cls, session_id: str) -> VibeStateStore:
        explicit_root = os.environ.get("NEXUS_VIBE_STATE_ROOT")
        if explicit_root:
            root = Path(explicit_root)
        else:
            advanced_root = os.environ.get("NEXUS_ADVANCED_STATE_ROOT")
            if advanced_root:
                root = Path(advanced_root) / "infinity-vibe"
            else:
                repository_root = Path(__file__).resolve().parents[3]
                root = repository_root / ".nexus" / "infinity-vibe"
        return cls(root, session_id)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": STORE_VERSION,
                "session_id": self.session_id,
                "workers": [],
            }
        try:
            if self.path.stat().st_size > MAX_STORE_BYTES:
                raise RuntimeError("Vibe worker state exceeds the supported size limit")
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("Vibe worker state could not be read safely") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("version") != STORE_VERSION
            or payload.get("session_id") != self.session_id
            or not isinstance(payload.get("workers"), list)
        ):
            raise RuntimeError("Vibe worker state has an unsupported or mismatched format")
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        if (
            not isinstance(payload, dict)
            or payload.get("version") != STORE_VERSION
            or payload.get("session_id") != self.session_id
            or not isinstance(payload.get("workers"), list)
        ):
            raise ValueError("invalid Vibe worker state payload")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_STORE_BYTES:
            raise RuntimeError("Vibe worker state exceeds the supported size limit")

        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.stem}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def delete(self) -> None:
        """Remove only this session's hash-addressed state file."""
        if self.path.exists():
            self.path.unlink()


__all__ = ["MAX_STORE_BYTES", "STORE_VERSION", "VibeStateStore"]
