"""Regression tests for the confirmed LLM provider-layer defects.

Every test in this file reproduces one defect that was confirmed against a
local fake provider server, and asserts the fixed behaviour.  The fake server
is a real HTTP server on ``127.0.0.1`` (see ``fake_provider_server``), so no
network access is needed and the production httpx code path is exercised.

The defects covered here:

===  =========================================================================
D1   a simulated provider must never satisfy a real request
D2   Anthropic input tokens must not be reset to zero
D3   Anthropic/Gemini/Kimi HTTP errors must be classified
D4   the circuit breaker must open on a terminal status
D5   Anthropic/Gemini/Kimi must support native tool calling
D6   OpenRouter must report usage
D7   a billed but failed stream must be recorded
D8   the response cache must be scoped per session
D9   OpenRouter's cooldown must be armed from the response header
D10  placeholder API keys must not be used
D11  ``has_any_real_provider`` must count Anthropic
D12  every provider must expose ``last_finish_reason``
D13  an SSE frame without a space after ``data:`` must be parsed
D14  an empty completion must not be a success
D15  ``Retry-After`` must be honoured
D16  an unknown model id must raise instead of substituting
D17  an isolated backend test must not inherit remote fallback credentials
===  =========================================================================
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import backend.llm.openai_provider as openai_provider_module
from backend.llm.anthropic_provider import AnthropicProvider
from backend.llm.dev_provider import DevProvider
from backend.llm.factory import (
    MockProvider,
    ResilientLLMProvider,
    _build_fallback_chain,
    ensure_cost_governed_provider,
)
from backend.llm.free_policy import ProviderUnavailableError
from backend.llm.gemini_provider import GeminiProvider
from backend.llm.kimi_provider import KimiProvider
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.llm.openai_provider import OpenAIProvider, ProviderHTTPStatusError
from backend.llm.opencode_go_provider import OpenCodeGoProvider
from backend.llm.openrouter_provider import OpenRouterProvider
from backend.llm.response_cache import get_response_cache, reset_response_cache
from backend.llm.tool_calls import TOOL_CALL_CLOSE, TOOL_CALL_OPEN
from backend.runtime.reasoning import REASONING_SINK_OPTION, reasoning_sink
from backend.tests.llm.fake_provider_server import (
    FakeLLMServer,
    Response,
    anthropic_sse,
    gemini_sse,
    openai_sse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_server() -> Any:
    """A local fake provider server, torn down after the test."""
    with FakeLLMServer() as server:
        yield server


def _agent_tool_calls(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse *text* with the *real* agent tool-call parser.

    The provider adapters must fold their native tool calls into the wrapper
    the ReAct loop understands, so the strongest possible assertion is that
    the agent itself finds the call.
    """
    from backend.agents.base import AgentBase

    class _Probe(AgentBase):
        name = "probe"
        model_key = "nano"
        prompt_file = "router"

        async def _execute(self, request: Any):  # pragma: no cover - never called
            yield "ok"

    return _Probe()._parse_tool_calls(text)


def _stub_settings(**api_keys: str) -> SimpleNamespace:
    """A settings stub with only the API keys the fallback chain reads."""
    defaults = {
        "openai_api_key": "",
        "kimi_api_key": "",
        "deepseek_api_key": "",
        "groq_api_key": "",
        "anthropic_api_key": "",
        "gemini_api_key": "",
        "openrouter_api_key": "",
        "kilo_api_key": "",
        "opencode_go_api_key": "",
        "lmstudio_api_key": "",
        "ollama_host": "",
        "ollama_dashboard_host": "",
        "nexus_enable_ollama": False,
    }
    defaults.update(api_keys)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# D1 — a simulated provider must never satisfy a real request
# ---------------------------------------------------------------------------


class _SpyDevProvider(DevProvider):
    """DevProvider that records whether it was dispatched at all."""

    calls = 0

    async def chat_complete(self, model, messages, **kwargs):  # type: ignore[override]
        type(self).calls += 1
        return await super().chat_complete(model, messages, **kwargs)

    async def chat_stream(self, model, messages, **kwargs):  # type: ignore[override]
        type(self).calls += 1
        async for token in super().chat_stream(model, messages, **kwargs):
            yield token


class _DeadProvider:
    """A real-looking provider that is down."""

    async def chat_complete(self, model, messages, **kwargs):  # type: ignore[override]
        raise RuntimeError("connection refused")

    async def chat_stream(self, model, messages, **kwargs):  # type: ignore[override]
        raise RuntimeError("connection refused")
        yield ""  # pragma: no cover - makes this an async generator


async def test_simulated_provider_never_satisfies_a_real_request() -> None:
    """D1: a dead primary must not fall through to a simulated answer.

    The DevProvider's canned reply used to be delivered as the agent's answer
    — with no simulation marker — and the run was persisted as completed.
    """
    _SpyDevProvider.calls = 0
    client = ResilientLLMProvider(_DeadProvider(), [_SpyDevProvider()])

    with pytest.raises(ProviderUnavailableError) as excinfo:
        await client.chat_complete("model", [{"role": "user", "content": "ola"}])

    assert excinfo.value.category == "simulation"
    # The simulation was never even dispatched.
    assert _SpyDevProvider.calls == 0


async def test_simulated_provider_never_streams_a_canned_answer() -> None:
    """D1 (streaming): the canned tokens must never reach the user."""
    _SpyDevProvider.calls = 0
    client = ResilientLLMProvider(_DeadProvider(), [_SpyDevProvider()])

    with pytest.raises(ProviderUnavailableError):
        async for _ in client.chat_stream("model", [{"role": "user", "content": "ola"}]):
            pass

    assert _SpyDevProvider.calls == 0


# ---------------------------------------------------------------------------
# D2 — Anthropic input tokens must not be reset to zero
# ---------------------------------------------------------------------------


async def test_anthropic_input_tokens_are_not_reset_to_zero(fake_server: Any) -> None:
    """D2: ``message_delta`` must merge, not overwrite, the usage.

    Anthropic reports ``input_tokens`` in ``message_start`` and
    ``output_tokens`` in ``message_delta``.  Overwriting with the missing
    field's default of 0 meant the input was never billed and the session
    panel showed ``ENTRADA 0``.
    """
    fake_server.sse(
        "POST",
        "/v1/messages",
        anthropic_sse(
            [
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_1",
                        "role": "assistant",
                        "usage": {"input_tokens": 25, "output_tokens": 1},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "ola"},
                },
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 10},
                },
            ]
        ),
    )

    provider = AnthropicProvider(base_url=fake_server.base_url, api_key="k")
    try:
        tokens = [
            token
            async for token in provider.chat_stream(
                "claude-haiku", [{"role": "user", "content": "ola"}]
            )
        ]
    finally:
        await provider.aclose()

    assert tokens == ["ola"]
    assert provider.last_usage["input_tokens"] == 25
    assert provider.last_usage["output_tokens"] == 10
    assert provider.last_usage["total_tokens"] == 35


# ---------------------------------------------------------------------------
# D3 — HTTP errors must be classified
# ---------------------------------------------------------------------------


async def test_anthropic_http_error_is_classified(fake_server: Any) -> None:
    """D3: an Anthropic HTTP error must carry its status code."""
    fake_server.respond("POST", "/v1/messages", status=401, text="invalid api key")

    provider = AnthropicProvider(base_url=fake_server.base_url, api_key="k")
    try:
        with pytest.raises(ProviderHTTPStatusError) as excinfo:
            await provider.chat_complete("claude-haiku", [{"role": "user", "content": "x"}])
    finally:
        await provider.aclose()

    assert excinfo.value.status_code == 401
    assert "401" in str(excinfo.value)


async def test_gemini_http_error_is_classified(fake_server: Any) -> None:
    """D3: a Gemini HTTP error must carry its status code."""
    fake_server.respond(
        "POST",
        "/v1beta/models/gemini-2.5-flash:generateContent",
        status=500,
        text="boom",
    )

    provider = GeminiProvider(
        base_url=f"{fake_server.base_url}/v1beta", api_key="k"
    )
    try:
        with pytest.raises(ProviderHTTPStatusError) as excinfo:
            await provider.chat_complete(
                "gemini-2.5-flash", [{"role": "user", "content": "x"}]
            )
    finally:
        await provider.aclose()

    assert excinfo.value.status_code == 500


async def test_kimi_http_error_is_classified(fake_server: Any) -> None:
    """D3: a Kimi HTTP error must carry its status code."""
    fake_server.respond("POST", "/v1/chat/completions", status=429, text="slow down")

    provider = KimiProvider(base_url=f"{fake_server.base_url}/v1", api_key="k")
    try:
        with pytest.raises(ProviderHTTPStatusError) as excinfo:
            await provider.chat_complete("kimi-k2", [{"role": "user", "content": "x"}])
    finally:
        await provider.aclose()

    assert excinfo.value.status_code == 429


# ---------------------------------------------------------------------------
# D4 — the circuit breaker must open on a terminal status
# ---------------------------------------------------------------------------


async def test_circuit_breaker_opens_on_a_terminal_status() -> None:
    """D4: a 401 must open the breaker instead of being re-dispatched.

    The breaker used to skip every failure whose typed category was
    ``provider_unavailable``, so a permanently broken provider was asked
    again on every single request.
    """
    from backend.llm.circuit_breaker import get_breaker, reset_breaker

    provider_name = "defect-terminal-status-provider"
    reset_breaker(provider_name)

    class _Unauthorized:
        async def chat_complete(self, model, messages, **kwargs):  # type: ignore[override]
            raise ProviderHTTPStatusError(401, "invalid api key")

    manager = MultiLLMManager(free_only=False)
    manager.register_provider(provider_name, _Unauthorized())

    with pytest.raises(ProviderUnavailableError) as excinfo:
        await manager.chat_complete("model", [{"role": "user", "content": "x"}])

    assert excinfo.value.category == "auth"
    breaker = get_breaker(provider_name)
    snapshot = breaker.snapshot()
    assert snapshot["state"] == "open"
    # The typed error tells the caller when it may try again.
    assert excinfo.value.retry_after is not None
    assert excinfo.value.retry_after > 0
    reset_breaker(provider_name)


# ---------------------------------------------------------------------------
# D5 — native tool calling
# ---------------------------------------------------------------------------


async def test_anthropic_tool_calls_are_folded_into_the_wrapper(fake_server: Any) -> None:
    """D5: Anthropic ``tool_use`` blocks must reach the agent parser."""
    fake_server.sse(
        "POST",
        "/v1/messages",
        anthropic_sse(
            [
                {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "list_dir",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"path": "."}',
                    },
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 4},
                },
            ]
        ),
    )

    provider = AnthropicProvider(base_url=fake_server.base_url, api_key="k")
    try:
        text = "".join(
            [
                token
                async for token in provider.chat_stream(
                    "claude-haiku",
                    [{"role": "user", "content": "lista"}],
                    options={
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "list_dir",
                                    "description": "list files",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {"path": {"type": "string"}},
                                    },
                                },
                            }
                        ],
                        "tool_choice": "auto",
                    },
                )
            ]
        )
    finally:
        await provider.aclose()

    assert TOOL_CALL_OPEN in text
    assert TOOL_CALL_CLOSE in text
    assert _agent_tool_calls(text) == [("list_dir", {"path": "."})]
    # The tool schema reached the provider in Anthropic's own dialect.
    body = fake_server.last_request().json()
    assert body["tools"][0]["name"] == "list_dir"
    assert "input_schema" in body["tools"][0]
    assert body["tool_choice"] == {"type": "auto"}


async def test_gemini_function_call_is_folded_into_the_wrapper(fake_server: Any) -> None:
    """D5: Gemini ``functionCall`` parts must not be dropped."""
    fake_server.sse(
        "POST",
        "/v1beta/models/gemini-2.5-flash:streamGenerateContent",
        gemini_sse(
            [
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "list_dir",
                                            "args": {"path": "."},
                                        }
                                    }
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ]
                }
            ]
        ),
    )

    provider = GeminiProvider(base_url=f"{fake_server.base_url}/v1beta", api_key="k")
    try:
        text = "".join(
            [
                token
                async for token in provider.chat_stream(
                    "gemini-2.5-flash",
                    [{"role": "user", "content": "lista"}],
                    options={
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "list_dir",
                                    "description": "list files",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {"path": {"type": "string"}},
                                    },
                                },
                            }
                        ]
                    },
                )
            ]
        )
    finally:
        await provider.aclose()

    assert _agent_tool_calls(text) == [("list_dir", {"path": "."})]
    body = fake_server.last_request().json()
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "list_dir"


async def test_kimi_tool_calls_are_folded_into_the_wrapper(fake_server: Any) -> None:
    """D5: Kimi's ``delta.tool_calls`` must reach the agent parser."""
    fake_server.sse(
        "POST",
        "/v1/chat/completions",
        openai_sse(
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "list_dir",
                                            "arguments": '{"path": "."}',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ]
        ),
    )

    provider = KimiProvider(base_url=f"{fake_server.base_url}/v1", api_key="k")
    try:
        text = "".join(
            [
                token
                async for token in provider.chat_stream(
                    "kimi-k2",
                    [{"role": "user", "content": "lista"}],
                    options={
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "list_dir",
                                    "description": "list files",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {"path": {"type": "string"}},
                                    },
                                },
                            }
                        ]
                    },
                )
            ]
        )
    finally:
        await provider.aclose()

    assert _agent_tool_calls(text) == [("list_dir", {"path": "."})]
    body = fake_server.last_request().json()
    assert body["tools"][0]["function"]["name"] == "list_dir"


async def test_kimi_reasoning_reaches_the_sink(fake_server: Any) -> None:
    """D5: Kimi had no reasoning sink, so the panel never showed its thinking."""
    fake_server.sse(
        "POST",
        "/v1/chat/completions",
        openai_sse(
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "reasoning_content": "let me think about it",
                                "content": "",
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {"content": "final answer"}}]},
            ]
        ),
    )

    collected: list[str] = []
    provider = KimiProvider(base_url=f"{fake_server.base_url}/v1", api_key="k")
    try:
        text = "".join(
            [
                token
                async for token in provider.chat_stream(
                    "kimi-k2",
                    [{"role": "user", "content": "pergunta"}],
                    options={REASONING_SINK_OPTION: reasoning_sink(collected)},
                )
            ]
        )
    finally:
        await provider.aclose()

    assert "let me think about it" in "".join(collected)
    # The private transcript must never become the answer.
    assert "let me think about it" not in text
    assert text == "final answer"


# ---------------------------------------------------------------------------
# D6 — OpenRouter usage
# ---------------------------------------------------------------------------


async def test_openrouter_exposes_last_usage(fake_server: Any) -> None:
    """D6: the wrapper hid the usage, so the budget was an estimate."""
    fake_server.respond(
        "POST",
        "/v1/chat/completions",
        json_body={
            "choices": [{"message": {"content": "olá"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        },
    )

    provider = OpenRouterProvider(base_url=fake_server.base_url, api_key="k")
    provider._min_request_interval = 0.0
    try:
        answer = await provider.chat_complete(
            "openai/gpt-4o", [{"role": "user", "content": "ola"}]
        )
    finally:
        await provider.aclose()

    assert answer == "olá"
    assert provider.last_usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    # The manager must see the real numbers, not a character-count estimate.
    from backend.llm.multi_llm_manager import _extract_provider_usage

    assert _extract_provider_usage(provider)["input_tokens"] == 11


async def test_openrouter_forwards_bounded_reasoning_options(fake_server: Any) -> None:
    """Explicit reasoning controls must reach the OpenRouter wire request."""
    fake_server.respond(
        "POST",
        "/v1/chat/completions",
        json_body={
            "choices": [{"message": {"content": "olá"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        },
    )
    provider = OpenRouterProvider(base_url=fake_server.base_url, api_key="k")
    provider._min_request_interval = 0.0
    try:
        answer = await provider.chat_complete(
            "openai/gpt-4o",
            [{"role": "user", "content": "ola"}],
            options={"reasoning": {"effort": "none"}},
        )
        assert answer == "olá"
        assert fake_server.last_request().json()["reasoning"] == {"effort": "none"}

        fake_server.sse(
            "POST",
            "/v1/chat/completions",
            openai_sse(
                [
                    {"choices": [{"delta": {"content": "resposta em streaming"}}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                    {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 3}},
                ]
            ),
        )
        stream = "".join(
            [
                token
                async for token in provider.chat_stream(
                    "openai/gpt-4o",
                    [{"role": "user", "content": "ola"}],
                    options={"think": True, "max_tokens": 256},
                )
            ]
        )
        assert stream == "resposta em streaming"
        request = fake_server.last_request().json()
        assert request["reasoning"] == {"effort": "low"}
        assert "think" not in request
    finally:
        await provider.aclose()


# ---------------------------------------------------------------------------
# D7 — a billed but failed stream must be recorded
# ---------------------------------------------------------------------------


async def test_a_failed_but_billed_stream_is_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """D7: tokens the provider already billed must reach the budget.

    The usage recording used to run only *after* the stream completed, so a
    stream that died half-way was invisible to the budget.
    """
    from backend.llm import multi_llm_manager as mlm_module
    from backend.llm.cost_governor import get_cost_governor, reset_cost_governor

    monkeypatch.setattr(mlm_module, "_compute_cost", lambda *a, **k: 0.25)
    reset_cost_governor()
    governor = get_cost_governor(tmp_path / "nexus.db")

    class _DiesHalfWay:
        @property
        def last_usage(self) -> dict[str, int]:
            return {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}

        async def chat_stream(self, model, messages, **kwargs):  # type: ignore[override]
            yield "partial answer"
            raise RuntimeError("connection dropped")

    manager = MultiLLMManager(free_only=False)
    manager.register_provider("defect-billed-failure", _DiesHalfWay())

    with pytest.raises(RuntimeError, match="connection dropped"):
        async for _ in manager.chat_stream(
            "model", [{"role": "user", "content": "x"}], run_id="run-billed"
        ):
            pass

    assert governor.today_spend() == pytest.approx(0.25)
    assert governor.run_spend("run-billed") == pytest.approx(0.25)
    reset_cost_governor()


async def test_selected_raw_provider_keeps_budget_governance_and_run_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A directly selected provider still goes through budget accounting."""
    import backend.llm.cost_governor as cost_governor
    import backend.llm.multi_llm_manager as mlm_module
    from backend.runtime.run_context import reset_current_run_id, set_current_run_id

    class _Governor:
        daily_budget_usd = 0.0

        def __init__(self) -> None:
            self.checked: list[str | None] = []
            self.recorded: list[dict[str, Any]] = []

        def check(self, *, run_id: str | None = None) -> None:
            self.checked.append(run_id)

        def record(self, **fields: Any) -> None:
            self.recorded.append(fields)

        def today_spend(self) -> float:
            return 0.0

    class _Provider:
        provider_name = "openai"
        last_model = "gpt-4o-mini"
        last_usage = {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16}

        async def chat_stream(self, _model: str, _messages: list[dict[str, str]], **_kwargs: Any):
            yield "ok"

    governor = _Governor()
    monkeypatch.setattr(cost_governor, "get_cost_governor", lambda: governor)
    monkeypatch.setattr(mlm_module, "_compute_cost", lambda **_kwargs: 0.42)
    provider = _Provider()
    client = ensure_cost_governed_provider(provider, free_only=False)
    token = set_current_run_id("run-selected-provider")
    try:
        result = [
            token
            async for token in client.chat_stream(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
            )
        ]
    finally:
        reset_current_run_id(token)

    assert result == ["ok"]
    assert governor.checked == ["run-selected-provider"]
    assert len(governor.recorded) == 1
    assert governor.recorded[0]["run_id"] == "run-selected-provider"
    assert governor.recorded[0]["cost_usd"] == 0.42


# ---------------------------------------------------------------------------
# D8 — the response cache must be scoped per session
# ---------------------------------------------------------------------------


async def test_response_cache_is_scoped_per_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D8: one session must never be served another session's answer."""
    monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "300")
    reset_response_cache()

    class _Counting:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_complete(self, model, messages, **kwargs):  # type: ignore[override]
            self.calls += 1
            return f"answer-{self.calls}"

    provider = _Counting()
    manager = MultiLLMManager(free_only=False)
    manager.register_provider("defect-cache-scope", provider)

    messages = [{"role": "user", "content": "mesma pergunta"}]
    first = await manager.chat_complete("m", messages, run_id="session-a")
    other = await manager.chat_complete("m", messages, run_id="session-b")
    again = await manager.chat_complete("m", messages, run_id="session-a")

    assert first == "answer-1"
    # A different session must not be served session A's answer.
    assert other == "answer-2"
    # The same session is still served from the cache.
    assert again == "answer-1"
    assert provider.calls == 2

    stats = get_response_cache().get_stats()
    assert stats["llm_cache_hits"] == 1
    reset_response_cache()


async def test_response_cache_is_disabled_without_a_session_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D8: without an owner there is no safe cache entry."""
    monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "300")
    reset_response_cache()

    class _Counting:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_complete(self, model, messages, **kwargs):  # type: ignore[override]
            self.calls += 1
            return f"answer-{self.calls}"

    provider = _Counting()
    manager = MultiLLMManager(free_only=False)
    manager.register_provider("defect-cache-unscoped", provider)

    messages = [{"role": "user", "content": "sem dono"}]
    await manager.chat_complete("m", messages)
    await manager.chat_complete("m", messages)

    assert provider.calls == 2
    assert get_response_cache().get_stats()["llm_cache_hits"] == 0
    reset_response_cache()


# ---------------------------------------------------------------------------
# D9 — OpenRouter cooldown from the response header
# ---------------------------------------------------------------------------


async def test_openrouter_cooldown_is_armed_from_the_response_header(
    fake_server: Any,
) -> None:
    """D9: ``X-RateLimit-Reset`` is a response *header*, not body text."""
    import backend.llm.openrouter_provider as openrouter_module

    reset_at_ms = int((time.time() + 60) * 1000)
    fake_server.respond(
        "POST",
        "/v1/chat/completions",
        status=429,
        text="rate limited",
        headers={"X-RateLimit-Reset": str(reset_at_ms)},
    )

    openrouter_module._quota_cooldown_until = 0.0
    openrouter_module._quota_next_request_at = 0.0
    openrouter_module._process_quota_lock()

    provider = OpenRouterProvider(base_url=fake_server.base_url, api_key="k")
    provider._min_request_interval = 0.0
    try:
        with pytest.raises(ProviderHTTPStatusError):
            await provider.chat_complete(
                "openai/gpt-4o", [{"role": "user", "content": "ola"}]
            )
    finally:
        await provider.aclose()

    assert openrouter_module._quota_cooldown_until > 0
    assert provider.quota_available is False
    openrouter_module._quota_cooldown_until = 0.0


# ---------------------------------------------------------------------------
# D10/D11 — the fallback chain and placeholder keys
# ---------------------------------------------------------------------------


def test_placeholder_api_keys_are_not_used() -> None:
    """D10: a template key must not be sent to the provider."""
    settings = _stub_settings(openai_api_key="your-openai-api-key-here")

    fallbacks = _build_fallback_chain(
        settings, {"free_only": False}, primary_provider="openai"
    )

    assert not any(
        isinstance(fallback, OpenAIProvider) for fallback in fallbacks
    ), "a placeholder key must not create a provider that burns a 401"


def test_has_any_real_provider_counts_anthropic() -> None:
    """D11: configuring only Anthropic is a real provider."""
    settings = _stub_settings(anthropic_api_key="sk-ant-real-key")

    fallbacks = _build_fallback_chain(
        settings, {"free_only": False}, primary_provider="openai"
    )

    assert any(isinstance(fallback, AnthropicProvider) for fallback in fallbacks)
    assert not any(isinstance(fallback, DevProvider) for fallback in fallbacks)


@pytest.mark.parametrize("free_only", [False, True])
def test_test_guard_disables_remote_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    free_only: bool,
) -> None:
    """A real backend subprocess must not dispatch inherited cloud keys."""
    monkeypatch.setenv("NEXUS_TEST_DISABLE_REMOTE_FALLBACKS", "true")
    settings = _stub_settings(
        openai_api_key="sk-test-openai-key",
        anthropic_api_key="sk-ant-test-key",
        openrouter_api_key="sk-or-test-key",
    )

    fallbacks = _build_fallback_chain(
        settings,
        {"free_only": free_only},
        primary_provider="openai",
    )

    assert len(fallbacks) == 1
    assert isinstance(fallbacks[0], MockProvider)


# ---------------------------------------------------------------------------
# D12 — last_finish_reason
# ---------------------------------------------------------------------------


def test_every_provider_exposes_last_finish_reason() -> None:
    """D12: a token-limit truncation must be detectable on every provider."""
    from backend.llm.airllm_provider import AirLLMProvider
    from backend.llm.kilo_provider import KiloProvider
    from backend.llm.lmstudio_provider import LMStudioProvider
    from backend.llm.ollama_provider import OllamaProvider

    providers = [
        AnthropicProvider(api_key="k"),
        GeminiProvider(api_key="k"),
        KimiProvider(api_key="k"),
        OpenAIProvider("https://api.example.test/v1", api_key="k"),
        OpenCodeGoProvider(api_key="k"),
        AirLLMProvider(),
        OpenRouterProvider(api_key="k"),
        LMStudioProvider(),
        KiloProvider(api_key="k"),
        OllamaProvider(base_url="http://127.0.0.1:1"),
        DevProvider(),
        MockProvider(),
    ]

    for provider in providers:
        assert hasattr(provider, "last_finish_reason"), (
            f"{type(provider).__name__} does not expose last_finish_reason"
        )
        reason = provider.last_finish_reason
        assert reason is None or isinstance(reason, str)


# ---------------------------------------------------------------------------
# D13 — SSE frames without a space after ``data:``
# ---------------------------------------------------------------------------


async def test_sse_frame_without_a_space_after_data_is_parsed(fake_server: Any) -> None:
    """D13: ``data:{...}`` is legal SSE and must not be dropped."""
    fake_server.sse(
        "POST",
        "/v1/chat/completions",
        openai_sse(
            [{"choices": [{"delta": {"content": "olá"}, "finish_reason": None}]}],
            space=False,
        ),
    )

    provider = OpenAIProvider(f"{fake_server.base_url}/v1", api_key="k")
    try:
        text = "".join(
            [
                token
                async for token in provider.chat_stream(
                    "model", [{"role": "user", "content": "ola"}]
                )
            ]
        )
    finally:
        await provider.aclose()

    assert text == "olá"


# ---------------------------------------------------------------------------
# D14 — an empty completion is not a success
# ---------------------------------------------------------------------------


async def test_empty_completion_is_not_a_success() -> None:
    """D14: ``""`` used to be returned as a successful, blank answer."""
    from backend.llm.circuit_breaker import reset_breaker

    class _Empty:
        async def chat_complete(self, model, messages, **kwargs):  # type: ignore[override]
            return ""

    manager = MultiLLMManager(free_only=False)
    manager.register_provider("defect-empty-completion", _Empty())

    with pytest.raises(ProviderUnavailableError):
        await manager.chat_complete("model", [{"role": "user", "content": "x"}])
    reset_breaker("defect-empty-completion")


async def test_empty_completion_is_not_a_success_in_the_fallback_chain() -> None:
    """D14: the resilient chain must refuse a blank answer too."""

    class _Empty:
        async def chat_complete(self, model, messages, **kwargs):  # type: ignore[override]
            return "   "

    client = ResilientLLMProvider(_Empty(), [])
    with pytest.raises(ProviderUnavailableError):
        await client.chat_complete("model", [{"role": "user", "content": "x"}])


# ---------------------------------------------------------------------------
# D15 — Retry-After
# ---------------------------------------------------------------------------


async def test_retry_after_header_is_honoured(
    fake_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D15: the provider said when to come back; the backoff must listen."""
    import backend.llm.gemini_provider as gemini_module

    fake_server.respond(
        "POST",
        "/v1beta/models/gemini-2.5-flash:generateContent",
        status=503,
        text="busy",
        headers={"Retry-After": "7"},
    )

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(gemini_module.asyncio, "sleep", fake_sleep)

    provider = GeminiProvider(base_url=f"{fake_server.base_url}/v1beta", api_key="k")
    try:
        with pytest.raises(ProviderHTTPStatusError):
            await provider.chat_complete(
                "gemini-2.5-flash", [{"role": "user", "content": "x"}]
            )
    finally:
        await provider.aclose()

    # The fixed exponential backoff (1s, 2s) was replaced by the 7s the
    # provider asked for.
    assert sleeps == [7.0, 7.0]


# ---------------------------------------------------------------------------
# D16 — an unknown model id must raise
# ---------------------------------------------------------------------------


def test_unknown_model_id_raises_instead_of_substituting() -> None:
    """D16: an unknown id must not be answered with the default text model."""
    provider = OpenCodeGoProvider(api_key="k")

    with pytest.raises(ValueError, match="Unknown OpenCode Go model"):
        provider.resolve_model("totally-unknown-model")

    # The vision tier of config/models.yaml is declared explicitly, so it
    # resolves to a real model of this provider instead of the default one.
    resolved = provider.resolve_model("gemini-2.0-flash")
    assert resolved in provider.list_models()
    assert resolved != provider.DEFAULT_MODEL


def test_openrouter_minimax_alias_uses_current_free_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The internal fast-tier alias must not point at the removed GPT-OSS route."""
    monkeypatch.delenv("NEXUS_OPENROUTER_TOOL_MODEL", raising=False)

    provider = OpenRouterProvider()

    assert provider.resolve_model("minimax-m3") == "nvidia/nemotron-3.5-lightning:free"


# ---------------------------------------------------------------------------
# D18 — OpenAI-compatible transient chat retries
# ---------------------------------------------------------------------------


async def test_openai_chat_stream_retries_transient_errors_with_same_context(
    fake_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry 503s every 15s while preserving the complete model request."""
    calls: list[Any] = []
    sleeps: list[float] = []

    def handle(request: Any) -> Response:
        calls.append(request)
        if len(calls) < 3:
            return Response(status=503, body=b"temporarily unavailable")
        return Response(
            status=200,
            body=(
                "\n\n".join(
                    openai_sse(
                        [
                            {"choices": [{"delta": {"content": "resposta"}}]},
                            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                        ]
                    )
                )
                + "\n\n"
            ).encode(),
            content_type="text/event-stream",
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    fake_server.route("POST", "/v1/chat/completions", handle)
    monkeypatch.setattr(openai_provider_module.asyncio, "sleep", fake_sleep)
    provider = OpenAIProvider(base_url=fake_server.base_url, api_key="k")
    messages = [
        {"role": "system", "content": "context and project rules"},
        {"role": "user", "content": "edit two files and run checks"},
    ]
    options = {"temperature": 0.1, "tools": [{"type": "function", "function": {"name": "read_file"}}]}
    try:
        answer = "".join(
            [
                token
                async for token in provider.chat_stream(
                    "model-x", messages, options=options
                )
            ]
        )
    finally:
        await provider.aclose()

    assert answer == "resposta"
    assert len(calls) == 3
    assert [call.json() for call in calls] == [calls[0].json()] * 3
    assert calls[0].json()["messages"] == messages
    assert calls[0].json()["tools"] == options["tools"]
    assert sleeps == [15.0, 15.0]


async def test_openai_chat_stream_retries_empty_success_response_with_same_context(
    fake_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An HTTP 200 with no answer is retried before anything is exposed."""
    calls: list[Any] = []
    sleeps: list[float] = []

    def handle(request: Any) -> Response:
        calls.append(request)
        if len(calls) == 1:
            return Response(
                status=200,
                body=(
                    openai_sse(
                        [{"choices": [{"delta": {}, "finish_reason": "stop"}]}]
                    )[0]
                    + "\n\n"
                ).encode(),
                content_type="text/event-stream",
            )
        return Response(
            status=200,
            body=(
                "\n\n".join(
                    openai_sse(
                        [
                            {"choices": [{"delta": {"content": "recuperado"}}]},
                            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                        ]
                    )
                )
                + "\n\n"
            ).encode(),
            content_type="text/event-stream",
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    fake_server.route("POST", "/v1/chat/completions", handle)
    monkeypatch.setattr(openai_provider_module.asyncio, "sleep", fake_sleep)
    provider = OpenAIProvider(base_url=fake_server.base_url, api_key="k")
    messages = [
        {"role": "system", "content": "project and conversation context"},
        {"role": "user", "content": "continue the interrupted task"},
    ]
    options = {
        "temperature": 0.1,
        "tools": [{"type": "function", "function": {"name": "read_file"}}],
    }
    try:
        answer = "".join(
            [
                token
                async for token in provider.chat_stream(
                    "model-x", messages, options=options
                )
            ]
        )
    finally:
        await provider.aclose()

    assert answer == "recuperado"
    assert len(calls) == 2
    assert [call.json() for call in calls] == [calls[0].json()] * 2
    assert calls[0].json()["messages"] == messages
    assert calls[0].json()["tools"] == options["tools"]
    assert sleeps == [15.0]


async def test_openai_chat_complete_retries_transient_errors_with_same_context(
    fake_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The non-streaming model path keeps the same request during retries too."""
    calls: list[Any] = []
    sleeps: list[float] = []

    def handle(request: Any) -> Response:
        calls.append(request)
        if len(calls) < 3:
            return Response(status=502, body=b"upstream gateway error")
        return Response(
            status=200,
            body=json.dumps(
                {"choices": [{"message": {"content": "completed"}, "finish_reason": "stop"}]}
            ).encode(),
            content_type="application/json",
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    fake_server.route("POST", "/v1/chat/completions", handle)
    monkeypatch.setattr(openai_provider_module.asyncio, "sleep", fake_sleep)
    provider = OpenAIProvider(base_url=fake_server.base_url, api_key="k")
    messages = [
        {"role": "system", "content": "project context"},
        {"role": "user", "content": "fix the failing test"},
    ]
    try:
        answer = await provider.chat_complete("model-x", messages)
    finally:
        await provider.aclose()

    assert answer == "completed"
    assert len(calls) == 3
    assert [call.json() for call in calls] == [calls[0].json()] * 3
    assert calls[0].json()["messages"] == messages
    assert sleeps == [15.0, 15.0]


async def test_openai_chat_stream_stops_after_ten_total_attempts(
    fake_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A permanently unavailable API gets ten bounded attempts, then fails."""
    sleeps: list[float] = []
    fake_server.respond("POST", "/v1/chat/completions", status=503, text="busy")

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(openai_provider_module.asyncio, "sleep", fake_sleep)
    provider = OpenAIProvider(base_url=fake_server.base_url, api_key="k")
    try:
        with pytest.raises(ProviderHTTPStatusError) as error:
            _ = [
                token
                async for token in provider.chat_stream(
                    "model-x", [{"role": "user", "content": "keep this context"}]
                )
            ]
    finally:
        await provider.aclose()

    assert error.value.status_code == 503
    assert len(fake_server.requests) == 10
    assert sleeps == [15.0] * 9


async def test_openai_chat_stream_never_retries_after_visible_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken stream after a visible token is surfaced without duplication."""
    calls = 0
    sleeps: list[float] = []

    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            )
            raise httpx.ReadError("connection lost after content")

        async def aclose(self) -> None:
            return None

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=BrokenStream(),
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(openai_provider_module.asyncio, "sleep", fake_sleep)
    provider = OpenAIProvider(base_url="http://provider.test", api_key="k")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="http://provider.test", transport=httpx.MockTransport(handle)
    )
    try:
        stream = provider.chat_stream("model-x", [{"role": "user", "content": "x"}])
        assert await anext(stream) == "partial"
        with pytest.raises(httpx.ReadError, match="connection lost"):
            await anext(stream)
    finally:
        await provider.aclose()

    assert calls == 1
    assert sleeps == []
