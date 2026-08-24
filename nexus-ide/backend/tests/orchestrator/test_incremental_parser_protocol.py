"""P2 da auditoria 2026-08-16, ao nível do parser incremental do chat.

Um ficheiro de três linhas que mencione ``<thinking>`` ou ``<tool_call>``
bastava para o protocolo interno aparecer no chat como se fosse a resposta do
assistente — e para o evento estruturado ``tool_result`` desaparecer. O
tamanho nunca foi o fator; o conteúdo era.
"""

from __future__ import annotations

import json

from backend.agents.event_protocol import encode_event
from backend.orchestrator.routes.chat import _IncrementalResponseParser


def _feed(chunks: list[str]) -> list:
    parser = _IncrementalResponseParser("NEXUS")
    events = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    events.extend(parser.flush())
    return events


def test_tool_result_with_thinking_marker_still_emits_a_structured_event() -> None:
    payload = json.dumps({"content": 'A = 1\nMARK = "<thinking>"\nB = 2'})
    frame = encode_event("tool_result", "read_file", payload)

    events = _feed(["Vou ler o ficheiro. ", frame, "Pronto."])

    kinds = [event.type for event in events]
    assert "tool_result" in kinds, kinds
    tool_result = next(event for event in events if event.type == "tool_result")
    assert tool_result.tool_name == "read_file"
    assert "<thinking>" in tool_result.tool_result["content"]

    visible = "".join(event.content or "" for event in events if event.type == "token")
    assert "<event>" not in visible
    assert "tool_result|" not in visible


def test_tool_call_marker_inside_a_result_does_not_swallow_the_reply() -> None:
    frame = encode_event(
        "tool_result", "read_file", json.dumps({"content": "<tool_call>x</tool_call>"})
    )
    events = _feed([frame, "A resposta continua aqui."])
    visible = "".join(event.content or "" for event in events if event.type == "token")
    assert "A resposta continua aqui." in visible


def test_frame_split_across_chunks_is_still_atomic() -> None:
    frame = encode_event("tool_result", "read_file", json.dumps({"content": "ok"}))
    half = len(frame) // 2
    events = _feed([frame[:half], frame[half:]])
    assert [event.type for event in events] == ["tool_result"]


def test_truncated_frame_is_not_painted_into_the_conversation() -> None:
    frame = encode_event("tool_result", "read_file", json.dumps({"content": "ok"}))
    events = _feed(["texto antes " + frame[: len(frame) // 2]])
    visible = "".join(event.content or "" for event in events if event.type == "token")
    assert visible.strip() == "texto antes"
    assert "<event>" not in visible


def test_plain_thinking_still_becomes_a_thinking_event() -> None:
    events = _feed(["<thinking>a pensar</thinking>resposta"])
    kinds = [event.type for event in events]
    assert "thinking" in kinds
    visible = "".join(event.content or "" for event in events if event.type == "token")
    assert visible.strip() == "resposta"
