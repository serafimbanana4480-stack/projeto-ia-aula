"""Structured logging with OpenTelemetry integration.

Provides:
- JSON-structured log output
- Trace context propagation
- Request-scoped loggers
- Log levels with environment-based filtering
- Automatic correlation IDs
- **Secret redaction** on every Nexus-owned handler (audit P1-8)
- **Size + total-size bounded rotation** of the log file
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from backend.core.log_rotation import add_rotating_file_handler

# Context variables for request-scoped logging
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_session_id: ContextVar[str] = ContextVar("session_id", default="")
_agent_name: ContextVar[str] = ContextVar("agent_name", default="")


# ---------------------------------------------------------------------------
# Secret redaction (audit P1-8)
# ---------------------------------------------------------------------------
#: Replacement text.  Fixed length-agnostic so a reader cannot infer the length
#: of the original value from the log line.
REDACTION = "***REDACTED***"

#: Names that look secret by the rules below but are harmless counters/config
#: knobs.  Getting this wrong in either direction is a real bug: redacting
#: ``input_tokens=1500`` destroys the most useful line in an LLM log, while
#: missing ``admin_password`` leaks a credential.
_NON_SECRET_KEY_NAMES = frozenset(
    {
        "allow_credentials",
        "key_id",
        "key_ids",
        "key_func",
        "token_counter",
        "tokens",
    }
)

#: Name shapes that contain a secret-ish word but are counters/units.  Without
#: these, ``cost_per_token=0.003`` — the single most useful number in a spend
#: log — would be masked.
_NON_SECRET_KEY_PATTERNS = (
    re.compile(r"(?i)(?:^|[_\-.])per(?:[_\-.]|$)"),          # cost_per_token, tokens_per_second
    re.compile(
        r"(?i)(?:^|[_\-.])(?:max|min|total|num|count|counter|used|remaining|left"
        r"|input|output|prompt|completion|cached|cache|reasoning|budget|limit|limits"
        r"|avg|average|estimated|estimate|active|before|final|alt|new|effective"
        r"|default|history|since|per)(?:[_\-.]|$)"
    ),
)

_SECRET_EXACT_NAMES = frozenset(
    {
        "secret",
        "secrets",
        "password",
        "passwd",
        "pwd",
        "passphrase",
        "token",
        "credential",
        "credentials",
        "apikey",
        "secret_key",
        "private_key",
        "access_key",
        "access_key_id",
        "aws_secret_access_key",
        "secret_access_key",
        "signing_key",
        "master_key",
        "encryption_key",
        "fernet_key",
        "encryption_salt",
    }
)

#: ``key<sep>value`` pairs.  The *key* is validated separately by
#: :func:`is_secret_key_name`, so this regex only has to find candidates.
_CANDIDATE_RE = re.compile(
    r"""(?P<kq>["']?)(?P<key>[A-Za-z0-9_.\-]{1,64})(?P=kq)"""
    r"""(?P<sep>\s*(?:=>|[:=])\s*)"""
    r"""(?P<val>"[^"\n]*"|'[^'\n]*'|[^\s,;)\]}]+)"""
)

#: Header shapes: ``Authorization: Bearer x``, ``x-api-key=abc``, ``Cookie: ...``.
#: The auth-scheme alternative keeps ``Bearer`` inside the redacted span instead
#: of leaking the token through a lazy match.
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(?P<key>authorization|proxy-authorization|x-api-key|api-key|cookie|set-cookie)"
    r"(?P<sep>\s*[:=]\s*)(?P<quote>[\"']?)"
    r"(?P<value>(?:Bearer|Basic|Token|Digest)\s+[A-Za-z0-9._\-~+/=]{8,}|[^\s,;)\]}\"']+)"
    r"(?P=quote)"
)

#: Well-known provider key shapes that appear bare in a message.
_BARE_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{12,}|sk-or-v1-[A-Za-z0-9_\-]{12,}|gsk_[A-Za-z0-9_\-]{12,}"
    r"|xai-[A-Za-z0-9_\-]{12,}|AIza[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_\-]{16,}"
    r"|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
    r"|eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{5,})\b"
)

#: ``Bearer <token>`` anywhere in free text.
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-~+/=]{8,}")

#: Cheap gate so the majority of log lines (no secret-ish substring) skip the
#: three substitutions above entirely.
_SECRET_HINT_RE = re.compile(
    r"(?i)secret|passw|credential|token|api[-_ ]?key|apikey|authorization|bearer|cookie"
    r"|sk-|sk-or|eyj|AIza|ghp_|github_pat|glpat|gsk_|xai-|hf_|akia"
)

#: Values shorter than this are never a credential (avoids masking "5" or "ok").
_MIN_SECRET_LEN = 4

_SECRET_SEGMENTS = frozenset(
    {
        "secret",
        "secrets",
        "password",
        "passwd",
        "pwd",
        "passphrase",
        "credential",
        "credentials",
        "apikey",
    }
)


def is_secret_key_name(key: str) -> bool:
    """Whether a *field name* denotes a credential.

    Segment-based rather than a blind ``endswith``: ``input_tokens`` must not be
    masked (it is the most valuable number in an LLM log) while ``openai_api_key``
    and ``admin_password`` must be.
    """
    name = str(key).strip().strip("\"'").lower()
    if not name:
        return False
    if name in _NON_SECRET_KEY_NAMES:
        return False
    if any(pattern.search(name) for pattern in _NON_SECRET_KEY_PATTERNS):
        return False
    if name in _SECRET_EXACT_NAMES:
        return True
    segments = [part for part in re.split(r"[_\-.\s]+", name) if part]
    if _SECRET_SEGMENTS & set(segments):
        return True
    if {"key", "keys"} & set(segments) and (
        {"api", "access", "private", "secret"} & set(segments)
    ):
        return True
    # Singular only: ``*_tokens`` are counters, not credentials.
    return name.endswith("token")


def _looks_like_secret(value: str) -> bool:
    stripped = value.strip().strip("\"'")
    if len(stripped) < _MIN_SECRET_LEN:
        return False
    if "*" in stripped and set(stripped) <= {"*", "REDACTED"}:
        return False
    return stripped.lower() not in {"true", "false", "none", "null", "redacted"}


def redact_text(text: str) -> str:
    """Mask credential-looking values in *text*.

    Applied to the formatted message and to every logging argument, so a secret
    cannot leak through ``%s`` interpolation either.
    """
    if not text or not _SECRET_HINT_RE.search(text):
        return text

    def _auth(match: re.Match[str]) -> str:
        if not _looks_like_secret(match.group("value")):
            return match.group(0)
        quote = match.group("quote") or ""
        return f"{match.group('key')}{match.group('sep')}{quote}{REDACTION}{quote}"

    def _kv(match: re.Match[str]) -> str:
        if not is_secret_key_name(match.group("key")):
            return match.group(0)
        raw = match.group("val")
        if not _looks_like_secret(raw):
            return match.group(0)
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            return f"{match.group('kq')}{match.group('key')}{match.group('kq')}" \
                   f"{match.group('sep')}{raw[0]}{REDACTION}{raw[0]}"
        return f"{match.group('kq')}{match.group('key')}{match.group('kq')}" \
               f"{match.group('sep')}{REDACTION}"

    text = _AUTH_HEADER_RE.sub(_auth, text)
    text = _CANDIDATE_RE.sub(_kv, text)
    text = _BEARER_RE.sub(f"Bearer {REDACTION}", text)
    text = _BARE_TOKEN_RE.sub(REDACTION, text)
    return text


class RedactingFilter(logging.Filter):
    """A :mod:`logging` filter that redacts secrets in place.

    It rewrites ``record.msg`` and ``record.args`` so **every** handler below it
    (console, file, third-party) sees the redacted form.  Non-``str`` payloads
    are left alone unless they are ``dict``/``tuple``/``list`` containers whose
    string leaves can be redacted.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            record.msg = self._redact_obj(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        key: self._redact_obj(value) for key, value in record.args.items()
                    }
                else:
                    record.args = tuple(self._redact_obj(value) for value in record.args)
        except Exception:  # pragma: no cover - redaction must never break logging
            return True
        return True

    def _redact_obj(self, value: Any) -> Any:
        if isinstance(value, str):
            return redact_text(value)
        if isinstance(value, dict):
            redacted: dict[Any, Any] = {}
            for key, item in value.items():
                if (
                    isinstance(key, str)
                    and isinstance(item, str)
                    and is_secret_key_name(key)
                    and _looks_like_secret(item)
                ):
                    redacted[key] = REDACTION
                else:
                    redacted[key] = self._redact_obj(item)
            return redacted
        if isinstance(value, tuple):
            return tuple(self._redact_obj(item) for item in value)
        if isinstance(value, list):
            return [self._redact_obj(item) for item in value]
        return value


class JsonFormatter(logging.Formatter):
    """JSON-structured log formatter for machine-readable logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add context
        corr_id = _correlation_id.get()
        if corr_id:
            log_entry["correlation_id"] = corr_id

        sess_id = _session_id.get()
        if sess_id:
            log_entry["session_id"] = sess_id

        agent = _agent_name.get()
        if agent:
            log_entry["agent"] = agent

        # Add exception info
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": redact_text(str(record.exc_info[1])),
            }

        # Add extra fields
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)  # type: ignore

        return json.dumps(log_entry, default=str)


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    log_file: str | None = None,
) -> None:
    """Configure structured logging for the application.

    Args:
        level: Root level name.  Callers must pass the configured ``LOG_LEVEL``
            instead of a hard-coded value (audit P1-8).
        json_format: Emit JSON lines.
        log_file: When given, a **rotating** file handler is installed.  Rotation
            bounds both the single-file size and the total size of the rotated
            set; see :mod:`backend.core.log_rotation`.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Replace only handlers installed by a previous Nexus configuration.
    # Clearing the root logger also removed uvicorn/host handlers and pytest's
    # capture handler, making diagnostics disappear after an app lifespan.
    for handler in list(root.handlers):
        if getattr(handler, "_nexus_owned", False):
            root.removeHandler(handler)
            handler.close()

    # Every Nexus-owned handler redacts secrets before anything is written.
    redactor = RedactingFilter()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console._nexus_owned = True  # type: ignore[attr-defined]
    console.addFilter(redactor)
    if json_format:
        console.setFormatter(JsonFormatter())
    else:
        console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(console)

    # File handler (optional) — rotating, so logs/ stays bounded.
    if log_file:
        formatter: logging.Formatter = (
            JsonFormatter()
            if json_format
            else logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        add_rotating_file_handler(root, log_file, formatter=formatter).addFilter(redactor)

    # Set levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    root.info("Logging configured (level=%s, json=%s, redact=on)", level, json_format)


def set_correlation_id(correlation_id: str | None = None) -> str:
    """Set the correlation ID for the current request context."""
    cid = correlation_id or uuid.uuid4().hex[:12]
    _correlation_id.set(cid)
    return cid


def set_session_id(session_id: str) -> None:
    _session_id.set(session_id)


def set_agent_name(name: str) -> None:
    _agent_name.set(name)


def get_correlation_id() -> str:
    return _correlation_id.get()


class LoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that injects context into log records."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        extra = kwargs.get("extra", {})
        extra["correlation_id"] = _correlation_id.get()
        extra["session_id"] = _session_id.get()
        extra["agent"] = _agent_name.get()
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> LoggerAdapter:
    """Get a context-aware logger."""
    logger = logging.getLogger(name)
    return LoggerAdapter(logger, {})
