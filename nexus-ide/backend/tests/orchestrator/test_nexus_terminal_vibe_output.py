from __future__ import annotations

import asyncio

import httpx
from rich.console import Console

from backend.orchestrator.infinity.vibe_director import VibeDirector
from scripts.nexus_terminal import NexusTerminal


def test_terminal_marks_failed_worker_without_printing_raw_error() -> None:
    terminal = object.__new__(NexusTerminal)
    terminal.console = Console(record=True, width=220, color_system=None)

    terminal._print_worker_rows(
        [
            {
                "id": "w-1",
                "name": "reviewer",
                "tier": "fast",
                "state": "streaming",
                "turns": 1,
                "queued": 0,
                "model": "test-model",
                "preview": "Good answer",
                "error": None,
                "settlement": {
                    "outcome": "failed",
                    "error": "RuntimeError: private provider detail",
                    "result": "Good answer",
                },
            }
        ]
    )
    table_output = terminal.console.export_text()
    assert "último turno falhou" in table_output
    assert "private provider detail" not in table_output

    terminal.console = Console(record=True, width=220, color_system=None)

    class FailedDirector:
        def full_output(self, worker_id: str) -> dict[str, object] | None:
            if worker_id != "w-1":
                return None
            return {
                "id": worker_id,
                "name": "reviewer",
                "tier": "fast",
                "state": "idle",
                "turns": 1,
                "history": [],
                "last_result": "Good answer",
                "error": "RuntimeError: private provider detail",
            }

    terminal.director = FailedDirector()
    terminal._print_worker_result("w-1")
    result_output = terminal.console.export_text()
    assert "último turno: falhou" in result_output
    assert "resposta concluída antes da falha" in result_output
    assert "Good answer" in result_output
    assert "private provider detail" not in result_output


def test_terminal_wait_uses_shared_strict_argument_parser() -> None:
    terminal = object.__new__(NexusTerminal)
    terminal.console = Console(record=True, width=180, color_system=None)
    calls: list[tuple[list[str] | None, float]] = []

    class WaitingDirector:
        async def wait(
            self, worker_ids: list[str] | None = None, timeout: float = 30.0
        ) -> list[dict[str, object]]:
            calls.append((worker_ids, timeout))
            return []

    terminal.director = WaitingDirector()
    asyncio.run(terminal._wait_workers("--timeout 2.5 w-1"))
    assert calls == [(["w-1"], 2.5)]

    asyncio.run(terminal._wait_workers("--timeout nan w-1"))
    assert calls == [(["w-1"], 2.5)]
    assert "entre 0.1 e 600" in terminal.console.export_text()


def test_terminal_vibe_worker_marks_chat_sse_error_as_failed() -> None:
    async def run() -> list[dict[str, object]]:
        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'data: {"type":"error","content":"provider detail"}\n'
                    'data: {"type":"done"}\n'
                ),
            )

        terminal = object.__new__(NexusTerminal)
        terminal.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        terminal.console = Console(record=True, width=180, color_system=None)
        terminal.api_url = "http://nexus.test"
        terminal.session_id = "terminal-test"
        terminal.project_path = "."
        terminal.requested_model = "test-model"
        terminal.token = ""
        terminal._last_error = None
        director = VibeDirector(
            session_id="terminal-test",
            runner=terminal._run_worker,
            tier_models={"fast": "test-model"},
        )
        worker = director.spawn(tier="fast", prompt="run task")
        try:
            return await director.wait([str(worker["id"])], timeout=2)
        finally:
            await terminal.client.aclose()

    results = asyncio.run(run())
    assert len(results) == 1
    settlement = results[0]["settlement"]
    assert isinstance(settlement, dict)
    assert settlement["outcome"] == "failed"
    assert "provider detail" not in str(settlement)
    assert results[0]["error"] == "RuntimeError: chat worker failed"


def test_terminal_background_transport_error_is_hidden_and_fails() -> None:
    terminal = object.__new__(NexusTerminal)
    terminal.console = Console(record=True, width=180, color_system=None)
    terminal.api_url = "http://nexus.test"
    terminal.session_id = "terminal-test"
    terminal.project_path = "."
    terminal.requested_model = "test-model"
    terminal.token = ""
    terminal._last_error = None

    class BrokenClient:
        def stream(self, *_args: object, **_kwargs: object) -> None:
            request = httpx.Request("POST", "http://nexus.test/api/chat")
            raise httpx.ConnectError("private transport detail", request=request)

    terminal.client = BrokenClient()

    async def run() -> None:
        try:
            await terminal._chat("worker task", display=False, max_retries=0)
        except RuntimeError as exc:
            assert str(exc) == "chat worker failed"
        else:
            raise AssertionError("background transport error must fail the worker")

    asyncio.run(run())
    assert "private transport detail" not in terminal.console.export_text()
    assert terminal._last_error == "chat worker failed"
