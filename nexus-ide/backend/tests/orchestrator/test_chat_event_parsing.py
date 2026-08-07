"""Regression tests for translating agent inline events to chat SSE events."""

from __future__ import annotations

from backend.orchestrator.routes.chat import (
    _command_help_text,
    _existing_directory_from_message,
    _IncrementalResponseParser,
    _is_command_help_request,
    _parse_inline_events,
)


def test_agent_error_event_reaches_the_frontend_as_an_error() -> None:
    events = _parse_inline_events("<event>error|provider unavailable</event>", "CODER")

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].agent == "CODER"
    assert events[0].content == "provider unavailable"


def test_react_thinking_iteration_marker_reaches_the_frontend() -> None:
    events = _parse_inline_events("<event>thinking|iteration:3</event>", "CODER")

    assert len(events) == 1
    assert events[0].type == "thinking"
    assert events[0].agent == "CODER"
    assert events[0].content == "A analisar a tarefa (passo 3)…"


def test_text_after_tool_event_is_not_dropped() -> None:
    events = _parse_inline_events(
        '<event>tool_call|read_file|{"path":"README.md"}</event>Resposta final.',
        "CODER",
    )

    assert [event.type for event in events] == ["tool_call", "token"]
    assert events[1].content == "Resposta final."


def test_thinking_is_emitted_before_the_provider_closes_the_block() -> None:
    parser = _IncrementalResponseParser("ARCHITECT")

    first = parser.feed("<think>Estou a comparar")
    second = parser.feed(" duas abordagens antes de decidir</think>Resposta")
    second.extend(parser.flush())

    thinking = [event.content for event in first + second if event.type == "thinking"]
    visible = [event.content for event in first + second if event.type == "token"]

    assert thinking == ["Estou a comparar", " duas abordagens antes de decidir"]
    assert "Resposta" in "".join(visible)


def test_thinking_tags_split_across_provider_chunks_are_not_leaked() -> None:
    parser = _IncrementalResponseParser("CODER")

    events = parser.feed("<thin")
    events.extend(parser.feed("k>Plano curto</think>feito"))
    events.extend(parser.flush())

    assert "".join(event.content or "" for event in events if event.type == "thinking") == "Plano curto"
    assert "".join(event.content or "" for event in events if event.type == "token") == "feito"


def test_native_tool_markup_is_not_rendered_as_chat_text() -> None:
    parser = _IncrementalResponseParser("CODER")

    events = parser.feed("Antes <tool_cal")
    events.extend(
        parser.feed(
            "l><function=list_dir><parameter=path>backend</parameter>"
            "</function></tool_call>Depois"
        )
    )
    events.extend(parser.flush())

    text = "".join(event.content or "" for event in events if event.type == "token")
    assert text == "Antes Depois"


def test_tool_fences_split_across_chunks_are_not_rendered() -> None:
    parser = _IncrementalResponseParser("ARCHITECT")

    events = parser.feed("Antes ```to")
    events.extend(
        parser.feed(
            'ol\n{"name":"list_dir","arguments":{"path":"."}}\n```Depois'
        )
    )
    events.extend(parser.flush())

    text = "".join(event.content or "" for event in events if event.type == "token")
    assert text == "Antes Depois"


def test_restarted_malformed_tool_fence_does_not_leak_transport_text() -> None:
    parser = _IncrementalResponseParser("ARCHITECT")

    events = parser.feed(
        'Início\n```tool\n{"name":"list_dir","arguments":{"path":"C:/tmp"\n'
        '```tool\n{"name":"list_dir","arguments":{"path":"C:/tmp"}}\n```\nFim'
    )
    events.extend(parser.flush())

    text = "".join(event.content or "" for event in events if event.type == "token")
    assert text == "Início\n\nFim"


def test_command_help_is_backed_by_the_real_catalog() -> None:
    assert _is_command_help_request("/command")
    assert _is_command_help_request("q comandos tem")

    help_text = _command_help_text()

    assert "/proof" in help_text
    assert "/forge" in help_text
    assert "/write" not in help_text


def test_unquoted_existing_project_path_is_recovered_from_message(tmp_path) -> None:
    project = tmp_path / "red nexus"
    project.mkdir()

    result = _existing_directory_from_message(
        f"analisa {project} verifica tudo e apresenta os resultados"
    )

    assert result == str(project.resolve())


def test_json_safe_serializes_live_dataclasses() -> None:
    """A live DependencyGraph/ExecutionPlan in event data must not kill the SSE bridge.

    Regression: ORCHESTRATOR_FINISHED published ``result.__dict__`` containing
    a live ExecutionPlan; ``model_dump_json()`` raised
    "Unable to serialize unknown type: DependencyGraph" and the entire event
    bridge died silently — the chat appeared unresponsive at run completion.
    """
    from backend.models.api import StreamEvent
    from backend.orchestrator.dependency_graph import DependencyGraph, ExecutionPlan, TaskNode
    from backend.orchestrator.routes.chat import _json_safe, _sse

    plan = ExecutionPlan.from_steps(
        title="t", description="d", steps=[TaskNode(name="s1", description="d")]
    )
    graph = DependencyGraph()
    graph.add_task(TaskNode(name="s2", description="d"))

    safe = _json_safe({"plan": plan, "graph": graph, "state": "COMPLETED"})

    frame = _sse(StreamEvent(type="progress", agent="ORCHESTRATOR", data=safe))
    assert frame.startswith("data: {")
    assert isinstance(safe["graph"], dict)
    assert isinstance(safe["plan"], dict)


def test_json_safe_handles_enums_sets_and_deep_nesting() -> None:
    import enum
    import json

    from backend.orchestrator.routes.chat import _json_safe

    class Color(enum.Enum):
        RED = "red"

    payload = {
        "enum": Color.RED,
        "set": {1, 2},
        "tuple": (3, 4),
        "deep": {"a": {"b": {"c": [{"custom": object()}]}}},
        "plain": "texto",
    }

    safe = _json_safe(payload)
    json.dumps(safe)  # must not raise
    assert safe["enum"] == "red"
    assert sorted(safe["set"]) == [1, 2]
    assert safe["tuple"] == [3, 4]
    assert safe["plain"] == "texto"
