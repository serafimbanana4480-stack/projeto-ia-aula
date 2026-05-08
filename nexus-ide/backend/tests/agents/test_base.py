"""Tests for backend.agents.base — dataclasses, enums, and AgentBase contract."""
from __future__ import annotations

import pytest

from backend.agents.base import AgentAction, AgentBase, AgentRequest, AgentResponse


class TestAgentAction:
    def test_all_actions_exist(self) -> None:
        actions = {a.value for a in AgentAction}
        expected = {
            "search_web",
            "fetch_url",
            "read_file",
            "write_file",
            "execute_code",
            "consult_agent",
            "search_codebase",
            "read_docs",
            "recall_context",
        }
        assert actions == expected

    def test_str_behavior(self) -> None:
        # AgentAction inherits from str + Enum, direct comparison works
        assert AgentAction.READ_FILE == "read_file"
        assert AgentAction.WRITE_FILE == "write_file"


class TestAgentRequest:
    def test_basic_instantiation(self, ollama_client) -> None:
        req = AgentRequest(session_id="abc-123", query="hello", client=ollama_client)
        assert req.session_id == "abc-123"
        assert req.query == "hello"
        assert req.history == []
        assert req.context == {}

    def test_history_defaults_to_empty_but_can_be_set(self, ollama_client) -> None:
        req = AgentRequest(
            session_id="s1", query="q", client=ollama_client,
            history=[],
            context={"custom": 1},
        )
        assert req.context["custom"] == 1


class TestAgentResponse:
    def test_basic_instantiation(self) -> None:
        resp = AgentResponse(
            agent="ROUTER",
            model="qwen2.5:0.5b",
            content="test",
            tokens_out=42,
        )
        assert resp.agent == "ROUTER"
        assert resp.tokens_out == 42
        assert resp.metrics == {}


class TestAgentBaseContract:
    def test_subclass_must_implement_run(self) -> None:
        class BrokenAgent(AgentBase):
            name = "BROKEN"
            model_key = "nano"
            prompt_file = "test"

        with pytest.raises(TypeError):
            BrokenAgent()  # type: ignore[abstract]

    def test_supported_actions_default_empty(self) -> None:
        class MinimalAgent(AgentBase):
            name = "MIN"
            model_key = "nano"
            prompt_file = "router"

            async def run(self, request):
                yield "ok"

        agent = MinimalAgent()
        assert agent.supported_actions == set()

    def test_resolve_model_id_and_system_prompt(self) -> None:
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def run(self, request):
                yield "ok"

        agent = T()
        assert agent.resolve_model_id().startswith("qwen")
        assert "ROUTER" in agent.system_prompt()

    async def test_stream_llm_yields_all_tokens(self, ollama_client) -> None:
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def run(self, request):
                async for tok in self.stream_llm(request):
                    yield tok

        agent = T()
        req = AgentRequest(session_id="s1", query="hi", client=ollama_client)
        out = [t async for t in agent.run(req)]
        assert out == ["Hello", ", ", "world", "!"]
        await ollama_client.aclose()
