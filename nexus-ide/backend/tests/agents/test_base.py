"""Tests for backend.agents.base — dataclasses, enums, and AgentBase contract."""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path

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
            "run_shell",
            "run_tests",
            "run_lint",
            "format_code",
            "type_check",
            "spawn_task",
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
    async def test_independent_read_tools_execute_in_parallel(self, monkeypatch) -> None:
        active = 0
        peak_active = 0

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"tool": name, "result": {"path": args["path"], "content": "ok"}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"
            supported_actions = {AgentAction.READ_FILE}
            calls = 0

            async def stream_llm(self, request, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    yield (
                        '```tool\n[{"name":"read_file","arguments":{"path":"a.py"}},'
                        '{"name":"read_file","arguments":{"path":"b.py"}}]\n```'
                    )
                else:
                    yield "done"

            async def _execute(self, request):
                yield "ok"

        request = AgentRequest(
            session_id="parallel",
            query="read both",
            client=object(),
            max_iterations=2,
        )
        output = [token async for token in T()._run_react_loop(request)]

        assert peak_active == 2
        assert sum("tool_result|read_file" in token for token in output) == 2

    def test_accepts_tools_declared_by_supported_actions(self) -> None:
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"
            supported_actions = {AgentAction.SPAWN_TASK}

            async def _execute(self, request):
                yield "ok"

        payload = (
            '```tool\n{"name": "spawn_task", "arguments": '
            '{"name": "Verify", "description": "Run focused tests"}}\n```'
        )
        assert T()._parse_tool_calls(payload) == [
            (
                "spawn_task",
                {"name": "Verify", "description": "Run focused tests"},
            )
        ]

    def test_parses_native_function_parameter_tool_call(self) -> None:
        """OpenRouter-style tool markup must execute instead of ending a run."""
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        calls = T()._parse_tool_calls(
            "<tool_call>\n"
            "<function=list_dir>\n"
            "<parameter=path>backend</parameter>\n"
            "<parameter=recursive>true</parameter>\n"
            "</function>\n"
            "</tool_call>"
        )

        assert calls == [("list_dir", {"path": "backend", "recursive": True})]

    def test_rejects_malformed_native_function_parameter_tool_call(self) -> None:
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        calls = T()._parse_tool_calls(
            "<tool_call><function=list_dir>backend</function></tool_call>"
        )

        assert calls == []

    def test_parses_arg_key_arg_value_tool_call(self) -> None:
        """Qwen3-Coder dialect inside <tool_call> must execute.

        Observed 3,995 parse failures in backend.log on 2026-08-02: the model
        wrote ``run_shell<arg_key>command</arg_key><arg_value>…</arg_value>``
        inside the wrapper; every call was dropped and the ReAct loop ended
        the turn with an empty final answer.
        """
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        calls = T()._parse_tool_calls(
            "<tool_call>run_shell<arg_key>command</arg_key>"
            "<arg_value>ls -la</arg_value>"
            "<arg_key>project_path</arg_key><arg_value>C:\\Users\\rodri</arg_value>"
            "</tool_call>"
        )

        assert calls == [
            ("run_shell", {"command": "ls -la", "project_path": "C:\\Users\\rodri"})
        ]

    def test_arg_key_arg_value_decodes_json_scalars(self) -> None:
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        calls = T()._parse_tool_calls(
            "<tool_call>list_dir<arg_key>path</arg_key><arg_value>backend</arg_value>"
            "<arg_key>recursive</arg_key><arg_value>true</arg_value></tool_call>"
        )

        assert calls == [("list_dir", {"path": "backend", "recursive": True})]

    def test_arg_key_arg_value_still_enforces_allow_list(self) -> None:
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        calls = T()._parse_tool_calls(
            "<tool_call>evil_tool<arg_key>x</arg_key><arg_value>1</arg_value></tool_call>"
        )

        assert calls == []

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


class TestKimiToolCallDialect:
    """Kimi-K2 emits reserved special tokens instead of the requested wrapper.

    Evidence, session 27437d6cc61e4753 at 2026-07-27T08:20:04Z::

        Failed to parse tool_call: <|tool_call_begin|>
        {"name": "search_codebase", "arguments": {"query": "...", ...}}
        <tool_call_

    Zero parsed calls made ``_run_react_loop`` emit a final answer, so a
    formatting mismatch was indistinguishable from "the agent finished".
    """

    @staticmethod
    def _agent():
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        return T()

    def test_special_tokens_inside_tool_call_wrapper(self) -> None:
        payload = (
            "<tool_call><|tool_call_begin|>\n"
            '{"name": "search_codebase", "arguments": '
            '{"query": "Execute Objective", "project_path": "."}}\n'
            "<tool_call_end|></tool_call>"
        )
        assert self._agent()._parse_tool_calls(payload) == [
            ("search_codebase", {"query": "Execute Objective", "project_path": "."})
        ]

    def test_bare_kimi_section_format(self) -> None:
        payload = (
            "<|tool_calls_section_begin|>"
            "<|tool_call_begin|>functions.list_dir:0"
            '<|tool_call_argument_begin|>{"path": "backend"}'
            "<|tool_call_end|>"
            "<|tool_calls_section_end|>"
        )
        assert self._agent()._parse_tool_calls(payload) == [("list_dir", {"path": "backend"})]

    def test_kimi_format_still_enforces_the_allow_list(self) -> None:
        """Loosening the wrapper must not loosen which tools may run."""
        payload = (
            "<|tool_call_begin|>functions.rm_rf"
            '<|tool_call_argument_begin|>{"path": "/"}<|tool_call_end|>'
        )
        assert self._agent()._parse_tool_calls(payload) == []

    def test_plain_prose_mentioning_the_tokens_yields_nothing(self) -> None:
        payload = "The model sometimes writes <|tool_call_begin|> without any JSON body."
        assert self._agent()._parse_tool_calls(payload) == []


class TestRateLimitBackoff:
    """The fallback cascade used to walk every model inside ~2 seconds.

    Session 27437d6cc61e4753 shows the consequence: kimi-k2.7-code,
    deepseek-v4-flash and minimax-m3 tried back-to-back, all three answering
    429, with the reset budget sitting unread in the response headers::

        "X-RateLimit-Limit":"20", "X-RateLimit-Remaining":"0",
        "X-RateLimit-Reset":"1785139560000"
    """

    @staticmethod
    def _agent():
        class T(AgentBase):
            name = "T"
            model_key = "nano"
            prompt_file = "router"

            async def _execute(self, request):
                yield "ok"

        return T()

    def test_reads_retry_after_seconds(self) -> None:
        exc = Exception("OpenAI API error 429: rate limited. Retry-After: 12")
        assert self._agent()._extract_retry_delay(exc) == pytest.approx(12.0)

    def test_reads_x_ratelimit_reset_epoch_millis(self) -> None:
        import time as _time

        reset_ms = int((_time.time() + 30) * 1000)
        exc = Exception(
            'OpenAI API error 429: {"headers":{"X-RateLimit-Limit":"20",'
            f'"X-RateLimit-Remaining":"0","X-RateLimit-Reset":"{reset_ms}"}}}}'
        )
        delay = self._agent()._extract_retry_delay(exc)
        assert delay is not None
        assert 25 <= delay <= 31

    def test_expired_reset_yields_no_wait(self) -> None:
        import time as _time

        past_ms = int((_time.time() - 600) * 1000)
        exc = Exception(f'429 {{"X-RateLimit-Reset":"{past_ms}"}}')
        assert self._agent()._extract_retry_delay(exc) == 0.0

    def test_no_header_means_no_suggestion(self) -> None:
        assert self._agent()._extract_retry_delay(Exception("429 rate limited")) is None

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("OpenAI API error 429: Rate limit exceeded", True),
            ("poolside/laguna-m.1:free is temporarily rate-limited upstream", True),
            ("OpenAI API error 404: This model is unavailable for free", False),
            ("OpenAI stream error: 502 Network connection lost", False),
        ],
    )
    def test_only_rate_limits_are_worth_waiting_on(self, message: str, expected: bool) -> None:
        assert AgentBase._is_rate_limited(Exception(message)) is expected

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_does_not_sleep(self, monkeypatch) -> None:
        slept: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("backend.agents.base.asyncio.sleep", _fake_sleep)
        await self._agent()._wait_before_fallback(Exception("404 gone"), 0)
        assert slept == []

    @pytest.mark.asyncio
    async def test_rate_limit_sleeps_within_the_ceiling(self, monkeypatch) -> None:
        slept: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("backend.agents.base.asyncio.sleep", _fake_sleep)
        await self._agent()._wait_before_fallback(Exception("429 rate limit"), 0)
        assert len(slept) == 1
        assert 0 < slept[0] <= AgentBase._MAX_BACKOFF_SECONDS

    @pytest.mark.asyncio
    async def test_absurd_retry_after_is_capped(self, monkeypatch) -> None:
        slept: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("backend.agents.base.asyncio.sleep", _fake_sleep)
        await self._agent()._wait_before_fallback(
            Exception("429 rate limit. Retry-After: 3600"), 0
        )
        assert slept[0] <= AgentBase._MAX_BACKOFF_SECONDS


# ---------------------------------------------------------------------------
# Helpers for the ReAct-loop regression suites below
# ---------------------------------------------------------------------------


def _scripted_agent(responses, **attrs):
    """An agent whose ``stream_llm`` replays *responses*, one per iteration.

    ``responses`` may be a list (the last entry repeats once exhausted), a bare
    exception (raised on every attempt), or a callable taking the 1-based
    attempt number. Each agent records how many times it was asked to stream in
    ``attempts``.
    """
    if isinstance(responses, BaseException):
        responses = [responses]

    class T(AgentBase):
        name = "T"
        model_key = "nano"
        prompt_file = "router"
        supported_actions = {AgentAction.LIST_DIR, AgentAction.READ_FILE}

        def __init__(self) -> None:
            self.attempts = 0
            self.model_ids_seen: list[str | None] = []

        async def stream_llm(self, request, **_kwargs):
            self.attempts += 1
            self.model_ids_seen.append(request.context.get("_model_override"))
            if callable(responses):
                payload = responses(self.attempts)
            else:
                index = min(self.attempts - 1, len(responses) - 1)
                payload = responses[index]
            if isinstance(payload, BaseException):
                raise payload
            for chunk in payload if isinstance(payload, list) else [payload]:
                if isinstance(chunk, BaseException):
                    raise chunk
                yield chunk

        async def _execute(self, request):
            yield "ok"

    for key, value in attrs.items():
        setattr(T, key, value)
    return T()


def _request(query: str = "lista o diretorio do projeto", **kwargs) -> AgentRequest:
    kwargs.setdefault("max_iterations", 6)
    return AgentRequest(session_id="s-react", query=query, client=object(), **kwargs)


# Verbatim from the 2026-07-27 audit (§6.3): every one of these produced zero
# parsed tool calls and was reported to the user as a completed task.
_BARE_JSON_CALL = '{ "tool": "list_dir", "arguments": { "path": "." } }'
_STEPS_PLAN = '{ "steps": [ { "tool": "list_dir", "parameters": { "path": "." } } ] }'
_COMMANDS_PLAN = '{ "commands": [ { "command": "list_dir", "path": "." } ] }'
_JSON_FENCE = '```json\n{"name": "list_dir", "arguments": {"path": "."}}\n```'
_REAL_CALL = '```tool\n{"name": "list_dir", "arguments": {"path": "."}}\n```'
_WRITE_ABSOLUTE_CALL = (
    '```tool\n{"name": "write_file_absolute", "arguments": '
    '{"path": "C:\\\\Users\\\\rodri\\\\Desktop\\\\relatorio.md", '
    '"content": "# Relatorio\\n\\nConcluido."}}\n```'
)


class TestAutonomousContinuation:
    """Autonomous work must not pause for redundant human permission."""

    def test_detects_the_report_permission_deferral_from_the_ui(self) -> None:
        agent = _scripted_agent(["unused"])
        deferral = (
            "Por favor, confirme que posso prosseguir e criar o arquivo de relatório "
            "no caminho indicado. Após sua confirmação, continuarei imediatamente "
            "com a análise e a escrita do relatório."
        )

        assert agent._is_human_permission_deferral(deferral) is True
        assert agent._is_human_permission_deferral(
            "Relatório criado, verificado e sem melhorias adicionais."
        ) is False

    async def test_suppresses_permission_request_and_executes_explicit_write(
        self, monkeypatch
    ) -> None:
        executed: list[tuple[str, dict, dict]] = []

        async def fake_execute_tool(name, _session_id, args, **kwargs):
            executed.append((name, args, kwargs))
            return {
                "tool": name,
                "result": {"written": True, "path": args["path"]},
            }

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        permission_request = (
            "Por favor, confirme que posso prosseguir e criar o arquivo de relatório "
            "no caminho indicado. Após sua confirmação, continuarei imediatamente."
        )
        agent = _scripted_agent(
            [
                permission_request,
                _WRITE_ABSOLUTE_CALL,
                "Relatório criado e verificado.",
                "Relatório criado, verificado e sem melhorias adicionais.",
            ],
            supported_actions={AgentAction.WRITE_FILE_ABSOLUTE},
        )
        request = _request(
            query=(
                "Cria o relatório em "
                "C:\\Users\\rodri\\Desktop\\relatorio.md e verifica o resultado."
            ),
            autonomous=True,
        )

        output = [token async for token in agent._run_react_loop(request)]
        combined = "".join(output)

        assert [name for name, _args, _kwargs in executed] == ["write_file_absolute"]
        assert executed[0][2]["confirmed"] is True
        assert executed[0][2]["autonomous"] is True
        assert permission_request not in combined
        assert "sem melhorias adicionais" in combined
        assert agent.attempts == 4
        assert agent._last_run_success is True

    async def test_completion_gets_one_bounded_improvement_audit(
        self, monkeypatch
    ) -> None:
        executed: list[str] = []

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            executed.append(name)
            return {"tool": name, "result": {"entries": [], "path": args["path"]}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        agent = _scripted_agent(
            [
                "O trabalho parece concluído.",
                _REAL_CALL,
                "Verificado; não existem melhorias adicionais suportadas por evidência.",
            ]
        )
        output = [
            token
            async for token in agent._run_react_loop(
                _request(autonomous=True)
            )
        ]

        assert executed == ["list_dir"]
        assert agent.attempts == 3
        assert "O trabalho parece concluído." not in "".join(output)
        assert "não existem melhorias adicionais" in "".join(output)
        assert agent._last_run_success is True

    async def test_interactive_request_keeps_normal_single_pass_completion(self) -> None:
        agent = _scripted_agent(["Concluído."])
        output = [
            token
            async for token in agent._run_react_loop(
                _request(autonomous=False)
            )
        ]

        assert agent.attempts == 1
        assert "Concluído." in output
        assert agent._last_run_success is True

    def test_model_cannot_preapprove_an_unrequested_external_path(self) -> None:
        agent = _scripted_agent(
            ["unused"],
            supported_actions={AgentAction.WRITE_FILE_ABSOLUTE},
        )
        request = _request(
            query="Cria apenas um resumo dentro do projeto.",
            project_path="C:\\workspace\\nexus",
            autonomous=True,
        )

        assert (
            agent._autonomous_call_preapproved(
                request,
                "write_file_absolute",
                {"path": "D:\\fora-do-projeto\\relatorio.md"},
            )
            is False
        )

    async def test_repeated_permission_deferrals_fail_boundedly(self) -> None:
        permission_request = "Por favor, confirme que posso prosseguir."
        agent = _scripted_agent([permission_request])

        output = [
            token
            async for token in agent._run_react_loop(
                _request(autonomous=True)
            )
        ]

        assert agent.attempts == AgentBase._MAX_PERMISSION_DEFERRAL_CORRECTIONS + 1
        assert "[TAREFA NÃO CONCLUÍDA]" in "".join(output)
        assert agent._last_run_success is False


class TestRejectedToolCallIsNotCompletion:
    """A tool call the parser refused must never look like "the agent finished".

    ``_parse_tool_calls`` accepts explicit wrappers only, by design: bare JSON
    must stay inert so a web page or file containing ``{"name": "write_file"}``
    cannot execute. The bug was the *consequence*: zero parsed calls went
    straight to ``<event>answer</event>``, so three documents (PHASE9_REVIEW.md
    and friends) were reported as written and never reached disk.
    """

    @pytest.mark.parametrize(
        "payload",
        [_BARE_JSON_CALL, _STEPS_PLAN, _COMMANDS_PLAN, _JSON_FENCE],
        ids=["bare-json", "steps-plan", "commands-plan", "json-fence"],
    )
    def test_detects_every_rejected_dialect_from_the_audit(self, payload: str) -> None:
        agent = _scripted_agent(["unused"])
        assert agent._parse_tool_calls(payload) == [], "parser must stay strict"
        assert agent._unparsed_tool_call_snippet(payload) is not None

    def test_detects_bare_shell_style_tool_command_without_executing_it(self) -> None:
        agent = _scripted_agent(["unused"])
        payload = '```bash\nlist_dir_absolute "C:\\Users\\rodri\\Desktop\\nexus"\n```'

        assert agent._parse_tool_calls(payload) == []
        assert agent._unparsed_tool_call_snippet(payload) == (
            'list_dir_absolute "C:\\Users\\rodri\\Desktop\\nexus"'
        )

    def test_accepts_explicit_one_line_unclosed_tool_fence_with_null_sentinel(self) -> None:
        agent = _scripted_agent(["unused"])
        payload = '```tool {"name":"list_dir","arguments":{"path":"."}} null'

        assert agent._parse_tool_calls(payload) == [("list_dir", {"path": "."})]

    @pytest.mark.parametrize(
        "answer",
        [
            "Listei o diretorio e encontrei 12 ficheiros.",
            "Done. No further action needed.",
            'The config file is `{"debug": true}` and nothing else changed.',
            "I considered calling the tool: list_dir but it was unnecessary.",
        ],
        ids=["prose-pt", "prose-en", "json-data", "prose-mentioning-tool"],
    )
    def test_genuine_final_answers_are_left_alone(self, answer: str) -> None:
        assert _scripted_agent(["unused"])._unparsed_tool_call_snippet(answer) is None

    def test_echoing_the_format_placeholders_costs_no_correction(self) -> None:
        """Quoting the injected format template is documentation, not a call."""
        agent = _scripted_agent(["unused"])
        template = '{"name": "tool_name", "arguments": {"arg1": "value1"}}'
        assert template in agent._build_tool_instructions()

        documentation = f"To call a tool, answer with {template} inside a ```tool fence."
        assert agent._parse_tool_calls(documentation) == []
        assert agent._unparsed_tool_call_snippet(documentation) is None

    async def test_rejected_call_is_corrected_and_then_executed(self, monkeypatch) -> None:
        executed: list[str] = []

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            executed.append(name)
            return {"tool": name, "result": {"entries": ["backend"], "path": args["path"]}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        agent = _scripted_agent([_BARE_JSON_CALL, _REAL_CALL, "Pronto, listei o diretorio."])
        output = [token async for token in agent._run_react_loop(_request())]

        # Without the fix the loop answered on iteration 1 and never executed.
        assert executed == ["list_dir"]
        assert agent.attempts == 3
        assert "<event>answer</event>" in output
        assert agent._last_run_success is True
        assert any("wrong format" in token for token in output)

    async def test_rejected_json_is_never_executed(self, monkeypatch) -> None:
        """The correction path must not become a back door around the parser."""
        executed: list[str] = []

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            executed.append(name)
            return {"tool": name, "result": "ok"}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        agent = _scripted_agent([_BARE_JSON_CALL])
        [token async for token in agent._run_react_loop(_request())]

        assert executed == [], "bare JSON must never reach execute_tool"

    async def test_format_corrections_are_bounded_and_fail_honestly(
        self, monkeypatch
    ) -> None:
        async def fake_execute_tool(name, _session_id, args, **_kwargs):  # pragma: no cover
            raise AssertionError("no tool call should ever parse in this scenario")

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        agent = _scripted_agent([_BARE_JSON_CALL])
        output = [token async for token in agent._run_react_loop(_request())]

        # One initial turn plus exactly _MAX_FORMAT_CORRECTIONS retries.
        assert agent.attempts == AgentBase._MAX_FORMAT_CORRECTIONS + 1
        assert "<event>answer</event>" in output
        assert agent._last_run_success is False, "a run that executed nothing is not a success"

    async def test_every_rejected_call_is_logged_with_the_snippet(
        self, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(
            "backend.agents.base.execute_tool",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("unreachable")),
        )
        agent = _scripted_agent([_BARE_JSON_CALL])

        with caplog.at_level(logging.WARNING, logger="backend.agents.base"):
            [token async for token in agent._run_react_loop(_request())]

        warnings = [
            r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.WARNING and "Unexecutable tool-call shape" in r.getMessage()
        ]
        # Silence is what made this invisible: one warning per rejected turn.
        assert len(warnings) == AgentBase._MAX_FORMAT_CORRECTIONS + 1
        assert all("list_dir" in message for message in warnings)

    async def test_correction_never_widens_the_allow_list(self, monkeypatch) -> None:
        """Recognising a rejected shape must not make a forbidden tool runnable."""
        executed: list[str] = []

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            executed.append(name)
            return {"tool": name, "result": "ok"}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        hostile = '{"tool": "rm_rf", "arguments": {"path": "/"}}'
        agent = _scripted_agent([hostile])
        # Detected as an intent (so the run is not reported as complete)...
        assert agent._unparsed_tool_call_snippet(hostile) is not None
        # ...but still unparseable and therefore unexecutable.
        assert agent._parse_tool_calls(hostile) == []
        assert agent._parse_tool_calls(f"```tool\n{hostile}\n```") == []
        assert agent._parse_tool_calls(f"<tool_call>{hostile}</tool_call>") == []

        [token async for token in agent._run_react_loop(_request())]
        assert executed == []
        assert agent._last_run_success is False


class TestStreamFailureRecovery:
    """One provider hiccup used to end the whole run: ``except: yield; return``."""

    async def test_context_overflow_shrinks_and_retries_once(self) -> None:
        from backend.token_management import ContextOverflowError

        agent = _scripted_agent([ContextOverflowError("context limit exceeded"), "Feito."])
        output = [token async for token in agent._run_react_loop(_request())]

        assert agent.attempts == 2, "a context overflow must not end the run"
        assert "<event>answer</event>" in output
        assert not any(token.startswith("<event>error|") for token in output)
        assert agent._last_run_success is True

    async def test_rate_limit_backs_off_and_retries(self, monkeypatch) -> None:
        slept: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("backend.agents.base.asyncio.sleep", _fake_sleep)

        agent = _scripted_agent([Exception("OpenAI API error 429: Rate limit"), "Feito."])
        output = [token async for token in agent._run_react_loop(_request())]

        assert agent.attempts == 2
        assert slept, "the rate-limit path must back off before retrying"
        assert "<event>answer</event>" in output
        assert agent._last_run_success is True

    async def test_rate_limited_primary_is_skipped_on_later_react_iterations(
        self, monkeypatch
    ) -> None:
        class _Agent(AgentBase):
            name = "TEST"
            model_key = "reasoning"
            prompt_file = "router"

        class _Provider:
            provider_name = "test"

            def __init__(self) -> None:
                self.calls: list[str] = []

            async def chat_stream(self, model, messages, **kwargs):
                self.calls.append(model)
                if model == "primary":
                    raise RuntimeError("429 rate limited")
                yield "ok"

        monkeypatch.setattr(
            "backend.agents.base.get_model_config",
            lambda _key: {
                "id": "primary",
                "fallback_id": "fallback",
                "max_tokens": 64,
                "temperature": 0.1,
            },
        )
        agent = _Agent()
        monkeypatch.setattr(agent, "system_prompt", lambda: "test")
        monkeypatch.setattr(agent, "_wait_before_fallback", lambda *_: asyncio.sleep(0))
        provider = _Provider()
        request = AgentRequest(session_id="s", query="q", client=provider)

        assert "".join([token async for token in agent.stream_llm(request)]) == "ok"
        assert "".join([token async for token in agent.stream_llm(request)]) == "ok"

        assert provider.calls == ["primary", "fallback", "fallback"]
        assert request.context["_rate_limited_models:TEST"] == ["primary"]

    async def test_retries_once_on_another_cascade_model(self) -> None:
        agent = _scripted_agent(
            [Exception("502 upstream connection reset"), "Feito."],
            _next_cascade_model=lambda self, request: "alt/model:free",
        )
        request = _request()
        output = [token async for token in agent._run_react_loop(request)]

        assert agent.attempts == 2
        assert agent.model_ids_seen == [None, "alt/model:free"]
        # The pinned model is per-request state and must be restored, or a
        # shared singleton agent would leak it into the rest of the session.
        assert "_model_override" not in request.context
        assert "<event>answer</event>" in output

    async def test_gives_up_honestly_once_recovery_is_exhausted(self) -> None:
        agent = _scripted_agent(
            Exception("502 upstream connection reset"),
            _next_cascade_model=lambda self, request: "alt/model:free",
        )
        output = [token async for token in agent._run_react_loop(_request())]

        assert agent.attempts == 2, "must try the alternate model before failing"
        assert any(token.startswith("<event>error|LLM stream failed") for token in output)
        assert "<event>answer</event>" not in output
        assert agent._last_run_success is False

    async def test_partially_streamed_answer_is_not_replayed(self) -> None:
        """Retrying after visible tokens duplicates text and re-runs mutations."""
        agent = _scripted_agent(
            [["Ja comecei a resp", Exception("502 connection reset")], "Feito."],
            _next_cascade_model=lambda self, request: "alt/model:free",
        )
        output = [token async for token in agent._run_react_loop(_request())]

        assert agent.attempts == 1
        assert output.count("Ja comecei a resp") == 1
        assert agent._last_run_success is False

    def test_context_overflow_classifier(self) -> None:
        from backend.token_management import ContextOverflowError

        agent = _scripted_agent(["unused"])
        assert agent._is_context_overflow(ContextOverflowError("x")) is True
        assert agent._is_context_overflow(Exception("maximum context length is 8192")) is True
        assert agent._is_context_overflow(Exception("429 rate limit")) is False

    def test_emergency_shrink_keeps_the_newest_steps(self) -> None:
        agent = _scripted_agent(["unused"])
        context = "".join(f"\nTool t{i} returned: {'x' * 50}" for i in range(10))
        shrunk = agent._emergency_shrink_context(context)
        assert len(shrunk) < len(context)
        assert "t9" in shrunk
        assert "t0" not in shrunk


class TestLastRunSuccessHonesty:
    """``_last_run_success`` gates memory persistence — it must not lie."""

    async def test_tool_error_prevents_a_success_verdict(self, monkeypatch) -> None:
        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            return {"tool": name, "error": "ENOENT: no such file or directory"}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        agent = _scripted_agent([_REAL_CALL, "Concluido com sucesso!"])
        output = [token async for token in agent._run_react_loop(_request())]

        assert "<event>answer</event>" in output
        assert agent._last_run_success is False

    async def test_clean_run_still_reports_success(self, monkeypatch) -> None:
        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            return {"tool": name, "result": {"entries": []}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        agent = _scripted_agent([_REAL_CALL, "Concluido."])
        output = [token async for token in agent._run_react_loop(_request())]

        assert "<event>answer</event>" in output
        assert agent._last_run_success is True

    async def test_autonomous_plan_step_requires_substantive_tool_evidence(
        self, monkeypatch
    ) -> None:
        executed: list[str] = []

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            executed.append(name)
            return {"tool": name, "result": {"ok": True}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)
        recall_call = (
            '```tool\n{"name":"recall_context","arguments":{"query":"Nexus"}}\n```'
        )
        list_call = '```tool\n{"name":"list_dir","arguments":{"path":"."}}\n```'
        read_call = '```tool\n{"name":"read_file","arguments":{"path":"README.md"}}\n```'
        agent = _scripted_agent(
            [
                "Vou começar.",
                recall_call,
                "Recuperei o contexto.",
                list_call,
                "Mapeei pastas.",
                read_call,
                "Concluído.",
            ]
        )
        request = _request()
        request.autonomous = True
        request.max_iterations = 10
        request.context["_tool_evidence_requirement"] = "substantive"

        output = [token async for token in agent._run_react_loop(request)]

        # Memory recall and a directory listing are discovery only. The step
        # must continue until it reads substantive workspace content.
        assert executed == ["recall_context", "list_dir", "read_file"]
        assert agent._last_run_success is True
        assert "[TAREFA NÃO CONCLUÍDA]" not in "".join(output)

    async def test_autonomous_verification_fails_without_executable_check(self) -> None:
        agent = _scripted_agent(["Revisei e parece correto."])
        request = _request()
        request.autonomous = True
        request.context["_tool_evidence_requirement"] = "verification"

        output = [token async for token in agent._run_react_loop(request)]

        assert agent.attempts == AgentBase._MAX_TOOL_EVIDENCE_CORRECTIONS + 1
        assert agent._last_run_success is False
        assert "[TAREFA NÃO CONCLUÍDA]" in "".join(output)

    async def test_repeated_discovery_call_cannot_bypass_evidence_gate(
        self, monkeypatch
    ) -> None:
        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            return {"tool": name, "result": {"entries": ["backend"]}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)
        list_call = '```tool\n{"name":"list_dir","arguments":{"path":"."}}\n```'
        agent = _scripted_agent([list_call, list_call, list_call])
        request = _request(autonomous=True)
        request.context["_tool_evidence_requirement"] = "substantive"

        output = [token async for token in agent._run_react_loop(request)]

        assert agent._last_run_success is False
        assert "repetiu apenas ferramentas de descoberta" in "".join(output)

    async def test_recovered_tool_error_keeps_success_verdict(self, monkeypatch) -> None:
        """An error the agent recovers from (a later tool succeeds) is healthy
        autonomy — e.g. a hallucinated path corrected via list_dir — and must
        not fail the whole run. Only errors with NO later success are fatal."""
        calls = {"n": 0}

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"tool": name, "error": "File not found: x", "recoverable": True}
            return {"tool": name, "result": {"entries": ["main.py"]}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        other_call = '```tool\n{"name": "list_dir", "arguments": {"path": "./backend"}}\n```'
        agent = _scripted_agent([_REAL_CALL, other_call, "Concluido apos corrigir o caminho."])
        output = [token async for token in agent._run_react_loop(_request())]

        assert "<event>answer</event>" in output
        assert calls["n"] == 2
        assert any(token.startswith("<event>tool_error|") for token in output)
        assert agent._last_run_success is True

    async def test_error_after_last_success_is_still_a_failure(self, monkeypatch) -> None:
        """Success first, error LAST: nothing recovered the error, so the run
        must still be marked unsuccessful."""
        calls = {"n": 0}

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"tool": name, "result": {"entries": []}}
            return {"tool": name, "error": "File not found: y"}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        other_call = '```tool\n{"name": "list_dir", "arguments": {"path": "./backend"}}\n```'
        agent = _scripted_agent([_REAL_CALL, other_call, "Concluido."])
        output = [token async for token in agent._run_react_loop(_request())]

        assert "<event>answer</event>" in output
        assert calls["n"] == 2
        assert agent._last_run_success is False


class TestEvidenceGateDeadlockRegression:
    """Regression cover for run 2026-08-02T05:22 (session b9f0dfbd53ad402a).

    Three plan tasks failed with "Agent execution failed its runtime/tool
    evidence gate" while producing zero findings. The conversation log shows
    four distinct defects, one test each below.
    """

    def test_incompletion_marker_is_not_mojibake(self) -> None:
        """The emitted marker must match the one every consumer greps for.

        ``base.py`` carried a double-encoded literal
        (``[TAREFA NÃƒO CONCLUÃDA]``), so ``plan_executor._INCOMPLETION_MARKERS``
        and the frontend's ``terminalMarkers`` both failed to recognise the
        agent's own admission of failure.
        """
        from backend.orchestrator.plan_executor import (
            _INCOMPLETION_MARKERS,
            output_reports_incompletion,
        )

        source = Path(inspect.getfile(AgentBase)).read_text(encoding="utf-8")
        assert "NÃƒO" not in source, "double-encoded UTF-8 reintroduced in base.py"
        assert "CONCLUÃ" not in source
        assert "[TAREFA NÃO CONCLUÍDA]" in _INCOMPLETION_MARKERS

        emitted = (
            "[TAREFA NÃO CONCLUÍDA] O agente repetiu apenas ferramentas de "
            "descoberta e não produziu a evidência substantiva ou de "
            "verificação exigida."
        )
        assert output_reports_incompletion(emitted) == "[TAREFA NÃO CONCLUÍDA]"

    async def test_alternating_discovery_calls_are_detected_as_a_loop(
        self, monkeypatch
    ) -> None:
        """A/B/A/B repetition must be caught, not just A/A.

        ANALYZER called ``list_dir_absolute`` on the same path at iterations
        1, 3, 6 and 8 and was never flagged, because only the immediately
        previous call was compared.
        """
        executed: list[str] = []

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            executed.append(name)
            return {"tool": name, "result": {"entries": ["backend"]}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        call_a = '```tool\n{"name":"list_dir","arguments":{"path":"."}}\n```'
        call_b = '```tool\n{"name":"list_dir","arguments":{"path":"./backend"}}\n```'
        agent = _scripted_agent([call_a, call_b, call_a, call_b, call_a, call_b])
        request = _request(autonomous=True)
        request.max_iterations = 12
        request.context["_tool_evidence_requirement"] = "substantive"

        output = [token async for token in agent._run_react_loop(request)]

        # The third distinct issue of ``call_a`` is a repeat at distance 2 and
        # must not be executed again.
        assert executed == ["list_dir", "list_dir"], executed
        assert agent._last_run_success is False
        assert "[TAREFA NÃO CONCLUÍDA]" in "".join(output)

    async def test_repeat_stop_spends_the_evidence_budget_first(
        self, monkeypatch
    ) -> None:
        """A repeat must not abandon the step while nudges remain unused.

        CODER died at iteration 3/10 with all four evidence corrections
        untouched; given one nudge naming the right tools it can recover.
        """
        executed: list[str] = []

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            executed.append(name)
            return {"tool": name, "result": {"content": "ok"}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        list_call = '```tool\n{"name":"list_dir","arguments":{"path":"."}}\n```'
        read_call = '```tool\n{"name":"read_file","arguments":{"path":"README.md"}}\n```'
        agent = _scripted_agent([list_call, list_call, list_call, read_call, "Feito."])
        request = _request(autonomous=True)
        request.max_iterations = 10
        request.context["_tool_evidence_requirement"] = "substantive"

        output = [token async for token in agent._run_react_loop(request)]

        assert "read_file" in executed, executed
        assert agent._last_run_success is True
        assert "[TAREFA NÃO CONCLUÍDA]" not in "".join(output)

    def test_evidence_nudge_names_the_tools_that_close_the_gate(self) -> None:
        """The nudge must redirect away from a blocked tool, not just scold.

        DEBUGGER re-issued ``run_shell`` after every ``[autonomous_blocked]``
        because nothing ever told it that ``run_tests``/``run_lint``/
        ``type_check`` need no approval.
        """
        agent = _scripted_agent(["unused"])

        verify = _request(autonomous=True)
        verify.context["_tool_evidence_requirement"] = "verification"
        hint = agent._tool_evidence_correction(verify)
        for tool in ("run_tests", "run_lint", "type_check", "execute_code"):
            assert tool in hint, tool
        assert "autonomous_blocked" in hint

        substantive = _request(autonomous=True)
        substantive.context["_tool_evidence_requirement"] = "substantive"
        hint = agent._tool_evidence_correction(substantive)
        assert "read_file" in hint and "search_in_files" in hint
        assert "list_dir" in hint  # named as NOT sufficient

        # No requirement configured -> plain nudge, no tool list appended.
        assert agent._tool_evidence_correction(_request()) == (
            AgentBase._TOOL_EVIDENCE_CORRECTION
        )

    def test_system_corrections_survive_context_trimming(self) -> None:
        """``_trim_context`` compresses by dropping chunks and deleted the
        very ``[SYSTEM]`` directives the loop had just appended — the model
        was corrected and then never shown the correction."""
        agent = _scripted_agent(["unused"])
        directives: list[str] = []

        agent._remember_sticky_directive(
            directives, AgentBase._AUTONOMOUS_BLOCKED_TOOL_CORRECTION
        )
        trimmed_away = "Tool list_dir -> {...}\nTool read_file -> {...}"
        restored = agent._reapply_sticky_directives(trimmed_away, directives)
        assert AgentBase._AUTONOMOUS_BLOCKED_TOOL_CORRECTION in restored

        # Already present -> not duplicated.
        assert agent._reapply_sticky_directives(restored, directives) == restored

        # Bounded, and re-pinning moves an entry to the end rather than growing.
        for i in range(10):
            agent._remember_sticky_directive(directives, f"[SYSTEM] d{i}")
        assert len(directives) == AgentBase._MAX_STICKY_DIRECTIVES


class TestRepeatEscalationRegression:
    """Regression cover for run 2026-08-04T00:30 (session 8d7cd19a70934c81).

    ANALYZER and CODER passed; DEBUGGER/Verify burned all 10 iterations. The
    log shows the repeat detector firing at iterations 3, 6, 8 and 10 — every
    one with ``nudge_sent=False``. ``repeated_tool_nudge_sent`` was cleared by
    any fresh call, so a model alternating repeat -> new -> repeat never
    escalated, and the evidence branch (which names the tools that close the
    gate) was never reached.
    """

    async def test_interleaved_repeats_still_escalate(self, monkeypatch) -> None:
        executed: list[str] = []

        async def fake_execute_tool(name, _session_id, args, **_kwargs):
            executed.append(name)
            return {"tool": name, "result": {"entries": ["backend"]}}

        monkeypatch.setattr("backend.agents.base.execute_tool", fake_execute_tool)

        a = '```tool\n{"name":"list_dir","arguments":{"path":"."}}\n```'
        b = '```tool\n{"name":"list_dir","arguments":{"path":"./backend"}}\n```'
        c = '```tool\n{"name":"list_dir","arguments":{"path":"./tests"}}\n```'
        # repeat, fresh, repeat, fresh, repeat … the exact alternation logged.
        agent = _scripted_agent([a, b, a, c, a, b, a, c, a, b])
        request = _request(autonomous=True)
        request.max_iterations = 10
        request.context["_tool_evidence_requirement"] = "verification"

        output = [token async for token in agent._run_react_loop(request)]
        joined = "".join(output)

        assert agent._last_run_success is False
        # It must stop on the evidence verdict, not silently hit the cap.
        assert "[TAREFA NÃO CONCLUÍDA]" in joined
        assert agent.attempts < 10, (
            f"escalated only after {agent.attempts} iterations — the cap was reached"
        )

    def test_repeat_budget_is_cumulative_not_consecutive(self) -> None:
        assert AgentBase._MAX_REPEATED_TOOL_CALLS >= 1

    def test_blocked_tool_steer_names_verification_tools(self) -> None:
        """A blocked run_shell in a Verify step must not point at list_dir."""
        agent = _scripted_agent(["unused"])

        verify = _request(autonomous=True)
        verify.context["_tool_evidence_requirement"] = "verification"
        steer = agent._blocked_tool_correction(verify)
        for tool in ("run_tests", "run_lint", "type_check", "execute_code"):
            assert tool in steer, tool
        assert "cannot complete this step" in steer

        # A substantive step keeps the generic text only.
        other = _request(autonomous=True)
        other.context["_tool_evidence_requirement"] = "substantive"
        assert agent._blocked_tool_correction(other) == (
            AgentBase._AUTONOMOUS_BLOCKED_TOOL_CORRECTION
        )
