"""Phase 3 — the primary agent loop, end to end, without a provider.

Every collaborator the loop needs is injected, so these tests exercise the
real control flow: the same code path the chat route drives, with fake
tokens instead of a model.

The cases mirror the phase 3 acceptance list:

1. a simple task runs with no subagent at all;
2. a run continues normally when no plan exists;
3. dependent tasks never overlap;
4. independent tasks really do run in parallel;
5. STOP pauses and CONTINUE resumes the same run;
6. a browser refresh replays exactly the missed events;
7. ``TIME_TO_FIRST_ACTION`` / ``TIME_TO_FIRST_USEFUL_WORK`` are measured.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import pytest

from backend.runtime.events import RunEventStream, RuntimeEventType
from backend.runtime.primary import (
    AgentSignal,
    AgentSignalKind,
    Observation,
    PrimaryLoop,
    PrimaryTurn,
    SteeringChannel,
    VerificationRequest,
    VerificationResult,
)
from backend.runtime.spawn_policy import SpawnPolicy


# ---------------------------------------------------------------- helpers
def signals(*items: AgentSignal):
    """A stream factory that replays a fixed script once per cycle."""

    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        async def iterator() -> AsyncIterator[AgentSignal]:
            for item in items:
                await asyncio.sleep(0)
                yield item

        return iterator()

    return factory


def token(text: str) -> AgentSignal:
    return AgentSignal(AgentSignalKind.TOKEN, text=text)


def tool_call(name: str, **args) -> AgentSignal:
    return AgentSignal(AgentSignalKind.TOOL_CALL, tool_name=name, payload=args)


def tool_result(name: str, **payload) -> AgentSignal:
    return AgentSignal(AgentSignalKind.TOOL_RESULT, tool_name=name, payload=payload)


def delegate(**payload) -> AgentSignal:
    return AgentSignal(AgentSignalKind.DELEGATE, tool_name="spawn_task", payload=payload)


async def observe_project(turn: PrimaryTurn) -> Observation:
    return Observation(
        summary="3 entradas na raiz", facts={"entries": ["a", "b", "c"]}, files_inspected=3
    )


async def collect(loop: PrimaryLoop) -> list:
    return [event async for event in loop.run()]


def types_of(events) -> list[str]:
    return [event.type.value for event in events]


# --------------------------------------------------- 1. simple task, no subagents
@pytest.mark.asyncio
async def test_simple_task_completes_without_any_subagent() -> None:
    loop = PrimaryLoop(
        run_id="run-simple",
        query="corrige o typo no README",
        stream=signals(
            token("Vou corrigir isso já."),
            tool_call("read_file", path="README.md"),
            tool_result("read_file", ok=True, files_read=1),
            tool_call("write_file", path="README.md"),
            tool_result("write_file", ok=True, paths=["README.md"]),
            token(" Feito."),
        ),
        observe=observe_project,
        verify=lambda request: VerificationResult(
            ran=True, ok=True, summary="4 passaram, 0 falharam", command="pytest"
        ),
        run_subagent=None,
        project_path="/tmp/project",
    )
    events = await collect(loop)

    assert loop.outcome.succeeded
    assert loop.outcome.subagents == ()
    assert loop.outcome.declined_subagents == ()
    assert loop.outcome.changed_files == ("README.md",)
    assert loop.outcome.verification.ok is True
    assert loop.outcome.answer == "Vou corrigir isso já. Feito."

    kinds = types_of(events)
    assert kinds[0] == "run_started"
    assert kinds[-1] == "run_completed"
    assert "subagent_started" not in kinds
    # The loop really did visit every phase of observe -> act -> tool -> test.
    assert "tool_started" in kinds and "file_changed" in kinds and "test_result" in kinds

    # Total order is intact: seq is dense and strictly increasing.
    seqs = [event.seq for event in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


@pytest.mark.asyncio
async def test_conversational_turn_without_observer_skips_project_statuses() -> None:
    loop = PrimaryLoop(
        run_id="run-chat-no-observer",
        query="Quanto é 19 vezes 23?",
        stream=signals(token("437")),
        run_subagent=None,
        project_path="",
    )

    events = await collect(loop)

    assert loop.outcome.succeeded
    assert loop.outcome.answer == "437"
    assert not any(
        event.type in {RuntimeEventType.FILE_READ, RuntimeEventType.TEST_STARTED}
        for event in events
    )
    assert not any(
        event.type is RuntimeEventType.STATUS_UPDATE
        and event.payload.get("label") == "sem observador configurado"
        for event in events
    )


@pytest.mark.asyncio
async def test_the_first_tool_call_precedes_any_planning_text() -> None:
    """The first action must not wait for a plan to be written."""
    loop = PrimaryLoop(
        run_id="run-fast",
        query="lê o backend/main.py",
        stream=signals(
            tool_call("read_file", path="backend/main.py"),
            tool_result("read_file", ok=True, files_read=1),
            token("O ficheiro arranca a app FastAPI."),
        ),
        observe=observe_project,
        project_path="/tmp/project",
    )
    events = await collect(loop)
    kinds = types_of(events)
    assert kinds.index("tool_started") < kinds.index("message_delta")


# ------------------------------------------- 2. no planner, run continues normally
@pytest.mark.asyncio
async def test_run_continues_with_no_plan_and_no_planner() -> None:
    """A missing/failed plan is not an input to this path at all.

    Phase 2 made a blocked planner non-fatal. Phase 3 goes further: the
    direct path never asks for a plan, so a planner failure cannot end a
    simple turn even in principle.
    """
    loop = PrimaryLoop(
        run_id="run-noplan",
        query="adiciona um teste para parse_config",
        stream=signals(
            tool_call("write_file", path="tests/test_config.py"),
            tool_result("write_file", ok=True, paths=["tests/test_config.py"]),
            token("Adicionei o teste e a execução terminou com sucesso."),
        ),
        observe=observe_project,
        verify=lambda request: VerificationResult(
            ran=True, ok=True, summary="1 passou, 0 falharam"
        ),
        project_path="/tmp/project",
    )
    events = await collect(loop)
    assert loop.outcome.succeeded
    assert "plan_updated" not in types_of(events)
    assert loop.outcome.cycles == 1


@pytest.mark.asyncio
async def test_failed_verification_loops_back_instead_of_ending() -> None:
    """A red test is a new observation, not a terminal state."""
    attempts: list[int] = []

    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        attempts.append(turn.cycle)
        first_cycle = turn.cycle == 1

        async def iterator() -> AsyncIterator[AgentSignal]:
            yield tool_call("write_file", path="app.py")
            yield tool_result("write_file", ok=True, paths=["app.py"])
            yield token("corrigido" if not first_cycle else "escrito")

        return iterator()

    results = iter(
        [
            VerificationResult(ran=True, ok=False, summary="1 falhou", command="pytest"),
            VerificationResult(ran=True, ok=True, summary="2 passaram", command="pytest"),
        ]
    )

    loop = PrimaryLoop(
        run_id="run-retry",
        query="corrige o bug",
        stream=factory,
        observe=observe_project,
        verify=lambda request: next(results),
        max_cycles=2,
        project_path="/tmp/project",
    )
    events = await collect(loop)

    assert attempts == [1, 2]
    assert loop.outcome.cycles == 2
    assert loop.outcome.verification.ok is True
    assert "recovery" in types_of(events)
    # The second cycle was told *why* it was running again.
    assert loop.telemetry.retries == 1


@pytest.mark.asyncio
async def test_final_failed_verification_is_not_reported_as_completed() -> None:
    loop = PrimaryLoop(
        run_id="run-final-red",
        query="corrige o bug",
        stream=signals(token("Apliquei a alteração.")),
        observe=observe_project,
        verify=lambda request: VerificationResult(
            ran=True, ok=False, summary="1 falhou", command="pytest"
        ),
        max_cycles=1,
        project_path="/tmp/project",
    )

    events = await collect(loop)

    assert loop.outcome.failed is True
    assert loop.outcome.error == "A verificação final falhou: 1 falhou"
    assert "run_failed" in types_of(events)
    assert "run_completed" not in types_of(events)


# ------------------------------------------------------- 3./4. delegation
def deep_proposal(name: str, **extra) -> dict:
    payload = {
        "name": name,
        "objective": f"objetivo de {name}",
        "definition_of_done": "critério verificável",
        "estimated_seconds": 45.0,
        "context_ready": True,
    }
    payload.update(extra)
    return payload


@pytest.mark.asyncio
async def test_independent_subagents_run_in_parallel() -> None:
    live = 0
    peak = 0

    async def run_subagent(proposal) -> str:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.05)
        live -= 1
        return f"{proposal.name} feito"

    loop = PrimaryLoop(
        run_id="run-parallel",
        query="trabalho grande",
        stream=signals(
            delegate(**deep_proposal("RESEARCHER", write_scope=["docs/a.md"])),
            delegate(**deep_proposal("ANALYZER", write_scope=["docs/b.md"])),
            token("delegado"),
        ),
        observe=observe_project,
        run_subagent=run_subagent,
        spawn_policy=SpawnPolicy(max_parallel_workers=3),
        project_path="/tmp/project",
    )
    started = time.monotonic()
    events = await collect(loop)
    elapsed = time.monotonic() - started

    assert peak == 2, "independent workers must overlap"
    # Overlap is proven by ``peak == 2`` above; this elapsed bound is only a
    # coarse guard against pathological scheduler overhead (Windows/CI noise
    # measured 0.149s against the previous 0.14s bound and flapped).
    assert elapsed < 0.45, "two 50ms workers took pathologically long"
    assert {result.status for result in loop.outcome.subagents} == {"completed"}
    assert types_of(events).count("subagent_started") == 2


@pytest.mark.asyncio
async def test_dependent_subagent_never_starts_before_its_dependency() -> None:
    order: list[str] = []

    async def run_subagent(proposal) -> str:
        order.append(f"start:{proposal.name}")
        await asyncio.sleep(0.02)
        order.append(f"end:{proposal.name}")
        return "ok"

    loop = PrimaryLoop(
        run_id="run-deps",
        query="trabalho encadeado",
        stream=signals(
            delegate(**deep_proposal("ANALYZER", write_scope=["a.py"])),
            delegate(
                **deep_proposal("REVIEWER", write_scope=["b.py"], depends_on=["ANALYZER"])
            ),
            token("delegado"),
        ),
        observe=observe_project,
        run_subagent=run_subagent,
        project_path="/tmp/project",
    )
    events = await collect(loop)

    assert order == [
        "start:ANALYZER",
        "end:ANALYZER",
        "start:REVIEWER",
        "end:REVIEWER",
    ]
    started = {
        event.payload["name"]: event
        for event in events
        if event.type.value == "subagent_started"
    }
    analyzer_task_id = started["ANALYZER"].task_id
    reviewer_started = started["REVIEWER"]
    assert reviewer_started.payload["objective"] == "objetivo de REVIEWER"
    assert reviewer_started.payload["depends_on"] == [analyzer_task_id]


@pytest.mark.asyncio
async def test_overlapping_write_scopes_are_serialised_not_raced() -> None:
    live = 0
    peak = 0

    async def run_subagent(proposal) -> str:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.02)
        live -= 1
        return "ok"

    loop = PrimaryLoop(
        run_id="run-conflict",
        query="dois workers, um ficheiro",
        stream=signals(
            delegate(**deep_proposal("CODER", write_scope=["shared.py"])),
            delegate(**deep_proposal("REFACTOR_CLEAN", write_scope=["shared.py"])),
            token("delegado"),
        ),
        observe=observe_project,
        run_subagent=run_subagent,
        project_path="/tmp/project",
    )
    await collect(loop)
    assert peak == 1, "two workers wrote the same file at the same time"


@pytest.mark.asyncio
async def test_cheap_work_is_declined_and_the_primary_does_it() -> None:
    called = False

    async def run_subagent(proposal) -> str:
        nonlocal called
        called = True
        return "ok"

    loop = PrimaryLoop(
        run_id="run-declined",
        query="tarefa pequena",
        stream=signals(
            delegate(
                name="CODER",
                objective="mudar uma linha",
                definition_of_done="a linha mudou",
                estimated_seconds=3.0,
            ),
            tool_call("write_file", path="one.py"),
            tool_result("write_file", ok=True, paths=["one.py"]),
        ),
        observe=observe_project,
        run_subagent=run_subagent,
        project_path="/tmp/project",
    )
    await collect(loop)

    assert called is False
    assert loop.outcome.declined_subagents == ("CODER",)
    assert loop.telemetry.subagents_declined == 1
    assert loop.outcome.changed_files == ("one.py",)


# ------------------------------------------------------------- 5. STOP / CONTINUE
@pytest.mark.asyncio
async def test_stop_pauses_the_run_and_continue_resumes_it() -> None:
    steering = SteeringChannel(pause_timeout=5.0)
    emitted_after_stop: list[str] = []
    seen_guidance: list[tuple[str, ...]] = []
    gate = asyncio.Event()

    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        seen_guidance.append(turn.guidance)

        async def iterator() -> AsyncIterator[AgentSignal]:
            yield token("a começar")
            gate.set()  # the test stops the run exactly here
            await asyncio.sleep(0.01)
            yield tool_call("read_file", path="x.py")
            yield tool_result("read_file", ok=True, files_read=1)
            emitted_after_stop.append("resumed")
            yield token(" terminei")

        return iterator()

    loop = PrimaryLoop(
        run_id="run-stop",
        query="tarefa longa",
        stream=factory,
        observe=observe_project,
        steering=steering,
        project_path="/tmp/project",
    )

    async def driver() -> list:
        return [event async for event in loop.run()]

    task = asyncio.create_task(driver())
    await asyncio.wait_for(gate.wait(), timeout=2)
    steering.stop()
    await asyncio.sleep(0.05)
    assert emitted_after_stop == [], "the run kept working after STOP"

    steering.cont("continua e não toques nos testes")
    events = await asyncio.wait_for(task, timeout=5)

    assert emitted_after_stop == ["resumed", "resumed"]
    assert seen_guidance[1] == ("continua e não toques nos testes",)
    assert loop.outcome.stopped is False
    labels = [
        event.payload.get("label", "")
        for event in events
        if event.type is RuntimeEventType.STATUS_UPDATE
    ]
    assert any("pausado" in label for label in labels)


@pytest.mark.asyncio
async def test_guidance_typed_during_a_run_reaches_the_next_cycle() -> None:
    seen: list[tuple[str, ...]] = []

    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        seen.append(turn.guidance)

        async def iterator() -> AsyncIterator[AgentSignal]:
            yield tool_call("write_file", path="a.py")
            yield tool_result("write_file", ok=True, paths=["a.py"])

        return iterator()

    steering = SteeringChannel()
    steering.steer("usa pytest, não unittest")
    results = iter(
        [
            VerificationResult(ran=True, ok=False, summary="falhou"),
            VerificationResult(ran=True, ok=True, summary="passou"),
        ]
    )
    loop = PrimaryLoop(
        run_id="run-steer",
        query="escreve testes",
        stream=factory,
        observe=observe_project,
        verify=lambda request: next(results),
        steering=steering,
        max_cycles=2,
        project_path="/tmp/project",
    )
    events = await collect(loop)

    assert seen[0] == ("usa pytest, não unittest",)
    assert "user_steering" in types_of(events)


@pytest.mark.asyncio
async def test_mid_run_guidance_gets_a_follow_up_cycle_even_when_initial_limit_is_one() -> None:
    stream_started = asyncio.Event()
    release_stream = asyncio.Event()
    seen: list[tuple[str, ...]] = []

    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        seen.append(turn.guidance)

        async def iterator() -> AsyncIterator[AgentSignal]:
            if turn.cycle == 1:
                stream_started.set()
                yield token("a verificar a pergunta inicial")
                await release_stream.wait()
            yield token(" resposta")

        return iterator()

    steering = SteeringChannel()
    loop = PrimaryLoop(
        run_id="run-mid-guidance",
        query="Quanto é 2 + 2?",
        stream=factory,
        steering=steering,
        max_cycles=1,
    )
    task = asyncio.create_task(collect(loop))
    await asyncio.wait_for(stream_started.wait(), timeout=2)
    assert steering.steer("Na verdade, explica também a conta.") is True
    release_stream.set()
    events = await asyncio.wait_for(task, timeout=5)

    assert seen == [(), ("Na verdade, explica também a conta.",)]
    assert "user_steering" in types_of(events)
    assert loop.outcome.cycles == 2
    assert steering.steer("chegou tarde") is False


@pytest.mark.asyncio
async def test_mid_run_guidance_continues_from_the_answer_already_streamed() -> None:
    stream_started = asyncio.Event()
    release_stream = asyncio.Event()
    turns: list[PrimaryTurn] = []

    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        turns.append(turn)

        async def iterator() -> AsyncIterator[AgentSignal]:
            if turn.cycle == 1:
                yield token("Resposta inicial.")
                stream_started.set()
                await release_stream.wait()
            else:
                yield token(" Secção complementar.")

        return iterator()

    steering = SteeringChannel()
    loop = PrimaryLoop(
        run_id="run-steer-continuation",
        query="Explica o fluxo e acrescenta uma secção se eu orientar.",
        stream=factory,
        steering=steering,
        max_cycles=1,
    )
    task = asyncio.create_task(collect(loop))
    await asyncio.wait_for(stream_started.wait(), timeout=2)
    assert steering.steer("Acrescenta isolamento de conversas.") is True
    release_stream.set()
    events = await asyncio.wait_for(task, timeout=5)

    assert turns[1].guidance == ("Acrescenta isolamento de conversas.",)
    assert turns[1].previous_answer == "Resposta inicial."
    assert loop.outcome.answer == "Resposta inicial. Secção complementar."
    assert loop.outcome.cycles == 2
    assert "user_steering" in types_of(events)


@pytest.mark.asyncio
async def test_conversational_followup_drops_regenerated_sections_before_streaming() -> None:
    stream_started = asyncio.Event()
    release_stream = asyncio.Event()
    prior = (
        "**Guia**\n\n**1. Fluxo**\n\n"
        "O fluxo já foi explicado ao utilizador com os passos e sintomas observáveis.\n\n"
        "**Checklist**\n\n- Confirmar o fluxo e guardar o resultado."
    )
    repeated = (
        "**Guia**\n\n**1. Fluxo**\n\n"
        "O fluxo já foi explicado ao utilizador com os passos e sintomas observáveis.\n\n"
        "**2. Isolamento**\n\nTestar duas conversas em paralelo e confirmar que o histórico não se mistura.\n\n"
        "**Checklist**\n\n- Confirmar o fluxo e guardar os resultados."
    )
    added_section = (
        "\n\n**2. Isolamento**\n\n"
        "Testar duas conversas em paralelo e confirmar que o histórico não se mistura."
    )
    turns: list[PrimaryTurn] = []

    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        turns.append(turn)

        async def iterator() -> AsyncIterator[AgentSignal]:
            if turn.cycle == 1:
                yield token(prior)
                stream_started.set()
                await release_stream.wait()
            else:
                for chunk in (repeated[:35], repeated[35:220], repeated[220:]):
                    yield token(chunk)

        return iterator()

    steering = SteeringChannel()
    loop = PrimaryLoop(
        run_id="run-steer-no-duplicate",
        query="Escreve um guia e acrescenta isolamento se eu orientar.",
        stream=factory,
        steering=steering,
        max_cycles=1,
    )
    task = asyncio.create_task(collect(loop))
    await asyncio.wait_for(stream_started.wait(), timeout=2)
    assert steering.steer("Acrescenta uma secção sobre isolamento.") is True
    release_stream.set()
    events = await asyncio.wait_for(task, timeout=5)

    deltas = [event.payload["text"] for event in events if event.type is RuntimeEventType.MESSAGE_DELTA]
    assert turns[1].previous_answer == prior
    assert deltas == [prior, added_section]
    assert loop.outcome.answer == prior + added_section
    assert loop.outcome.answer.count("**1. Fluxo**") == 1
    assert loop.outcome.answer.count("**Checklist**") == 1
    assert loop.outcome.answer.count("**2. Isolamento**") == 1


@pytest.mark.asyncio
async def test_conversational_followup_drops_repeated_long_paragraphs_without_headings() -> None:
    stream_started = asyncio.Event()
    release_stream = asyncio.Event()
    prior = (
        "O diagnóstico começa por confirmar o envio, a receção e a persistência da mensagem. "
        "Observa os eventos do cliente e do servidor, compara os identificadores da sessão "
        "e verifica se a resposta aparece uma única vez. Este parágrafo já está visível."
    )
    new_paragraph = (
        "Para testar duas conversas ao mesmo tempo, envia marcadores diferentes em cada uma "
        "e confirma que as respostas e o histórico continuam ligados à sessão correta."
    )
    repeated = f"{prior}\n\n{new_paragraph}"

    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        async def iterator() -> AsyncIterator[AgentSignal]:
            if turn.cycle == 1:
                yield token(prior)
                stream_started.set()
                await release_stream.wait()
            else:
                yield token(repeated)

        return iterator()

    steering = SteeringChannel()
    loop = PrimaryLoop(
        run_id="run-steer-no-duplicate-paragraph",
        query="Explica o diagnóstico e acrescenta o que eu orientar.",
        stream=factory,
        steering=steering,
        max_cycles=1,
    )
    task = asyncio.create_task(collect(loop))
    await asyncio.wait_for(stream_started.wait(), timeout=2)
    assert steering.steer("Acrescenta o teste de duas conversas.") is True
    release_stream.set()
    events = await asyncio.wait_for(task, timeout=5)

    deltas = [event.payload["text"] for event in events if event.type is RuntimeEventType.MESSAGE_DELTA]
    assert deltas == [prior, f"\n\n{new_paragraph}"]
    assert loop.outcome.answer == prior + f"\n\n{new_paragraph}"


def test_steering_channel_caps_guidance_and_rejects_after_close() -> None:
    steering = SteeringChannel()
    assert [
        steering.steer(f"orientação {index}") for index in range(4)
    ] == [True, True, True, False]
    steering.drain_guidance()
    assert steering.steer("o limite é por run, não por fila") is False
    steering.close()
    assert steering.steer("run terminado") is False


@pytest.mark.asyncio
async def test_abort_ends_the_run_as_cancelled_not_completed() -> None:
    steering = SteeringChannel()

    def factory(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        async def iterator() -> AsyncIterator[AgentSignal]:
            yield token("a trabalhar")
            steering.abort()
            await asyncio.sleep(0)
            yield token(" mais texto")

        return iterator()

    loop = PrimaryLoop(
        run_id="run-abort",
        query="tarefa",
        stream=factory,
        observe=observe_project,
        steering=steering,
        project_path="/tmp/project",
    )
    events = await collect(loop)
    assert loop.outcome.stopped is True
    assert types_of(events)[-1] == "run_cancelled"
    assert "run_completed" not in types_of(events)


# ------------------------------------------------------------ 6. browser refresh
@pytest.mark.asyncio
async def test_a_browser_refresh_replays_exactly_the_missed_events() -> None:
    stream = RunEventStream("run-refresh")
    loop = PrimaryLoop(
        run_id="run-refresh",
        query="tarefa",
        stream=signals(
            token("um"),
            tool_call("read_file", path="a.py"),
            tool_result("read_file", ok=True, files_read=1),
            token(" dois"),
        ),
        observe=observe_project,
        events=stream,
        project_path="/tmp/project",
    )
    events = await collect(loop)

    # The client rendered up to the 4th event and then the tab reloaded.
    rendered = events[:4]
    last_seq = rendered[-1].seq
    replayed = stream.replay(after_seq=last_seq)

    assert [event.seq for event in replayed] == [
        event.seq for event in events[4:]
    ]
    assert not {event.event_id for event in rendered} & {
        event.event_id for event in replayed
    }, "replay duplicated an already rendered event"
    # Rendering history + replay reconstructs the run exactly once.
    assert [event.seq for event in rendered + replayed] == [e.seq for e in events]


@pytest.mark.asyncio
async def test_a_slow_consumer_never_blocks_the_run() -> None:
    """A disconnected browser must not be able to stall the agent."""
    stream = RunEventStream("run-slow", subscriber_queue_size=2)
    loop = PrimaryLoop(
        run_id="run-slow",
        query="tarefa",
        stream=signals(*[token(f"{i} ") for i in range(50)]),
        observe=observe_project,
        events=stream,
        project_path="/tmp/project",
    )
    # Prime the buffer so the subscriber's queue is registered synchronously,
    # then stop reading from it — this is a browser that walked away.
    stream.emit(RuntimeEventType.STATUS_UPDATE, label="prime")
    subscriber = stream.subscribe(after_seq=0)
    await subscriber.__anext__()

    events = await asyncio.wait_for(collect(loop), timeout=5)
    assert loop.outcome.succeeded
    assert len(events) > 50
    await subscriber.aclose()


# --------------------------------------------------------------- 7. telemetry
@pytest.mark.asyncio
async def test_time_to_first_action_and_useful_work_are_measured() -> None:
    def slow_model(turn: PrimaryTurn) -> AsyncIterator[AgentSignal]:
        async def iterator() -> AsyncIterator[AgentSignal]:
            await asyncio.sleep(0.05)  # the provider is slow to produce a token
            yield token("olá")
            yield tool_call("read_file", path="a.py")
            yield tool_result("read_file", ok=True, files_read=2)

        return iterator()

    loop = PrimaryLoop(
        run_id="run-metrics",
        query="lê o ficheiro",
        stream=slow_model,
        observe=observe_project,
        project_path="/tmp/project",
    )
    await collect(loop)
    metrics = loop.outcome.telemetry

    assert metrics["time_to_first_action"] is not None
    assert metrics["time_to_first_useful_work"] is not None
    assert metrics["time_to_first_token"] is not None
    # The deterministic observation runs before the provider replies, so real
    # work is measurable before the first token — this is the whole point of
    # putting OBSERVE ahead of the model call.
    assert metrics["time_to_first_useful_work"] < metrics["time_to_first_token"]
    assert metrics["time_to_first_action"] <= metrics["time_to_first_useful_work"]
    assert metrics["files_read"] == 5  # 3 from the snapshot + 2 from the tool
    assert metrics["tool_calls"] == 1
    assert metrics["total_duration"] is not None


@pytest.mark.asyncio
async def test_telemetry_does_not_invent_useful_work() -> None:
    """A turn that only produced text must not claim it inspected anything."""

    async def observe_nothing(turn: PrimaryTurn) -> Observation:
        return Observation(summary="sem projeto selecionado", files_inspected=0)

    loop = PrimaryLoop(
        run_id="run-talk",
        query="olá",
        stream=signals(token("olá!")),
        observe=observe_nothing,
    )
    await collect(loop)
    metrics = loop.outcome.telemetry

    assert metrics["files_read"] == 0
    assert metrics["time_to_first_useful_work"] is None
    assert metrics["time_to_first_token"] is not None


@pytest.mark.asyncio
async def test_verification_is_skipped_when_nothing_changed() -> None:
    calls: list[VerificationRequest] = []

    def verify(request: VerificationRequest) -> VerificationResult:
        calls.append(request)
        return VerificationResult(
            ran=bool(request.changed_files), ok=True, summary="nada a verificar"
        )

    loop = PrimaryLoop(
        run_id="run-noverify",
        query="lê o ficheiro",
        stream=signals(
            tool_call("read_file", path="a.py"),
            tool_result("read_file", ok=True, files_read=1),
        ),
        observe=observe_project,
        verify=verify,
        project_path="/tmp/project",
    )
    await collect(loop)
    assert len(calls) == 1
    assert calls[0].changed_files == ()
    assert loop.outcome.verification.ran is False


@pytest.mark.asyncio
async def test_a_tool_failure_is_reported_not_swallowed() -> None:
    loop = PrimaryLoop(
        run_id="run-toolfail",
        query="corre o comando",
        stream=signals(
            tool_call("run_shell", command="pytest"),
            AgentSignal(
                AgentSignalKind.TOOL_ERROR,
                tool_name="run_shell",
                text="command not found",
                ok=False,
            ),
            token("não consegui correr o comando"),
        ),
        observe=observe_project,
        project_path="/tmp/project",
    )
    events = await collect(loop)
    assert "tool_failed" in types_of(events)
    assert loop.telemetry.agent_failures == 1
    assert loop.outcome.succeeded  # the run finished honestly, reporting the failure


@pytest.mark.asyncio
async def test_fatal_provider_error_never_becomes_completed() -> None:
    loop = PrimaryLoop(
        run_id="run-fatal-provider",
        query="responde",
        stream=signals(
            AgentSignal(
                AgentSignalKind.ERROR,
                text="provider timeout",
                ok=False,
            ),
        ),
        project_path="/tmp/project",
    )

    events = await collect(loop)

    assert loop.outcome.failed is True
    assert loop.outcome.error == "provider timeout"
    assert "run_failed" in types_of(events)
    assert "run_completed" not in types_of(events)


@pytest.mark.asyncio
async def test_empty_model_response_is_an_explicit_failure() -> None:
    loop = PrimaryLoop(
        run_id="run-empty-provider",
        query="responde",
        stream=signals(),
        project_path="/tmp/project",
    )

    events = await collect(loop)

    assert loop.outcome.failed is True
    assert "sem uma resposta visível" in loop.outcome.error
    assert types_of(events)[-1] == "run_failed"
    assert "run_completed" not in types_of(events)
