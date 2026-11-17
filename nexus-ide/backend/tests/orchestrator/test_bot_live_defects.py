"""The four defects from the live free-model run.

A scripted provider stands in for the model. Nothing here calls a paid API.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agents.base import AgentBase, AgentRequest
from backend.llm.free_policy import ProviderUnavailableError
from backend.orchestrator.routes import chat
from backend.runtime.run_coordinator import RunState


class _Agent(AgentBase):
    name = "NEXUS"
    model_key = "coder"
    prompt_file = "router"

    async def _execute(self, request):
        async for token in self._run_react_loop(request):
            yield token


def _agent(monkeypatch: pytest.MonkeyPatch) -> _Agent:
    monkeypatch.setattr(
        "backend.agents.base.get_model_config",
        lambda _key: {"id": "configured/model", "max_tokens": 64, "temperature": 0.1},
    )
    agent = _Agent()
    monkeypatch.setattr(agent, "system_prompt", lambda: "sistema")
    return agent


@pytest.mark.asyncio
async def test_a_fabricated_file_claim_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    class _Provider:
        provider_name = "openrouter"

        async def chat_stream(self, *, model, messages, **_kwargs):
            nonlocal calls
            calls += 1
            yield "Li o ficheiro nota.txt e o conteúdo é segredo."

    agent = _agent(monkeypatch)
    request = AgentRequest(
        session_id="bot-claims",
        query="Lê nota.txt",
        client=_Provider(),
        context={"_isolated_bot_conversation": True, "_model_override": "free-model"},
        max_iterations=6,
    )
    output = [token async for token in agent._run_react_loop(request)]
    text = "".join(output)
    assert calls >= 2
    assert "[Não verificado]" in text
    assert "nenhuma ferramenta de leitura correu" in text
    assert request.context["_agent_run_success"] is False


@pytest.mark.asyncio
async def test_a_real_tool_call_satisfies_the_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _agent(monkeypatch)
    claims = agent._unsupported_bot_claims(
        "Li o ficheiro nota.txt.", {"read_file"}
    )
    assert claims == ()


@pytest.mark.asyncio
async def test_a_multi_part_request_is_not_finished_after_one_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    class _Provider:
        provider_name = "openrouter"

        async def chat_stream(self, *, model, messages, **_kwargs):
            prompts.append(str(messages))
            if len(prompts) == 1:
                yield "Já tratei a primeira parte."
                return
            yield "Não consegui escrever o resumo."

    agent = _agent(monkeypatch)
    request = AgentRequest(
        session_id="bot-parts",
        query="Lista a pasta do código e depois escreve o resumo em notas",
        client=_Provider(),
        context={"_isolated_bot_conversation": True, "_model_override": "free-model"},
        max_iterations=6,
    )
    output = [token async for token in agent._run_react_loop(request)]
    assert len(prompts) >= 2
    assert "falta evidência" in prompts[1]
    assert "resumo" in prompts[1]
    assert any("várias partes" in token for token in output)


@pytest.mark.asyncio
async def test_rate_limit_retries_with_retry_after_on_the_bot_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    class _Provider:
        provider_name = "openrouter"

        def __init__(self) -> None:
            self.calls = 0

        async def chat_stream(self, *, model, messages, **_kwargs):
            self.calls += 1
            if self.calls < 3:
                raise ProviderUnavailableError(
                    "429 rate limit", category="rate_limit", retry_after=2
                )
            yield "resposta"

    agent = _agent(monkeypatch)

    async def _sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(agent, "_sleep_retry", _sleep)
    provider = _Provider()
    request = AgentRequest(
        session_id="bot-429",
        query="Olá",
        client=provider,
        context={
            "_isolated_bot_conversation": True,
            "_fast_chat_lane": True,
            "_model_override": "free-model",
        },
        max_iterations=4,
    )
    output = [token async for token in agent._run_react_loop(request)]
    text = "".join(output)
    assert provider.calls == 3
    assert slept == [2.0, 2.0]
    assert "limite do provider, a tentar de novo em 2s" in text
    assert "resposta" in text


@pytest.mark.asyncio
async def test_rate_limit_failure_keeps_category_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Provider:
        provider_name = "openrouter"

        async def chat_stream(self, *, model, messages, **_kwargs):
            raise ProviderUnavailableError(
                "429 rate limit", category="rate_limit", retry_after=4
            )
            yield "nunca"

    agent = _agent(monkeypatch)

    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(agent, "_sleep_retry", _sleep)
    request = AgentRequest(
        session_id="bot-429-fail",
        query="Olá",
        client=_Provider(),
        context={"_fast_chat_lane": True, "_model_override": "free-model"},
        max_iterations=3,
    )
    output = [token async for token in agent._run_react_loop(request)]
    error = next(token for token in output if token.startswith("<event>error|"))
    assert "LLM stream failed" in error
    assert "rate_limit" in error
    assert "retry_after" in error
    parsed = chat._parse_inline_events(error, "NEXUS")
    assert parsed[0].type == "error"
    assert parsed[0].data["error_category"] == "rate_limit"
    assert parsed[0].data["retry_after"] == 4


def test_a_failed_run_is_not_replayed_but_a_completed_one_is() -> None:
    failed = SimpleNamespace(run_id="run-failed", state=RunState.FAILED)
    completed = SimpleNamespace(run_id="run-done", state=RunState.COMPLETED)
    running = SimpleNamespace(run_id="run-live", state=RunState.RUNNING)
    assert chat._should_replay_idempotent_primary_run(failed) is False
    assert chat._should_replay_idempotent_primary_run(completed) is True
    assert chat._should_replay_idempotent_primary_run(running) is True
