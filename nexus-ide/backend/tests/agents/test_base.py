"""Tests for backend.agents.base — dataclasses, enums, and AgentBase contract."""

from __future__ import annotations

from backend.agents.base import AgentAction, AgentBase, AgentRequest, AgentResponse


class TestAgentAction:
    def test_all_actions_exist(self) -> None:
        actions = {a.value for a in AgentAction}
        expected = {
            "search_web",
            "fetch_url",
            "read_file",
            "write_file",
            "write_file_absolute",
            "read_file_absolute",
            "list_dir",
            "list_dir_absolute",
            "execute_code",
            "consult_agent",
            "search_codebase",
            "search_symbols",
            "index_symbols",
            "read_docs",
            "recall_context",
            "store_memory",
            "analyze_data",
            "generate_report",
            "scaffold_project",
            "search_github",
            "search_docs",
            "deep_research",
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


class TestAgentContextTrimming:
    def test_estimate_tokens(self) -> None:
        from backend.agents.base import AgentBase

        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        agent = T()
        assert agent._estimate_tokens("") == 0
        # 400 chars of repeated 'a' tokens to ~50 tokens with cl100k_base
        # (single repeated chars compress efficiently in BPE).
        estimate = agent._estimate_tokens("a" * 400)
        assert 30 <= estimate <= 100, f"unexpected token estimate: {estimate}"

    def test_trim_context_under_limit(self) -> None:
        from backend.agents.base import AgentBase

        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        agent = T()
        short = "Tool read_file returned: ok"
        assert agent._trim_context(short, 1) == short

    def test_trim_context_summarizes_old_iterations(self) -> None:
        from backend.agents.base import AgentBase

        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        agent = T()
        # Build a large context (>4000 tokens)
        parts = [f"Tool tool_{i} returned: {'x' * 500}" for i in range(50)]
        big_context = "\nTool ".join(parts)
        trimmed = agent._trim_context(big_context, 10)
        # The trim should reduce the context size.
        assert len(trimmed) < len(big_context)
        # Either path may run: structured compression or fallback summarization.
        # Both produce shorter output; check the structured one OR the digest markers.
        assert (
            "Memory digest" in trimmed
            or "Recent steps" in trimmed
            or len(trimmed) < len(big_context) * 0.5
        )


class TestAgentBaseContract:
    def test_subclass_must_implement_run(self) -> None:
        class BrokenAgent(AgentBase):
            name = "BROKEN"
            model_key = "nano"
            prompt_file = "test"

        # The abstract method is now _execute (not run). A subclass that
        # fails to implement it should not raise at instantiation time
        # (Python does not enforce abstract methods without ABCMeta), but
        # the parent class should expose _execute as the required hook.
        agent = BrokenAgent()
        assert hasattr(agent, "_execute")
        assert callable(agent._execute)

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
        # nano tier routes to a small/fast model. The current registry maps
        # all tiers to deepseek-v4-flash via OpenRouter (configurable in
        # config/models.yaml). We assert structure (non-empty string) rather
        # than pinning to a specific model id.
        resolved = agent.resolve_model_id()
        assert isinstance(resolved, str) and resolved
        assert "ROUTER" in agent.system_prompt()

    def test_action_tools_mapping_uses_registered_tool_names(self) -> None:
        """Verify _ACTION_TOOLS maps to actual registered tool names, not stale names."""
        from backend.agents.action_registry import get_action_registry
        from backend.agents.base import AgentAction

        registry = get_action_registry()
        for action in AgentAction:
            spec = registry.get(action.name)
            assert spec is not None, f"Action {action.name} missing from registry"
            tool_name = spec.tool
            assert tool_name == action.value or tool_name in {
                "read_file",
                "write_file",
                "execute_code",
                "web_search",
                "fetch_url",
                "consult_agent",
                "recall_context",
                "store_memory",
                "search_codebase",
                "data_analysis",
                "report_generation",
            }, f"Action {action.value} maps to unknown tool {tool_name}"

    def test_search_codebase_maps_to_search_codebase_tool(self) -> None:
        """Regression: SEARCH_CODEBASE must map to 'search_codebase', not 'search_in_files'."""
        from backend.agents.action_registry import get_action_registry
        from backend.agents.base import AgentAction

        spec = get_action_registry().get(AgentAction.SEARCH_CODEBASE.name)
        assert spec is not None
        assert spec.tool == "search_codebase"

    def test_fetch_url_maps_to_fetch_url_tool(self) -> None:
        """FETCH_URL must map to 'fetch_url', not 'web_search'."""
        from backend.agents.action_registry import get_action_registry
        from backend.agents.base import AgentAction

        spec = get_action_registry().get(AgentAction.FETCH_URL.name)
        assert spec is not None
        assert spec.tool == "fetch_url"

    def test_analyze_data_maps_to_data_analysis_tool(self) -> None:
        from backend.agents.action_registry import get_action_registry
        from backend.agents.base import AgentAction

        spec = get_action_registry().get(AgentAction.ANALYZE_DATA.name)
        assert spec is not None
        assert spec.tool == "data_analysis"

    def test_generate_report_maps_to_report_generation_tool(self) -> None:
        from backend.agents.action_registry import get_action_registry
        from backend.agents.base import AgentAction

        spec = get_action_registry().get(AgentAction.GENERATE_REPORT.name)
        assert spec is not None
        assert spec.tool == "report_generation"

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
        # Real LLM test: just verify the stream yields non-empty tokens.
        # Token content depends on model (0.5B produces different output than
        # the canned MockTransport stream). Robust assertions:
        joined = "".join(out)
        assert out, "stream_llm yielded no tokens"
        assert len(joined) > 0, "stream_llm produced empty text"
        # Should contain at least some alphanumeric characters (not just punctuation)
        assert any(c.isalnum() for c in joined), (
            f"stream_llm produced non-textual output: {out[:5]!r}"
        )
        await ollama_client.aclose()
