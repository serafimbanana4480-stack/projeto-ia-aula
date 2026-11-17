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


def test_mcp_availability_helper_exists_for_the_default_capability() -> None:
    """MCP is on by default. The turn must be able to ask why it is blocked."""
    from backend.orchestrator.routes.bots import _mcp_block_reason

    reason = _mcp_block_reason()
    assert isinstance(reason, str)


def test_prose_tool_names_counts_and_invented_errors_are_unverified() -> None:
    """The live model named tools, counts and errors that never happened."""
    answer = (
        "recall_context (18 chamadas) não devolveu nada. "
        "Li os ficheiros do módulo. "
        "search_in_files devolveu TypeError 'file_pattern'. "
        "O run_shell mostrou a saída do comando. "
        "store_memory guardou o facto e o web_fetch trouxe a página."
    )
    claims = AgentBase._unsupported_bot_claims(
        answer,
        {"list_skills", "load_skill"},
        tool_events={"list_skills": 2, "load_skill": 1},
    )
    joined = " ".join(claims)
    assert "recall_context" in joined
    assert "18" in joined and "registou 0" in joined
    assert "search_in_files" in joined
    assert "file_pattern" in joined
    assert "run_shell" in joined
    assert "store_memory" in joined
    assert "web_fetch" in joined
    assert "nenhuma ferramenta de leitura correu" in joined


@pytest.mark.asyncio
async def test_a_fabricated_tool_story_is_marked_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Provider:
        provider_name = "openrouter"

        async def chat_stream(self, *, model, messages, **_kwargs):
            yield (
                "recall_context (18 chamadas). "
                "search_in_files deu TypeError 'file_pattern'. "
                "O web_fetch trouxe a página."
            )

    agent = _agent(monkeypatch)
    request = AgentRequest(
        session_id="bot-story",
        query="Confirma o que correu",
        client=_Provider(),
        context={"_isolated_bot_conversation": True, "_model_override": "free-model"},
        max_iterations=4,
    )
    text = "".join([token async for token in agent._run_react_loop(request)])
    assert "[Não verificado]" in text
    assert "recall_context" in text
    assert "search_in_files" in text
    assert request.context["_agent_run_success"] is False


@pytest.mark.asyncio
async def test_repeated_bot_prose_is_capped_and_not_concatenated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentence = "O run_shell não está a respeitar o project_path neste pedido."
    calls = 0

    class _Provider:
        provider_name = "openrouter"

        async def chat_stream(self, *, model, messages, **_kwargs):
            nonlocal calls
            calls += 1
            yield (sentence + " ") * 40

    agent = _agent(monkeypatch)
    request = AgentRequest(
        session_id="bot-repeat",
        query="Lista a pasta e depois corre o shell",
        client=_Provider(),
        context={"_isolated_bot_conversation": True, "_model_override": "free-model"},
        max_iterations=6,
    )
    text = "".join([token async for token in agent._run_react_loop(request)])
    assert calls >= 2
    assert text.count(sentence) <= 2
    assert len(text) < 8_000
    assert "Resposta interrompida" in text
    assert text.count(sentence) < 40


@pytest.mark.asyncio
async def test_multipart_nudge_names_the_real_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    class _Provider:
        provider_name = "openrouter"

        async def chat_stream(self, *, model, messages, **_kwargs):
            prompts.append(str(messages))
            yield "Já tratei a primeira parte em prosa."

    agent = _agent(monkeypatch)
    request = AgentRequest(
        session_id="bot-tools-nudge",
        query="Lê o código e depois corre o shell e também guarda na memória",
        client=_Provider(),
        context={"_isolated_bot_conversation": True, "_model_override": "free-model"},
        max_iterations=4,
    )
    _ = [token async for token in agent._run_react_loop(request)]
    assert len(prompts) >= 2
    nudge = prompts[1]
    assert "read_file" in nudge
    assert "search_in_files" in nudge
    assert "run_shell" in nudge
    assert "store_memory" in nudge
    assert "A prosa não conta" in nudge


@pytest.mark.asyncio
async def test_remember_request_stores_memory_when_the_model_never_calls_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: list[dict] = []

    async def _execute(name, session_id, args, **kwargs):
        stored.append({"name": name, "session_id": session_id, "args": args, "user_id": kwargs.get("user_id")})
        return {"id": "mem-1"}

    monkeypatch.setattr("backend.tools.registry.execute_tool", _execute)

    class _Provider:
        provider_name = "openrouter"

        async def chat_stream(self, *, model, messages, **_kwargs):
            yield "Fica registado, não te esqueças."

    agent = _agent(monkeypatch)
    request = AgentRequest(
        session_id="bot-memory",
        query="Lembra-te que a porta do servidor é 8000",
        user_id="owner-1",
        client=_Provider(),
        context={
            "_isolated_bot_conversation": True,
            "_bot_memory_session_scope": True,
            "_allowed_tools": ("store_memory", "recall_context"),
            "_model_override": "free-model",
        },
        max_iterations=4,
    )
    text = "".join([token async for token in agent._run_react_loop(request)])
    assert stored and stored[0]["name"] == "store_memory"
    assert stored[0]["user_id"] == "owner-1"
    assert "8000" in stored[0]["args"]["content"]
    assert "store_memory" in text


def test_default_bot_workspace_ignores_path_mentions(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = tmp_path / "server"
    routes = server / "backend" / "orchestrator" / "routes"
    routes.mkdir(parents=True)
    outside = tmp_path / "outside-repo"
    outside.mkdir()
    workspace_root = tmp_path / "bot-workspaces"
    workspace = workspace_root / "bot-a"
    workspace.mkdir(parents=True)
    monkeypatch.chdir(server)
    monkeypatch.setenv("NEXUS_BOT_WORKSPACE_ROOT", str(workspace_root))
    message = f"Revê backend/orchestrator/routes. O caminho absoluto é {outside}."
    assert chat._message_names_foreign_directory(message, str(workspace)) is False
    project = tmp_path / "real-project"
    project.mkdir()
    assert chat._message_names_foreign_directory(message, str(project)) is True


def test_a_name_without_at_is_not_a_deferred_mention(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.runtime.group_primary import select_group_bot
    from backend.runtime.triage import RequestClass, TriageDecision

    profiles = {
        "ana": {
            "id": "ana", "name": "Ana", "provider": "openrouter", "model": "free",
            "archived": False, "description": "", "instructions": "", "capabilities": {},
        },
        "pedro": {
            "id": "pedro", "name": "pedro", "provider": "openrouter", "model": "free",
            "archived": False, "description": "", "instructions": "", "capabilities": {},
        },
    }
    monkeypatch.setattr(
        "backend.persistence.bots.get_bot",
        lambda _owner, bot_id: profiles[bot_id],
    )
    selection = select_group_bot(
        "owner",
        {"bot_ids": ["ana", "pedro"]},
        "pede ao pedro para rever o texto",
        TriageDecision(RequestClass.CONVERSATIONAL, "conversa"),
        SimpleNamespace(providers={"openrouter": object()}),
    )
    assert selection.deferred_mentions == ()


def test_consult_agent_is_offered_with_task_tools() -> None:
    from backend.orchestrator.routes.chat_primary import _BOT_CAPABILITY_TOOLS

    assert "consult_agent" in _BOT_CAPABILITY_TOOLS["tasks"]
    assert "store_memory" in _BOT_CAPABILITY_TOOLS["memory"]


def test_a_failed_run_is_not_replayed_but_a_completed_one_is() -> None:
    failed = SimpleNamespace(run_id="run-failed", state=RunState.FAILED)
    completed = SimpleNamespace(run_id="run-done", state=RunState.COMPLETED)
    running = SimpleNamespace(run_id="run-live", state=RunState.RUNNING)
    assert chat._should_replay_idempotent_primary_run(failed) is False
    assert chat._should_replay_idempotent_primary_run(completed) is True
    assert chat._should_replay_idempotent_primary_run(running) is True
