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
            "analyze_data",
            "generate_report",
            "scaffold_project",
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
            session_id="s1",
            query="q",
            client=ollama_client,
            history=[],
            context={"custom": 1},
        )
        assert req.context["custom"] == 1

    def test_project_path_defaults_empty(self, ollama_client) -> None:
        req = AgentRequest(session_id="s1", query="q", client=ollama_client)
        assert req.project_path == ""

    def test_project_path_can_be_set(self, ollama_client) -> None:
        req = AgentRequest(
            session_id="s1",
            query="q",
            client=ollama_client,
            project_path="/home/user/project",
        )
        assert req.project_path == "/home/user/project"


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
        # The abstract method is now _execute, not run
        assert hasattr(AgentBase, '_execute')

    def test_supported_actions_default_empty(self) -> None:
        class MinimalAgent(AgentBase):
            name = "MIN"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        agent = MinimalAgent()
        assert agent.supported_actions == set()

    def test_resolve_model_id_and_system_prompt(self) -> None:
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        agent = T()
        assert agent.resolve_model_id().startswith("qwen")
        assert "ROUTER" in agent.system_prompt()

    def test_action_tools_mapping_uses_registered_tool_names(self) -> None:
        """Verify _ACTION_TOOLS maps to actual registered tool names, not stale names."""
        from backend.agents.base import AgentBase

        for action, (tool_name, _example) in AgentBase._ACTION_TOOLS.items():
            assert tool_name == action.value or tool_name in {
                "read_file", "write_file", "execute_code", "web_search",
                "fetch_url", "consult_agent", "recall_context",
                "search_codebase", "data_analysis", "report_generation",
            }, f"Action {action.value} maps to unknown tool {tool_name}"

    def test_search_codebase_maps_to_search_codebase_tool(self) -> None:
        """Regression: SEARCH_CODEBASE must map to 'search_codebase', not 'search_in_files'."""
        from backend.agents.base import AgentBase, AgentAction

        tool_name, _ = AgentBase._ACTION_TOOLS[AgentAction.SEARCH_CODEBASE]
        assert tool_name == "search_codebase"

    def test_fetch_url_maps_to_fetch_url_tool(self) -> None:
        """FETCH_URL must map to 'fetch_url', not 'web_search'."""
        from backend.agents.base import AgentBase, AgentAction

        tool_name, _ = AgentBase._ACTION_TOOLS[AgentAction.FETCH_URL]
        assert tool_name == "fetch_url"

    def test_analyze_data_maps_to_data_analysis_tool(self) -> None:
        from backend.agents.base import AgentBase, AgentAction

        tool_name, _ = AgentBase._ACTION_TOOLS[AgentAction.ANALYZE_DATA]
        assert tool_name == "data_analysis"

    def test_generate_report_maps_to_report_generation_tool(self) -> None:
        from backend.agents.base import AgentBase, AgentAction

        tool_name, _ = AgentBase._ACTION_TOOLS[AgentAction.GENERATE_REPORT]
        assert tool_name == "report_generation"

    async def test_stream_llm_yields_all_tokens(self, ollama_client) -> None:
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                async for tok in self.stream_llm(request):
                    yield tok

        agent = T()
        req = AgentRequest(session_id="s1", query="hi", client=ollama_client)
        out = [t async for t in agent.run(req)]
        assert out == ["Hello", ", ", "world", "!"]
        await ollama_client.aclose()
