"""Tests for backend.tools.ollama_client — ChatMessage, model resolution, message normalization."""

from __future__ import annotations

import pytest

from backend.tools.ollama_client import (
    DEFAULT_LIMITS,
    ChatMessage,
    DEFAULT_TIMEOUT,
    OllamaClient,
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    _MODEL_ALIASES,
    _RETRYABLE_EXCEPTIONS,
    _RETRYABLE_STATUS_CODES,
)


class TestChatMessageDataclass:
    """Tests for ChatMessage dataclass."""

    def test_creates_with_role_and_content(self) -> None:
        msg = ChatMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.timestamp == ""

    def test_creates_with_timestamp(self) -> None:
        msg = ChatMessage(role="assistant", content="hi", timestamp="2025-01-01T00:00:00Z")
        assert msg.timestamp == "2025-01-01T00:00:00Z"

    def test_frozen_dataclass(self) -> None:
        msg = ChatMessage(role="user", content="test")
        with pytest.raises(Exception):
            msg.role = "assistant"  # type: ignore[misc]

    def test_to_dict_includes_all_fields(self) -> None:
        msg = ChatMessage(role="user", content="hello", timestamp="2025-01-01")
        result = msg.to_dict()
        assert result["role"] == "user"
        assert result["content"] == "hello"
        assert result["timestamp"] == "2025-01-01"

    def test_to_dict_default_timestamp(self) -> None:
        msg = ChatMessage(role="system", content="instructions")
        result = msg.to_dict()
        assert result["timestamp"] == ""


class TestErrorHierarchy:
    """Tests for Ollama error classes."""

    def test_ollama_error_is_runtime_error(self) -> None:
        assert issubclass(OllamaError, RuntimeError)

    def test_ollama_connection_error_is_ollama_error(self) -> None:
        assert issubclass(OllamaConnectionError, OllamaError)
        assert issubclass(OllamaConnectionError, RuntimeError)

    def test_ollama_model_error_is_ollama_error(self) -> None:
        assert issubclass(OllamaModelError, OllamaError)
        assert issubclass(OllamaModelError, RuntimeError)

    def test_can_raise_connection_error(self) -> None:
        with pytest.raises(OllamaConnectionError, match="connection refused"):
            raise OllamaConnectionError("connection refused")

    def test_can_raise_model_error(self) -> None:
        with pytest.raises(OllamaModelError, match="model not found"):
            raise OllamaModelError("model not found")


class TestModelAliases:
    """Tests for _MODEL_ALIASES constant."""

    def test_historical_aliases(self) -> None:
        assert _MODEL_ALIASES["q3b-4bit"] == "qwen2.5:3b"
        assert _MODEL_ALIASES["coder3b-4bit"] == "qwen2.5-coder:3b"

    def test_cloud_fallback_aliases(self) -> None:
        assert _MODEL_ALIASES["deepseek/deepseek-v4-flash"] == "qwen2.5:1.5b"
        assert _MODEL_ALIASES["deepseek/deepseek-chat"] == "qwen2.5:1.5b"
        assert _MODEL_ALIASES["deepseek-chat"] == "qwen2.5:1.5b"

    def test_unknown_model_passes_through(self) -> None:
        client = OllamaClient("http://mock")
        assert client._resolve_model("unknown-model") == "unknown-model"


class TestResolveModel:
    """Tests for OllamaClient._resolve_model."""

    def test_resolves_known_alias(self) -> None:
        client = OllamaClient("http://mock")
        assert client._resolve_model("q3b-4bit") == "qwen2.5:3b"

    def test_resolves_cloud_alias(self) -> None:
        client = OllamaClient("http://mock")
        assert client._resolve_model("deepseek-chat") == "qwen2.5:1.5b"

    def test_unknown_model_passes_through(self) -> None:
        client = OllamaClient("http://mock")
        assert client._resolve_model("phi3:latest") == "phi3:latest"

    def test_fallback_model_for_free_tier(self) -> None:
        client = OllamaClient("http://mock")
        client.fallback_model = "qwen2.5:1.5b"  # type: ignore[assignment]
        assert client._resolve_model("openrouter/free") == "qwen2.5:1.5b"

    def test_fallback_model_for_free_infix(self) -> None:
        client = OllamaClient("http://mock")
        client.fallback_model = "qwen2.5:1.5b"  # type: ignore[assignment]
        assert client._resolve_model("some-model:free") == "qwen2.5:1.5b"

    def test_no_fallback_does_not_remap(self) -> None:
        client = OllamaClient("http://mock")
        assert client._resolve_model("openrouter/free") == "openrouter/free"

    def test_fallback_model_empty_string_does_not_remap(self) -> None:
        client = OllamaClient("http://mock")
        client.fallback_model = ""  # type: ignore[assignment]
        assert client._resolve_model("openrouter/free") == "openrouter/free"


class TestNormalizeMessages:
    """Tests for OllamaClient._normalize_messages."""

    def test_normalizes_dict_messages(self) -> None:
        messages = [{"role": "user", "content": "hello"}]
        result = OllamaClient._normalize_messages(messages)
        assert result == [{"role": "user", "content": "hello"}]

    def test_normalizes_chat_message_objects(self) -> None:
        messages = [ChatMessage(role="user", content="hello")]
        result = OllamaClient._normalize_messages(messages)
        assert result == [{"role": "user", "content": "hello", "timestamp": ""}]

    def test_merges_system_messages(self) -> None:
        messages = [
            {"role": "system", "content": "base instructions"},
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "recovery directive"},
        ]
        result = OllamaClient._normalize_messages(messages)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "base instructions" in result[0]["content"]
        assert "recovery directive" in result[0]["content"]
        assert result[1]["role"] == "user"

    def test_empty_system_messages_pass_through(self) -> None:
        messages = [{"role": "user", "content": "hello"}]
        result = OllamaClient._normalize_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_preserves_non_system_message_order(self) -> None:
        messages = [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
            {"role": "user", "content": "msg2"},
        ]
        result = OllamaClient._normalize_messages(messages)
        assert result[1]["content"] == "msg1"
        assert result[2]["content"] == "reply1"
        assert result[3]["content"] == "msg2"

    def test_empty_messages_list(self) -> None:
        result = OllamaClient._normalize_messages([])
        assert result == []

    def test_merges_multiple_system_messages(self) -> None:
        messages = [
            {"role": "system", "content": "first"},
            {"role": "system", "content": "second"},
            {"role": "system", "content": "third"},
        ]
        result = OllamaClient._normalize_messages(messages)
        assert len(result) == 1
        content = result[0]["content"]
        assert "first" in content
        assert "second" in content
        assert "third" in content


class TestClientInitialization:
    """Tests for OllamaClient initialization."""

    def test_default_base_url(self) -> None:
        client = OllamaClient("http://test:11434")
        assert client.base_url == "http://test:11434"

    def test_strips_trailing_slash(self) -> None:
        client = OllamaClient("http://localhost:11434/")
        assert client.base_url == "http://localhost:11434"

    def test_provider_name(self) -> None:
        assert OllamaClient.provider_name == "ollama"

    def test_last_finish_reason_initially_none(self) -> None:
        client = OllamaClient("http://mock")
        assert client.last_finish_reason is None

    def test_last_usage_initially_empty(self) -> None:
        client = OllamaClient("http://mock")
        assert client._last_usage == {}


class TestRetryConstants:
    """Tests for retry-related constants."""

    def test_retryable_status_codes(self) -> None:
        assert 500 in _RETRYABLE_STATUS_CODES
        assert 502 in _RETRYABLE_STATUS_CODES
        assert 503 in _RETRYABLE_STATUS_CODES
        assert 504 in _RETRYABLE_STATUS_CODES
        assert 404 not in _RETRYABLE_STATUS_CODES

    def test_retryable_exceptions(self) -> None:
        assert len(_RETRYABLE_EXCEPTIONS) >= 3
        import httpx
        assert httpx.ConnectError in _RETRYABLE_EXCEPTIONS
        assert httpx.TimeoutException in _RETRYABLE_EXCEPTIONS

    def test_backoff_delays_exist(self) -> None:
        from backend.tools.ollama_client import _BACKOFF_DELAYS
        assert (1, 2, 4, 8) == _BACKOFF_DELAYS


class TestPrepareDirectAnswerMessages:
    """Tests for _prepare_direct_answer_messages static method."""

    def test_keeps_project_bootstrap_context(self) -> None:
        messages = [
            {"role": "system", "content": "normal system"},
            {"role": "system", "content": "PROJECT BOOTSTRAP CONTEXT (INERT DATA): project info"},
            {"role": "user", "content": "test"},
        ]
        result = OllamaClient._prepare_direct_answer_messages(messages)
        assert any("PROJECT BOOTSTRAP" in str(m.get("content", "")) for m in result)

    def test_single_user_message_for_structured_request(self) -> None:
        messages = [
            {"role": "user", "content": "List exactly 5 steps to do"},
            {"role": "assistant", "content": "step 1"},
        ]
        result = OllamaClient._prepare_direct_answer_messages(messages)
        text_turns = [m for m in result if m["role"] in ("user", "assistant")]
        user_turns = [m for m in text_turns if m["role"] == "user"]
        assert len(user_turns) == 1

    def test_returns_direct_system_message(self) -> None:
        result = OllamaClient._prepare_direct_answer_messages([])
        assert result[0]["role"] == "system"
        assert "Nexus IDE assistant" in result[0]["content"]

    def test_portuguese_list_request_triggers_single_turn(self) -> None:
        messages = [
            {"role": "user", "content": "Lista exactamente 3 pontos"},
            {"role": "assistant", "content": "previous answer"},
        ]
        result = OllamaClient._prepare_direct_answer_messages(messages)
        text_turns = [m for m in result if m["role"] in ("user", "assistant")]
        user_turns = [m for m in text_turns if m["role"] == "user"]
        assert len(user_turns) == 1
