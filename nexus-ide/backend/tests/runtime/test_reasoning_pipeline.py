"""The tool-reasoning pipeline, end to end, without a provider.

Why this file exists
--------------------
The on-screen "painel de raciocínio" was completely non-functional. The proven
defects were: the runtime vocabulary had no ``THINKING`` member, the primary
loop mapped the agent's thinking signal onto a 160-character ``STATUS_UPDATE``
only, and the SSE bridge therefore never produced a single
``StreamEvent(type="thinking")`` for the frontend to fold.

These tests pin the whole path that a reasoning delta now travels:

    provider dialect -> bounded RuntimeEventType.THINKING
                      -> StreamEvent(type="thinking") with the (run_id, seq)
                         ordering envelope
                      -> non-zero reasoning token accounting

plus the privacy contract (what may leave the process) and the two behaviours
that must not regress (journal replay tolerance, and the swarm aggregation not
leaking protocol tags).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.runtime.events import RunEventStream, RuntimeEvent, RuntimeEventType
from backend.runtime.primary import (
    AgentSignal,
    AgentSignalKind,
    PrimaryLoop,
    PrimaryTurn,
)
from backend.runtime.reasoning import (
    FULL_CAP,
    LABEL_CAP,
    ReasoningVisibility,
    bound_label,
    bound_reasoning_text,
    count_reasoning_tokens,
    deliver_reasoning,
    parse_provider_delta,
    reasoning_label_or_default,
    reasoning_sink,
    visibility_for_strength,
)


# --------------------------------------------------------------------- events
def test_thinking_is_a_first_class_runtime_event() -> None:
    """D1/D2: the vocabulary needs the member for the panel to exist at all."""
    assert RuntimeEventType.THINKING == "thinking"
    assert RuntimeEventType("thinking") is RuntimeEventType.THINKING


def test_from_dict_is_tolerant_of_an_unknown_type() -> None:
    """A journal written by another build must never crash a replay."""
    raw = {
        "run_id": "run-x",
        "seq": 4,
        "type": "reasoning_from_the_future",
        "event_id": "e-4",
        "payload": {},
    }
    assert RuntimeEvent.try_from_dict(raw) is None
    # The strict variant still refuses, so a caller that *needs* the value is
    # told rather than silently handed a wrong one.
    with pytest.raises(ValueError):
        RuntimeEvent.from_dict(raw)


def test_try_from_dict_survives_junk_entries() -> None:
    assert RuntimeEvent.try_from_dict(None) is None
    assert RuntimeEvent.try_from_dict("not a dict") is None
    assert RuntimeEvent.try_from_dict({"run_id": "r", "seq": 1}) is None
    assert RuntimeEvent.try_from_dict({"run_id": "r", "seq": 1, "type": "heartbeat"})


def test_load_journal_skips_lines_it_cannot_interpret(tmp_path: Path) -> None:
    good = RuntimeEvent(
        run_id="run-j",
        seq=2,
        type=RuntimeEventType.MESSAGE_DELTA,
        payload={"text": "ok"},
    )
    journal = tmp_path / "run-j.jsonl"
    journal.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "run-j",
                        "seq": 1,
                        "type": "unknown_from_another_build",
                        "event_id": "x",
                    }
                ),
                "{not json",
                json.dumps(good.to_sse()),
            ]
        ),
        encoding="utf-8",
    )
    events = RunEventStream.load_journal(journal)
    assert [event.seq for event in events] == [2]


# ------------------------------------------------------------- runtime emit
def _loop_with_thinking(text: str, visibility: ReasoningVisibility | None = None) -> PrimaryLoop:
    async def stream(_turn: PrimaryTurn):  # pragma: no cover - never consumed
        if False:
            yield AgentSignal(AgentSignalKind.TOKEN, text="")

    loop = PrimaryLoop(
        run_id="run-thinking",
        query="corrige o bug",
        stream=stream,
        reasoning_visibility=visibility,
    )
    return loop


def test_thinking_signal_emits_status_update_and_thinking() -> None:
    """D1: the STATUS_UPDATE stays first; THINKING is added after it."""
    loop = _loop_with_thinking("")
    events = loop._handle_signal(
        AgentSignal(AgentSignalKind.THINKING, text="Vou ler o módulo e ajustar o offset."),
        _turn(),  # type: ignore[arg-type]
        loop.events.emit,
        [],
    )
    types = [event.type for event in events]
    assert types == [RuntimeEventType.STATUS_UPDATE, RuntimeEventType.THINKING]
    # The status frame is unchanged for phase/telemetry consumers.
    assert events[0].payload["phase"] == "act"
    assert events[0].payload["blocked_on"] == "waiting_model"
    # The reasoning payload lives under `text` and is bounded.
    assert events[1].payload["text"]
    assert len(events[1].payload["text"]) <= LABEL_CAP


def _turn() -> PrimaryTurn:
    return PrimaryTurn(query="corrige o bug", cycle=1)


def test_thinking_payload_is_bounded_to_the_configured_cap() -> None:
    loop = _loop_with_thinking("")
    long_text = "Vou " + ("rever o cálculo do offset " * 400)
    events = loop._handle_signal(
        AgentSignal(AgentSignalKind.THINKING, text=long_text),
        _turn(),  # type: ignore[arg-type]
        loop.events.emit,
        [],
    )
    thinking = next(e for e in events if e.type is RuntimeEventType.THINKING)
    assert len(thinking.payload["text"]) <= LABEL_CAP
    assert thinking.payload["text"].endswith("…")
    # And it is a single line: newlines were collapsed, so one frame is one row.
    assert "\n" not in thinking.payload["text"]


def test_thinking_visibility_off_emits_no_thinking_event() -> None:
    loop = _loop_with_thinking("", ReasoningVisibility.OFF)
    events = loop._handle_signal(
        AgentSignal(AgentSignalKind.THINKING, text="Vou raciocinar."),
        _turn(),  # type: ignore[arg-type]
        loop.events.emit,
        [],
    )
    # The status update is telemetry and is NOT gated by the privacy policy.
    assert [event.type for event in events] == [RuntimeEventType.STATUS_UPDATE]
    assert loop.reasoning_text == ""


def test_thinking_visibility_full_passes_the_text_through() -> None:
    loop = _loop_with_thinking("", ReasoningVisibility.FULL)
    events = loop._handle_signal(
        AgentSignal(AgentSignalKind.THINKING, text="Primeiro comparo, depois corrijo."),
        _turn(),  # type: ignore[arg-type]
        loop.events.emit,
        [],
    )
    thinking = next(e for e in events if e.type is RuntimeEventType.THINKING)
    assert thinking.payload["text"] == "Primeiro comparo, depois corrijo."
    assert loop.reasoning_text == "Primeiro comparo, depois corrijo."


def test_thinking_visibility_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUS_REASONING_VISIBILITY", "off")
    loop = _loop_with_thinking("")
    assert loop.reasoning_visibility is ReasoningVisibility.OFF
    events = loop._handle_signal(
        AgentSignal(AgentSignalKind.THINKING, text="algo"),
        _turn(),  # type: ignore[arg-type]
        loop.events.emit,
        [],
    )
    assert not [e for e in events if e.type is RuntimeEventType.THINKING]


# ------------------------------------------------------ visibility policy
def test_label_policy_truncates_and_sanitises() -> None:
    raw = "<think>\nVou ler\no ficheiro\n</think>  e depois responder"
    label = bound_reasoning_text(raw, visibility=ReasoningVisibility.LABEL)
    assert "<think>" not in label
    assert "\n" not in label
    assert label.startswith("Vou ler o ficheiro")
    assert len(label) <= LABEL_CAP


def test_off_policy_yields_nothing() -> None:
    assert bound_reasoning_text("qualquer coisa", visibility=ReasoningVisibility.OFF) == ""


def test_full_policy_passes_through_but_still_bounds() -> None:
    text = "raciocínio " * 5_000
    full = bound_reasoning_text(text, visibility=ReasoningVisibility.FULL)
    assert full.startswith("raciocínio")
    assert len(full) <= FULL_CAP + 1  # + the ellipsis
    assert full.endswith("…")


def test_label_cap_is_the_documented_default() -> None:
    assert LABEL_CAP == 160
    assert bound_label("x" * 500) == "x" * 159 + "…"
    # A label is never empty: a row always has something to render.
    assert reasoning_label_or_default("") == "a definir a abordagem"
    assert reasoning_label_or_default("   ") == "a definir a abordagem"


def test_visibility_for_strength_can_only_narrow() -> None:
    # low/"" can never unlock `full`, whatever the operator chose.
    assert visibility_for_strength("", operator_visibility=ReasoningVisibility.FULL) is (
        ReasoningVisibility.LABEL
    )
    assert visibility_for_strength("low", operator_visibility=ReasoningVisibility.FULL) is (
        ReasoningVisibility.LABEL
    )
    # medium/high unlock the operator's own opt-in…
    assert visibility_for_strength("medium", operator_visibility=ReasoningVisibility.FULL) is (
        ReasoningVisibility.FULL
    )
    assert visibility_for_strength("high", operator_visibility=ReasoningVisibility.FULL) is (
        ReasoningVisibility.FULL
    )
    # …and grant nothing when the operator did not opt in.
    assert visibility_for_strength("high", operator_visibility=ReasoningVisibility.LABEL) is (
        ReasoningVisibility.LABEL
    )
    # `off` wins over everything.
    assert visibility_for_strength("high", operator_visibility=ReasoningVisibility.OFF) is (
        ReasoningVisibility.OFF
    )


def test_unknown_visibility_env_value_falls_back_toward_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.runtime.reasoning import reasoning_visibility

    monkeypatch.setenv("NEXUS_REASONING_VISIBILITY", "everything-please")
    assert reasoning_visibility() is ReasoningVisibility.LABEL
    monkeypatch.delenv("NEXUS_REASONING_VISIBILITY", raising=False)
    assert reasoning_visibility() is ReasoningVisibility.LABEL


# ------------------------------------------------------------- SSE transport
def test_thinking_event_maps_to_exactly_one_ordered_stream_event() -> None:
    """D3 + AGENTS.md rule 5: one frame, carrying (run_id, seq, event_id)."""
    from backend.orchestrator.routes.chat_primary import runtime_event_to_stream_events

    stream = RunEventStream("run-transport")
    event = stream.emit(
        RuntimeEventType.THINKING,
        text="Vou comparar a implementação com o teste.",
        label="a raciocinar",
    )
    frames = runtime_event_to_stream_events(event)

    assert len(frames) == 1
    frame = frames[0]
    assert frame.type == "thinking"
    assert frame.content
    assert len(frame.content) <= LABEL_CAP
    # The decorator must keep stamping: the frontend's RunEventBuffer reads
    # these three at the frame root and refuses to order without them.
    assert frame.run_id == event.run_id
    assert frame.seq == event.seq
    assert frame.event_id == event.event_id
    assert frame.data is not None
    assert frame.data["seq"] == event.seq
    assert frame.data["run_id"] == event.run_id
    assert frame.data["kind"] == RuntimeEventType.THINKING.value
    # The timeline row shows a short verb; the text is the panel body.
    assert frame.data["label"] == "a raciocinar"
    assert frame.data["reasoning_chars"] == len(frame.content)


def test_thinking_event_produces_no_frame_when_visibility_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.orchestrator.routes.chat_primary import runtime_event_to_stream_events

    monkeypatch.setenv("NEXUS_REASONING_VISIBILITY", "off")
    stream = RunEventStream("run-off")
    event = stream.emit(RuntimeEventType.THINKING, text="segredo")
    assert runtime_event_to_stream_events(event) == []


def test_stream_event_thinking_is_a_legal_event_type() -> None:
    from backend.models.api import EventType

    assert "thinking" in EventType.__args__


# ------------------------------------------------------------- provider parse
def test_openai_reasoning_content_is_separated_from_the_answer() -> None:
    """D6: `delta.reasoning_content` used to be dropped on the floor."""
    collected: list[str] = []
    sink = reasoning_sink(collected)
    frame = {
        "choices": [
            {
                "delta": {
                    "reasoning_content": "Primeiro confirmo a assinatura.",
                    "content": "A resposta é offset + 1.",
                }
            }
        ]
    }
    parsed = deliver_reasoning(sink, "openai", frame)
    assert parsed.reasoning == "Primeiro confirmo a assinatura."
    assert parsed.content == "A resposta é offset + 1."
    assert "".join(collected) == "Primeiro confirmo a assinatura."
    # The answer text must not contain the reasoning, and vice versa.
    assert parsed.reasoning not in parsed.content


def test_openai_flattens_reasoning_field_and_usage() -> None:
    parsed = parse_provider_delta(
        "openai",
        {
            "choices": [{"delta": {"reasoning": "outro nome de campo"}}],
            "usage": {"completion_tokens_details": {"reasoning_tokens": 512}},
        },
    )
    assert parsed.reasoning == "outro nome de campo"
    assert parsed.usage == {"reasoning_tokens": 512}


def test_openai_responses_api_summary_delta() -> None:
    parsed = parse_provider_delta(
        "openai",
        {
            "type": "response.reasoning_summary_text.delta",
            "delta": "Resumo do plano",
        },
    )
    assert parsed.reasoning == "Resumo do plano"
    assert parsed.content == ""


def test_anthropic_thinking_and_signature_deltas() -> None:
    collected: list[str] = []
    sink = reasoning_sink(collected)
    thinking = deliver_reasoning(
        sink,
        "anthropic",
        {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "Vou verificar o índice."},
        },
    )
    assert thinking.reasoning == "Vou verificar o índice."
    assert thinking.content == ""

    signature = deliver_reasoning(
        sink,
        "anthropic",
        {
            "type": "content_block_delta",
            "delta": {"type": "signature_delta", "signature": "abc123"},
        },
    )
    assert signature.signature == "abc123"
    assert signature.reasoning == ""
    # The signature is an integrity token and must never reach the user.
    assert "abc123" not in "".join(collected)

    text = deliver_reasoning(
        sink,
        "anthropic",
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Olá."}},
    )
    assert text.content == "Olá."
    assert "".join(collected) == "Vou verificar o índice."


def test_anthropic_redacted_thinking_is_reported_not_rendered() -> None:
    collected: list[str] = []
    sink = reasoning_sink(collected)
    block = deliver_reasoning(
        sink,
        "anthropic",
        {"type": "content_block_start", "content_block": {"type": "redacted_thinking"}},
    )
    assert block.redacted is True
    assert collected == []


def test_anthropic_thinking_payload_respects_the_budget_constraint() -> None:
    from backend.llm.anthropic_provider import AnthropicProvider

    payload = {"max_tokens": 4096}
    assert AnthropicProvider._thinking_payload(payload, {"think": True}) is True
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    # budget_tokens must stay strictly below max_tokens or Anthropic 400s.
    assert payload["thinking"]["budget_tokens"] < payload["max_tokens"]
    # Extended thinking is incompatible with a non-default temperature.
    payload2 = {"max_tokens": 4096, "temperature": 0.4}
    AnthropicProvider._thinking_payload(payload2, {"think": True})
    assert "temperature" not in payload2
    # No reasoning requested -> no thinking block (unchanged behaviour).
    plain = {"max_tokens": 4096}
    assert AnthropicProvider._thinking_payload(plain, None) is False
    assert "thinking" not in plain
    # A budget that cannot fit below max_tokens is refused rather than sent.
    tight = {"max_tokens": 512}
    assert AnthropicProvider._thinking_payload(tight, {"think": True}) is False


def test_ollama_message_thinking_is_separated() -> None:
    collected: list[str] = []
    sink = reasoning_sink(collected)
    parsed = deliver_reasoning(
        sink,
        "ollama",
        {"message": {"thinking": "O modelo está a pensar", "content": "Resposta."}},
    )
    assert parsed.reasoning == "O modelo está a pensar"
    assert parsed.content == "Resposta."
    assert collected == ["O modelo está a pensar"]


def test_gemini_thought_parts_are_separated_from_answer_parts() -> None:
    collected: list[str] = []
    sink = reasoning_sink(collected)
    frame = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Plano: comparar as duas implementações.", "thought": True},
                        {"text": "A resposta é 1.", "thought": False},
                    ]
                }
            }
        ],
        "usageMetadata": {"thoughtsTokenCount": 128},
    }
    parsed = deliver_reasoning(sink, "gemini", frame)
    assert parsed.reasoning == "Plano: comparar as duas implementações."
    assert parsed.content == "A resposta é 1."
    assert parsed.usage == {"reasoning_tokens": 128}


def test_gemini_thought_signature_alone_never_re_routes_answer_text() -> None:
    parsed = parse_provider_delta(
        "gemini",
        {
            "candidates": [
                {"content": {"parts": [{"text": "Resposta final.", "thoughtSignature": "sig"}]}}
            ]
        },
    )
    assert parsed.content == "Resposta final."
    assert parsed.reasoning == ""


@pytest.mark.parametrize(
    ("dialect", "frame"),
    [
        ("openai", {"choices": "not-a-list"}),
        ("openai", {"choices": [{"delta": None}]}),
        ("openai", {"choices": [{"delta": {"tool_calls": "nope"}}]}),
        ("openai", {"choices": [{"delta": {"content": 12}}]}),
        ("anthropic", {"type": "content_block_delta", "delta": "text"}),
        ("anthropic", {"delta": {"type": "thinking_delta", "thinking": None}}),
        ("anthropic", {"type": 12, "delta": {"type": 13}}),
        ("ollama", {"message": "not-a-dict"}),
        ("ollama", {"message": {"content": ["unexpected"]}}),
        ("gemini", {"candidates": "nope"}),
        ("gemini", {"candidates": [{"content": "nope"}]}),
        ("gemini", {"candidates": [{"content": {"parts": [None, 5, {}]}}]}),
        ("unknown-dialect", {"content": "still readable"}),
    ],
)
def test_parser_never_raises_on_a_malformed_or_absent_field(
    dialect: str, frame: object
) -> None:
    parsed = parse_provider_delta(dialect, frame)
    assert isinstance(parsed.reasoning, str)
    assert isinstance(parsed.content, str)


def test_parser_never_raises_on_a_non_dict_frame() -> None:
    for dialect in ("openai", "anthropic", "ollama", "gemini"):
        for frame in (None, "text", 5, [1, 2], object()):
            parsed = parse_provider_delta(dialect, frame)
            assert parsed.reasoning == ""
            assert parsed.content == ""


def test_reasoning_sink_is_optional_and_bounded() -> None:
    assert reasoning_sink(None) is None
    collected: list[str] = []
    sink = reasoning_sink(collected, cap=10)
    sink("x" * 100)
    assert "".join(collected) == "x" * 10
    sink("ignored because full")
    assert "".join(collected) == "x" * 10
    # A redacted block is a signal, not text.
    other: list[str] = []
    sink2 = reasoning_sink(other)
    sink2("", redacted=True)
    assert other == []


def test_airllm_thinking_disable_respects_the_policy() -> None:
    from backend.llm.airllm_provider import AirLLMProvider

    guard = AirLLMProvider._inject_thinking_disable
    plain = {"temperature": 0.1}
    assert guard(None, "qwen2.5-coder:7b", plain)["thinking"] is False
    # A caller that opened the reasoning channel keeps thinking on.
    with_sink = {**plain, "_nexus_reasoning_sink": lambda *_a, **_k: None}
    assert "thinking" not in guard(None, "qwen2.5-coder:7b", with_sink)
    # A non-qwen model is untouched either way.
    assert "thinking" not in guard(None, "deepseek-r1:7b", plain)


def test_openai_usage_only_adds_reasoning_tokens_when_reported() -> None:
    from backend.llm.openai_provider import OpenAIProvider

    extract = OpenAIProvider._extract_usage
    plain = extract(None, {"usage": {"prompt_tokens": 1, "completion_tokens": 2}})
    assert plain == {"input_tokens": 1, "output_tokens": 2, "total_tokens": 0}
    deep = extract(
        None,
        {
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "completion_tokens_details": {"reasoning_tokens": 900},
            }
        },
    )
    assert deep["reasoning_tokens"] == 900


# --------------------------------------------------------------- accounting
def test_usage_metric_reports_reasoning_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """The panel showed 0 forever because the field was hardcoded."""
    from backend.orchestrator.routes.chat_primary import build_usage_metric

    class _Request:
        message = "corrige o bug do offset"
        model = "fast"

    usage = build_usage_metric(
        llm_client=object(),
        req=_Request(),
        answer="Resposta.",
        history=[],
        finish_reason="stop",
        reasoning_text="Vou comparar as duas implementações antes de alterar o ficheiro.",
    )
    assert usage["reasoning_tokens"] > 0
    assert usage["context"]["reasoning"] == usage["reasoning_tokens"]
    assert count_reasoning_tokens("") == 0


def test_usage_metric_prefers_provider_reported_reasoning_tokens() -> None:
    from backend.orchestrator.routes.chat_primary import build_usage_metric

    class _Request:
        message = "oi"
        model = "fast"

    provider = type(
        "P", (), {"last_usage": {"input_tokens": 10, "output_tokens": 4, "reasoning_tokens": 77}}
    )()
    usage = build_usage_metric(
        llm_client=provider,
        req=_Request(),
        answer="a",
        history=[],
        finish_reason="stop",
        reasoning_text="qualquer texto",
    )
    assert usage["reasoning_tokens"] == 77
    assert usage["source"] == "provider"


def test_usage_metric_without_reasoning_reports_zero() -> None:
    from backend.orchestrator.routes.chat_primary import build_usage_metric

    class _Request:
        message = "oi"
        model = "fast"

    usage = build_usage_metric(
        llm_client=object(),
        req=_Request(),
        answer="a",
        history=[],
        finish_reason="stop",
    )
    assert usage["reasoning_tokens"] == 0
    assert usage["context"]["reasoning"] == 0


# ---------------------------------------------------------- thinking_strength
def test_thinking_strength_drives_enable_thinking_on_the_primary_lane() -> None:
    """D4: `enable_thinking` was hardcoded to False on this lane."""
    import inspect

    from backend.orchestrator.routes import chat_primary

    source = inspect.getsource(chat_primary.make_signal_stream)
    assert "enable_thinking=enable_thinking" in source
    assert "enable_thinking=False" not in source


def test_legacy_lane_still_produces_thinking_frames() -> None:
    """The legacy lane's two thinking paths must survive the change."""
    from backend.agents.event_protocol import encode_event
    from backend.orchestrator.routes.chat import _parse_inline_events

    # (a) a raw <thinking> block written by the model
    parsed = _parse_inline_events("<think>abordagem pública</think>resposta", "CODER")
    assert [event.type for event in parsed] == ["thinking", "token"]
    assert parsed[0].content == "abordagem pública"

    # (b) the ReAct loop's <event>thinking|iteration:N</event> marker
    parsed = _parse_inline_events(encode_event("thinking", "iteration:2"), "CODER")
    assert parsed[0].type == "thinking"
    assert "passo 2" in parsed[0].content


def test_provider_reasoning_payload_is_not_replaced_by_a_generic_label() -> None:
    """The panel showed "A analisar a tarefa…" for *every* thinking payload.

    ``_parse_inline_events`` used to branch only on the iteration marker and
    substituted a generic label otherwise, discarding the bounded approach text
    the agent had just published. That is the difference between a panel that
    says something and one that says nothing.
    """
    from backend.agents.event_protocol import encode_event
    from backend.orchestrator.routes.chat import _parse_inline_events

    payload = "Primeiro comparo as duas implementacoes antes de editar o ficheiro."
    parsed = _parse_inline_events(encode_event("thinking", payload), "NEXUS")
    assert [event.type for event in parsed] == ["thinking"]
    assert parsed[0].content == payload


def test_provider_reasoning_payload_is_bounded_by_the_sse_parser() -> None:
    from backend.agents.event_protocol import encode_event
    from backend.orchestrator.routes.chat import _parse_inline_events

    parsed = _parse_inline_events(encode_event("thinking", "y" * 5_000), "NEXUS")
    assert len(parsed[0].content) <= LABEL_CAP + 1  # + the ellipsis


def test_provider_reasoning_never_mixes_into_the_answer() -> None:
    """End-to-end through a real agent: two channels, one answer."""
    import logging

    from backend.agents.base import AgentRequest
    from backend.agents.nexus_primary import NexusPrimaryAgent
    from backend.orchestrator.routes.chat import _parse_inline_events
    from backend.runtime.reasoning import deliver_reasoning

    logging.disable(logging.CRITICAL)

    class _Client:
        provider_name = "openai"

        async def chat_stream(self, model, messages, options=None, **kw):
            sink = (options or {}).get("_nexus_reasoning_sink")
            for chunk in ("Primeiro comparo ", "as duas implementacoes ", "antes de editar."):
                deliver_reasoning(
                    sink, "openai", {"choices": [{"delta": {"reasoning_content": chunk}}]}
                )
            yield "Resposta final."

    async def run() -> list:
        agent = NexusPrimaryAgent()
        request = AgentRequest(
            session_id="s1",
            query="compara",
            client=_Client(),
            enable_thinking=True,
            max_iterations=1,
        )
        parsed: list = []
        async for chunk in agent.run(request):
            parsed.extend(_parse_inline_events(chunk, "NEXUS"))
        return parsed

    frames = asyncio.run(run())
    thinking = [event.content or "" for event in frames if event.type == "thinking"]
    answer = "".join(event.content or "" for event in frames if event.type == "token")

    assert any("Primeiro comparo" in text for text in thinking)
    assert answer.strip() == "Resposta final."
    assert "Primeiro comparo" not in answer


def test_legacy_frames_are_stamped_with_the_bus_ordering_envelope() -> None:
    """AGENTS.md rule 5: the legacy lane reuses the bus's own (run_id, seq).

    Checked on the module source because the bridge lives in a nested generator
    that is not reachable as a module attribute. The two things that matter:
    the envelope is READ from the bus-stamped event, and no second counter was
    introduced next to it.
    """
    import inspect

    from backend.orchestrator.routes import chat

    source = inspect.getsource(chat)
    assert 'getattr(evt, "run_id", "")' in source
    assert 'getattr(evt, "seq", 0)' in source
    assert 'getattr(evt, "event_id", "")' in source
    assert '_stamped(StreamEvent(type="thinking"' in source
    # No per-run counter of its own: the bus owns sequencing.
    assert "self._seq[" not in source
    assert "EventBus._assign_seq(" not in source


@pytest.mark.parametrize(
    ("strength", "conversational", "expected"),
    [
        ("high", False, True),
        ("high", True, True),
        ("medium", False, True),
        ("medium", True, False),
        ("low", False, False),
        ("low", True, False),
        ("", False, False),
        ("", True, False),
        ("nonsense", False, False),
    ],
)
def test_reasoning_enabled_matches_the_legacy_lane(
    strength: str, conversational: bool, expected: bool
) -> None:
    from backend.orchestrator.routes.chat_primary import _reasoning_enabled

    assert _reasoning_enabled(strength, fast_chat_turn=conversational) is expected


@pytest.mark.parametrize(
    ("strength", "conversational", "expected"),
    [
        # chat.py:3690 adds the guidance for ANY known strength, as long as the
        # turn is not a fast-chat turn. The primary lane must agree.
        ("high", False, True),
        ("high", True, False),
        ("medium", False, True),
        ("low", False, True),
        ("", False, False),
        ("nonsense", False, False),
    ],
)
def test_reasoning_depth_addon_matches_the_legacy_lane(
    strength: str, conversational: bool, expected: bool
) -> None:
    from backend.orchestrator.routes.chat_primary import _reasoning_depth_addon

    addon = _reasoning_depth_addon(strength, fast_chat_turn=conversational)
    assert ("[REASONING DEPTH]" in addon) is expected
    if expected:
        assert "approach summary" in addon


def test_reasoning_depth_guidance_states_the_privacy_rule() -> None:
    from backend.orchestrator.routes.chat_primary import _STRENGTH_GUIDANCE

    assert set(_STRENGTH_GUIDANCE) == {"low", "medium", "high"}
    for guidance in _STRENGTH_GUIDANCE.values():
        assert "approach summary" in guidance
    # `high` is the only one that must spell out the private-CoT prohibition.
    assert "never private chain-of-thought" in _STRENGTH_GUIDANCE["high"]


# ------------------------------------------------------------------- swarm
def test_swarm_output_has_no_literal_thinking_tag() -> None:
    """D12: `split_stream` drops frames but not the raw `<think>` token."""
    from backend.orchestrator.swarm import _strip_thinking_markup

    aggregated = "<think>\nO plano é comparar.\n</think>\nA resposta final está acima."
    cleaned = _strip_thinking_markup(aggregated)
    assert "<thinking" not in cleaned
    assert "</think>" not in cleaned
    # The agent's own words are kept: only the transport markup goes.
    assert "O plano é comparar." in cleaned
    assert "A resposta final está acima." in cleaned


def test_swarm_strip_helper_is_a_noop_without_markup() -> None:
    from backend.orchestrator.swarm import _strip_thinking_markup

    assert _strip_thinking_markup("resposta simples") == "resposta simples"
