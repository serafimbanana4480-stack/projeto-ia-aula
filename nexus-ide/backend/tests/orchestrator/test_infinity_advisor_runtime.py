from __future__ import annotations

import asyncio

from backend.orchestrator.infinity import advisor_engine
from backend.orchestrator.routes.chat_primary import runtime_event_to_stream_events
from backend.runtime.events import RunEventStream, RuntimeEventType


class _ReviewClient:
    def chat_stream(self, _model: str, _messages: list[dict[str, str]], **_kwargs: object):
        async def stream():
            yield (
                '{"notes":[{"severity":"concern",'
                '"note":"A condição de erro ainda não foi coberta."}],'
                '"desired_model":null}'
            )

        return stream()


def test_advisor_reviews_terminal_event_and_emits_renderable_note(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(advisor_engine, "NOTES_DIR", tmp_path)

    async def exercise() -> None:
        events = RunEventStream("run-advisor-test", journal_path=None)
        runtime = advisor_engine.AdvisorRuntime(
            run_id="run-advisor-test",
            session_id="session-advisor-test",
            events=events,
            llm_client=_ReviewClient(),
            immune_turns=0,
        )
        runtime._model_id = "test-advisor-model"
        runtime.start()
        events.emit(
            RuntimeEventType.RUN_COMPLETED,
            verification={"ran": True, "ok": True, "summary": "tests passed"},
        )
        assert await runtime.wait_for_terminal_review(timeout=1.0) is True
        note_event = next(
            event for event in events.history() if event.type is RuntimeEventType.ADVISOR_NOTE
        )
        frames = runtime_event_to_stream_events(note_event)

        assert runtime.reviews_done == 1
        assert len(runtime.notes) == 1
        assert frames[0].type == "progress"
        assert frames[0].agent == "ADVISOR"
        assert frames[0].run_id == note_event.run_id
        assert frames[0].seq == note_event.seq
        assert frames[0].data["severity"] == "concern"
        assert "condição de erro" in frames[0].content

        await runtime.stop()
        await events.aclose()

    asyncio.run(exercise())
