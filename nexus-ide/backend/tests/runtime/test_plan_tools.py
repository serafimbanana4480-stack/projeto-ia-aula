"""PLAN_UPDATED events from the todo tools in the primary loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from backend.runtime.events import RuntimeEventType
from backend.runtime.primary import (
    AgentSignal,
    AgentSignalKind,
    Observation,
    PrimaryLoop,
    PrimaryTurn,
    VerificationResult,
)


def token(text: str) -> AgentSignal:
    return AgentSignal(AgentSignalKind.TOKEN, text=text)


def signals(*items: AgentSignal):
    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        async def iterator() -> AsyncIterator[AgentSignal]:
            for item in items:
                await asyncio.sleep(0)
                yield item

        return iterator()

    return factory


def tool_result(name: str, **payload) -> AgentSignal:
    return AgentSignal(AgentSignalKind.TOOL_RESULT, tool_name=name, payload=payload)


def tool_call(name: str, **args) -> AgentSignal:
    return AgentSignal(AgentSignalKind.TOOL_CALL, tool_name=name, payload=args)


async def observe_noop(turn: PrimaryTurn) -> Observation:
    return Observation(summary="sem trabalho de ficheiros")


async def collect(loop) -> list:
    return [event async for event in loop.run()]


@pytest.mark.asyncio
async def test_todo_tools_emit_plan_updated() -> None:
    loop = PrimaryLoop(
        run_id="run-plan",
        query="planeia e executa",
        stream=signals(
            token("Vou planear."),
            tool_call("todo_write", operation="add", content="passo 1"),
            tool_result(
                "todo_write",
                ok=True,
                operation="add",
                todos=[{"id": 1, "content": "passo 1", "status": "pending"}],
            ),
            tool_call("todo_list"),
            tool_result(
                "todo_list",
                ok=True,
                todos=[
                    {"id": 1, "content": "passo 1", "status": "in_progress"},
                    {"id": 2, "content": "passo 2", "status": "pending"},
                ],
            ),
            token("Feito."),
        ),
        observe=observe_noop,
        verify=lambda request: VerificationResult(ran=False, ok=True, summary="n/a"),
        run_subagent=None,
        max_cycles=1,
    )
    events = await collect(loop)
    plan_events = [e for e in events if e.type is RuntimeEventType.PLAN_UPDATED]

    assert [e.payload["tool"] for e in plan_events] == ["todo_write", "todo_list"]
    assert plan_events[0].payload["todos"] == [
        {"id": 1, "content": "passo 1", "status": "pending"}
    ]
    assert len(plan_events[1].payload["todos"]) == 2
    # seq order is still strictly increasing across the whole stream
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)


@pytest.mark.asyncio
async def test_wrapped_todo_tool_result_emits_root_todos_for_plan_consumers() -> None:
    """The real execute_tool contract nests handler output under ``result``."""
    todos = [
        {"id": 4, "content": "Guardar o progresso", "priority": "high", "status": "pending"}
    ]
    loop = PrimaryLoop(
        run_id="run-plan-wrapped",
        query="atualiza o plano",
        stream=signals(
            tool_call("todo_write", operation="add", content="Guardar o progresso"),
            tool_result(
                "todo_write",
                ok=True,
                result={
                    "ok": True,
                    "operation": "add",
                    "session_id": "session-1",
                    "todos": todos,
                    "counts": {"pending": 1, "in_progress": 0, "completed": 0, "cancelled": 0, "total": 1},
                },
            ),
            token("Plano atualizado."),
        ),
        observe=observe_noop,
        verify=lambda request: VerificationResult(ran=False, ok=True, summary="n/a"),
        run_subagent=None,
        max_cycles=1,
    )

    events = await collect(loop)
    plan_events = [event for event in events if event.type is RuntimeEventType.PLAN_UPDATED]

    assert len(plan_events) == 1
    assert plan_events[0].payload["todos"] == todos


@pytest.mark.asyncio
async def test_sequential_thinking_does_not_emit_plan_updated() -> None:
    loop = PrimaryLoop(
        run_id="run-think",
        query="pensa passo a passo",
        stream=signals(
            token("Vou raciocinar."),
            tool_call("sequential_thinking", thought="passo"),
            tool_result(
                "sequential_thinking",
                ok=True,
                thought="passo",
                thoughts=[{"thought": "passo", "thought_number": 1}],
            ),
            token("Concluí."),
        ),
        observe=observe_noop,
        verify=lambda request: VerificationResult(ran=False, ok=True, summary="n/a"),
        run_subagent=None,
        max_cycles=1,
    )
    events = await collect(loop)

    assert not any(e.type is RuntimeEventType.PLAN_UPDATED for e in events)
    kinds = [e.type.value for e in events]
    assert "tool_started" in kinds and "tool_completed" in kinds
