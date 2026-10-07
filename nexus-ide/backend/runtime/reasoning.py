"""Canonical reasoning (public approach) text: bounding, visibility, parsing.

Why this module exists
----------------------
Three independent parts of the system need the exact same reasoning text, and
they must never disagree about what may leave the process:

* ``RuntimeEventType.THINKING`` and its ``StreamEvent`` translation;
* every provider adapter, each of which hides the model's reasoning in a
  different field (``delta.reasoning_content``, Anthropic ``thinking_delta``,
  Ollama ``message.thinking``, Gemini ``thought`` parts);
* the agents, which must turn that captured text into a *bounded* control frame
  instead of forwarding a private transcript.

So all three live here:

1. **A bound.** Nothing unbounded ever reaches the journal, the SSE body or the
   DOM. ``label`` mode is capped at :data:`LABEL_CAP` characters — the same cap
   the primary runtime already applied to its ``STATUS_UPDATE`` label, so
   turning the panel on cannot widen what was already visible.
2. **A visibility policy.** ``NEXUS_REASONING_VISIBILITY`` is ``label``
   (default), ``full`` or ``off``. ``label`` is *operational transparency* — what
   the agent is about to do — never a private chain of thought. Only an
   operator can raise it; a UI control can only ever lower it.
3. **A dialect-aware parser.** :func:`parse_provider_delta` splits one provider
   frame into ``(content, reasoning, tool_calls)`` so the answer channel and the
   reasoning channel stay separate all the way to the ``StreamEvent``. Merging
   them is exactly how a private transcript ends up inside a user-visible
   answer.

Every entry point here is defensive on purpose: a provider that returns a
malformed, absent or surprising reasoning field must never break the answer
stream (:func:`deliver_reasoning` is the only function providers need).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

#: Hard cap for the default ``label`` visibility mode. Deliberately equal to the
#: 160-character cap the primary runtime already used for its status label, so
#: the default posture is byte-for-byte the privacy guarantee of today.
LABEL_CAP = 160

#: Hard cap when an operator explicitly opts into ``full``. Still bounded: an
#: unbounded "thought dump" is both a privacy hazard and a rendering hazard.
FULL_CAP = 4_000

#: The most reasoning text collected from a single provider stream. A model can
#: think for tens of thousands of tokens; only the first slice is ever useful
#: as an *operational summary* and the rest is pure cost.
COLLECT_CAP = 8_000

#: Used when the provider produced reasoning that is entirely opaque (for
#: example an Anthropic ``redacted_thinking`` block).
DEFAULT_LABEL = "a definir a abordagem"

_ENV_VAR = "NEXUS_REASONING_VISIBILITY"

#: Key under which a provider adapter finds the reasoning callback in its
#: ``options`` dictionary. Defined here (a dependency-free module) so the agent
#: and every provider import the *same* key without an import cycle.
REASONING_SINK_OPTION = "_nexus_reasoning_sink"

#: Portable request flag for "this model may think" (Ollama reads it natively;
#: Anthropic uses it to derive ``budget_tokens``). Only ever set when a sink is
#: present, so a model that cannot think is unaffected.
REASONING_REQUEST_OPTION = "think"


class ReasoningVisibility(StrEnum):
    """How much of the model's reasoning may be surfaced to the user."""

    #: One bounded, single-line statement of the approach. The default.
    LABEL = "label"
    #: The model's own bounded reasoning text. Operator opt-in only.
    FULL = "full"
    #: Nothing. The panel stays empty and no event is emitted.
    OFF = "off"


_ON_WORDS = {"1", "true", "yes", "on", "enabled", "show"}
_OFF_WORDS = {"0", "false", "no", "off", "disabled", "hide", "none"}


def reasoning_visibility(
    default: ReasoningVisibility = ReasoningVisibility.LABEL,
) -> ReasoningVisibility:
    """Resolve ``NEXUS_REASONING_VISIBILITY`` into a policy.

    Unknown values fall back to *toward privacy* (``label``), never to
    ``full``: a typo in a deployment variable must not silently widen what the
    browser receives.
    """
    raw = os.environ.get(_ENV_VAR, "").strip().lower()
    if not raw:
        return default
    if raw in _OFF_WORDS:
        return ReasoningVisibility.OFF
    if raw in _ON_WORDS:
        return ReasoningVisibility.LABEL
    try:
        return ReasoningVisibility(raw)
    except ValueError:
        logger.warning(
            "Unknown %s=%r; falling back to %s", _ENV_VAR, raw, default.value
        )
        return default


#: ``medium``/``high`` may unlock the operator's opt-in but never grant it.
_STRENGTH_ALLOW_FULL = frozenset({"medium", "high"})


def visibility_for_strength(
    strength: str,
    *,
    operator_visibility: ReasoningVisibility | None = None,
) -> ReasoningVisibility:
    """Map the UI's thinking-depth control onto the visibility policy.

    ``low``/``""`` can only ever show a label. ``medium``/``high`` unlock an
    operator's explicit ``full`` opt-in, and are silently ignored when the
    operator did not opt in — but they are never ignored *silently*: the
    resulting policy is returned so the caller can log or surface it.
    """
    operator = (
        reasoning_visibility()
        if operator_visibility is None
        else operator_visibility
    )
    if operator is ReasoningVisibility.OFF:
        return ReasoningVisibility.OFF
    normalized = (strength or "").strip().lower()
    if normalized in _STRENGTH_ALLOW_FULL and operator is ReasoningVisibility.FULL:
        return ReasoningVisibility.FULL
    return ReasoningVisibility.LABEL


_TAG_RE = re.compile(
    r"</?\s*(?:think|thinking|reasoning|scratchpad)\s*>",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


def strip_reasoning_markup(text: str) -> str:
    """Remove ``<think>``-style tags. The tags are transport, not content."""
    if not text:
        return ""
    return _TAG_RE.sub("", str(text))


def collapse_reasoning_whitespace(text: str) -> str:
    """Collapse every run of whitespace (including newlines) into one space."""
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", str(text)).strip()


def bound_label(text: str, *, cap: int = LABEL_CAP) -> str:
    """One operational line: markup-free, single-line, hard-capped.

    This is the default (and the only) shape the browser sees unless an
    operator opts into ``full``.
    """
    clean = collapse_reasoning_whitespace(strip_reasoning_markup(text))
    if not clean:
        return ""
    limit = max(1, cap)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def bound_reasoning_text(
    text: str,
    *,
    visibility: ReasoningVisibility | None = None,
    cap: int | None = None,
) -> str:
    """Apply the visibility policy and the bound. ``off`` yields ``""``."""
    policy = reasoning_visibility() if visibility is None else visibility
    if policy is ReasoningVisibility.OFF:
        return ""
    if policy is ReasoningVisibility.FULL:
        clean = strip_reasoning_markup(text).strip()
        limit = FULL_CAP if cap is None else cap
        if limit and len(clean) > limit:
            return clean[:limit].rstrip() + "…"
        return clean
    return bound_label(text, cap=LABEL_CAP if cap is None else cap)


def reasoning_label_or_default(text: str, *, cap: int = LABEL_CAP) -> str:
    """A label that is never empty, so a block always has a renderable row."""
    return bound_label(text, cap=cap) or DEFAULT_LABEL


def count_reasoning_tokens(text: str, model: str = "fast") -> int:
    """Token count for reasoning text, reusing the session's own counter.

    Providers that report reasoning tokens are preferred by the caller; this is
    the honest local estimate for the ones that do not, and it is what makes
    ``reasoning_tokens`` in the usage metric non-zero instead of hardcoded.
    """
    if not text:
        return 0
    try:
        from backend.token_management import count_tokens

        return max(0, int(count_tokens(str(text), model or "fast")))
    except Exception:
        logger.debug("token counter unavailable; estimating reasoning tokens", exc_info=True)
        return max(0, len(str(text)) // 4)


# ---------------------------------------------------------------------------
# provider-native reasoning parsing
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    """One provider frame split into independent channels.

    ``content`` is the only field that may ever become user-visible answer
    text. ``reasoning`` is the approach text for the panel. ``tool_calls`` is
    the structured tool transport, already separated by the providers that
    support native function calling.
    """

    content: str = ""
    reasoning: str = ""
    tool_calls: tuple[Any, ...] = ()
    signature: str = ""
    redacted: bool = False
    usage: dict[str, int] = field(default_factory=dict)


def _string(value: Any) -> str:
    """Coerce an optional provider field to ``str`` without ever raising."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, str):
        try:
            return max(0, int(float(value.strip())))
        except ValueError:
            return 0
    return 0


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _openai_usage(usage: Any) -> dict[str, int]:
    """Reasoning tokens from an OpenAI-compatible ``usage`` block.

    DeepSeek R1 and the o-series report
    ``completion_tokens_details.reasoning_tokens``; several OpenAI-compatible
    servers flatten it to ``reasoning_tokens``.
    """
    block = _as_dict(usage)
    if not block:
        return {}
    details = _as_dict(block.get("completion_tokens_details"))
    for key in ("reasoning_tokens", "reasoning", "thoughts_tokens"):
        value = _int(details.get(key))
        if value:
            return {"reasoning_tokens": value}
    for key in ("reasoning_tokens", "thinking_tokens"):
        value = _int(block.get(key))
        if value:
            return {"reasoning_tokens": value}
    return {}


_RESPONSES_REASONING_FRAMES = frozenset(
    {
        "response.reasoning_summary_text.delta",
        "response.reasoning_text.delta",
    }
)


def _parse_openai(frame: dict[str, Any]) -> ReasoningDelta:
    usage = _openai_usage(frame.get("usage"))
    delta = _as_dict(frame.get("delta"))
    if not delta:
        choices = _as_list(frame.get("choices"))
        if choices:
            delta = _as_dict(_as_dict(choices[0]).get("delta"))
    content = _string(delta.get("content"))
    reasoning = _string(delta.get("reasoning_content")) or _string(
        delta.get("reasoning")
    )
    if not reasoning and str(frame.get("type") or "") in _RESPONSES_REASONING_FRAMES:
        # OpenAI's Responses API streams reasoning summaries as their own
        # frame; the text lives in ``delta``/``text`` rather than in content.
        reasoning = _string(frame.get("delta")) or _string(frame.get("text"))
    tool_calls = tuple(
        frag for frag in _as_list(delta.get("tool_calls")) if isinstance(frag, dict)
    )
    return ReasoningDelta(
        content=content,
        reasoning=reasoning,
        tool_calls=tool_calls,
        usage=usage,
    )


def _parse_anthropic(frame: dict[str, Any]) -> ReasoningDelta:
    usage = _anthropic_usage(frame.get("usage"))
    event_type = str(frame.get("type") or "")
    if event_type == "content_block_start":
        block = _as_dict(frame.get("content_block"))
        block_type = str(block.get("type") or "")
        if block_type == "redacted_thinking":
            return ReasoningDelta(redacted=True, usage=usage)
        if block_type == "thinking":
            return ReasoningDelta(reasoning=_string(block.get("thinking")), usage=usage)
        return ReasoningDelta(usage=usage)

    delta = _as_dict(frame.get("delta"))
    delta_type = str(delta.get("type") or "")
    if delta_type == "thinking_delta":
        return ReasoningDelta(reasoning=_string(delta.get("thinking")), usage=usage)
    if delta_type == "signature_delta":
        # The signature is an integrity token, never user-visible text.
        return ReasoningDelta(signature=_string(delta.get("signature")), usage=usage)
    if delta_type == "redacted_thinking" or event_type == "redacted_thinking":
        return ReasoningDelta(redacted=True, usage=usage)
    return ReasoningDelta(content=_string(delta.get("text")), usage=usage)


def _anthropic_usage(usage: Any) -> dict[str, int]:
    block = _as_dict(usage)
    if not block:
        return {}
    for key in ("thinking_tokens", "reasoning_tokens"):
        value = _int(block.get(key))
        if value:
            return {"reasoning_tokens": value}
    return {}


def _parse_ollama(frame: dict[str, Any]) -> ReasoningDelta:
    message = _as_dict(frame.get("message")) or frame
    thinking = _string(message.get("thinking")) or _string(
        message.get("reasoning")
    )
    return ReasoningDelta(
        content=_string(message.get("content")),
        reasoning=thinking,
    )


def _parse_gemini(frame: dict[str, Any]) -> ReasoningDelta:
    usage = _gemini_usage(frame.get("usageMetadata") or frame.get("usage_metadata"))
    candidates = _as_list(frame.get("candidates"))
    if not candidates:
        return ReasoningDelta(usage=usage)
    parts = _as_list(_as_dict(_as_dict(candidates[0]).get("content")).get("parts"))
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    for part in parts:
        block = _as_dict(part)
        text = _string(block.get("text"))
        if not text:
            continue
        # ``thought: true`` is the only flag Gemini sets on a thinking part.
        # ``thoughtSignature`` alone rides on ordinary answer parts, so it must
        # never re-route answer text into the reasoning channel.
        if block.get("thought") is True:
            reasoning_parts.append(text)
        else:
            content_parts.append(text)
    return ReasoningDelta(
        content="".join(content_parts),
        reasoning="".join(reasoning_parts),
        usage=usage,
    )


def _gemini_usage(usage: Any) -> dict[str, int]:
    block = _as_dict(usage)
    if not block:
        return {}
    for key in ("thoughtsTokenCount", "thinking_tokens", "reasoning_tokens"):
        value = _int(block.get(key))
        if value:
            return {"reasoning_tokens": value}
    return {}


_PARSERS: dict[str, Callable[[dict[str, Any]], ReasoningDelta]] = {
    "openai": _parse_openai,
    "anthropic": _parse_anthropic,
    "ollama": _parse_ollama,
    "gemini": _parse_gemini,
}


def parse_provider_delta(dialect: str, frame: Any) -> ReasoningDelta:
    """Split one provider frame into ``(content, reasoning, tool_calls)``.

    Never raises. An unrecognised dialect or a malformed frame degrades to the
    salvageable answer text, because losing reasoning must never cost the user
    their answer.
    """
    if not isinstance(frame, dict):
        return ReasoningDelta()
    parser = _PARSERS.get(str(dialect or "").strip().lower())
    if parser is None:
        return ReasoningDelta(content=_string(frame.get("content")))
    try:
        return parser(frame)
    except Exception:
        logger.debug("Malformed %s reasoning frame ignored", dialect, exc_info=True)
        return ReasoningDelta(content=_string(_as_dict(frame.get("delta")).get("text")))


def reasoning_sink(
    collector: list[str] | None,
    *,
    cap: int = COLLECT_CAP,
) -> Callable[..., None] | None:
    """Build the callback a provider uses to hand reasoning back.

    The sink is the *only* new channel a provider needs: it appends bounded
    reasoning text to ``collector`` and ignores everything else (signatures,
    redacted blocks, overflow past ``cap``).
    """
    if collector is None:
        return None
    state = {"size": 0}

    def _sink(text: str = "", *, redacted: bool = False, signature: str = "") -> None:
        del signature  # integrity tokens are never user-visible text
        if redacted or not text:
            return
        chunk = str(text)
        room = cap - state["size"]
        if room <= 0:
            return
        if len(chunk) > room:
            chunk = chunk[:room]
        state["size"] += len(chunk)
        collector.append(chunk)

    return _sink


def deliver_reasoning(
    sink: Callable[..., None] | None,
    dialect: str,
    frame: Any,
) -> ReasoningDelta:
    """Parse ``frame`` and push *only* the reasoning channel into ``sink``.

    The two channels never mix: the caller still yields ``delta.content`` to the
    model stream while ``delta.reasoning`` goes to the panel.
    """
    parsed = parse_provider_delta(dialect, frame)
    if sink is not None and parsed.reasoning:
        with contextlib.suppress(Exception):
            sink(parsed.reasoning)
    return parsed


def join_collected_reasoning(parts: list[str] | Iterable[str]) -> str:
    """Concatenate collected reasoning fragments, tolerating odd input."""
    try:
        chunks = [str(part) for part in parts if part]
    except TypeError:
        return ""
    return "".join(chunks)


# ---------------------------------------------------------------------------
# config/models.yaml ``thinking_mode`` (previously declared, never read)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _models_config() -> dict[str, Any]:
    try:
        from backend.config.settings import load_models_config

        return load_models_config() or {}
    except Exception:
        logger.debug("models.yaml unavailable for the reasoning policy", exc_info=True)
        return {}


def _models_by_key() -> dict[str, dict[str, Any]]:
    blocks = _models_config().get("models", {})
    if not isinstance(blocks, dict):
        return {}
    return {
        str(key): block
        for key, block in blocks.items()
        if isinstance(block, dict)
    }


def model_declares_thinking_mode(model_key: str) -> bool:
    """True when ``config/models.yaml`` marks this *tier* as a reasoning tier."""
    return bool(_models_by_key().get(str(model_key or ""), {}).get("thinking_mode"))


def model_id_declares_thinking_mode(model_id: str) -> bool:
    """True when any declared model with this id belongs to a reasoning tier."""
    target = str(model_id or "").strip().lower()
    if not target:
        return False
    for block in _models_by_key().values():
        if not block.get("thinking_mode"):
            continue
        for key in ("id", "fallback_id"):
            if str(block.get(key) or "").strip().lower() == target:
                return True
    return False


__all__ = [
    "COLLECT_CAP",
    "DEFAULT_LABEL",
    "FULL_CAP",
    "LABEL_CAP",
    "REASONING_REQUEST_OPTION",
    "REASONING_SINK_OPTION",
    "ReasoningDelta",
    "ReasoningVisibility",
    "bound_label",
    "bound_reasoning_text",
    "collapse_reasoning_whitespace",
    "count_reasoning_tokens",
    "deliver_reasoning",
    "join_collected_reasoning",
    "model_declares_thinking_mode",
    "model_id_declares_thinking_mode",
    "parse_provider_delta",
    "reasoning_label_or_default",
    "reasoning_sink",
    "reasoning_visibility",
    "strip_reasoning_markup",
    "visibility_for_strength",
]
