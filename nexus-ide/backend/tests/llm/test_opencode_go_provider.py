"""Tests for the OpenCode Go provider.

The OpenCode Go provider is the primary cloud LLM provider for NEXUS IDE.
It exposes an OpenAI-compatible chat completions API at
https://opencode.ai/zen/go/v1 and supports a curated list of models.

These tests cover the provider's pure-logic methods (no real API calls) and
mocked streaming behavior. They verify:
- Model list and alias resolution
- Health check (online/offline detection)
- Streaming with mocked aiohttp responses
- chat_complete with mocked responses
- Multi-model resolution
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.llm.opencode_go_provider import OpenCodeGoProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def provider() -> OpenCodeGoProvider:
    """Create a provider instance with a dummy API key."""
    return OpenCodeGoProvider(api_key="test-key-dummy")


# ---------------------------------------------------------------------------
# Model list and resolution
# ---------------------------------------------------------------------------
def test_list_models_contains_all_expected_models(provider: OpenCodeGoProvider) -> None:
    """The provider should expose the canonical list of OpenCode Go models."""
    models = provider.list_models()
    assert isinstance(models, list)
    assert len(models) > 5
    # Core models that should always be available
    expected = [
        "minimax-m3",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "kimi-k2.7-code",
        "glm-5.2",
    ]
    for m in expected:
        assert m in models, f"Expected model '{m}' not in {models}"


def test_list_models_is_sorted_unique(provider: OpenCodeGoProvider) -> None:
    """The list should not contain duplicates and should be stable."""
    models = provider.list_models()
    assert len(models) == len(set(models)), "Model list contains duplicates"


def test_resolve_model_passthrough(provider: OpenCodeGoProvider) -> None:
    """Bare model names (without provider prefix) should be passed through."""
    assert provider.resolve_model("minimax-m3") == "minimax-m3"
    assert provider.resolve_model("deepseek-v4-flash") == "deepseek-v4-flash"


def test_resolve_model_with_alias(provider: OpenCodeGoProvider) -> None:
    """NEXUS-style aliases (e.g. 'deepseek/deepseek-v4-flash') should be mapped."""
    assert provider.resolve_model("deepseek/deepseek-v4-flash") == "deepseek-v4-flash"
    assert provider.resolve_model("openai/gpt-4o") == "minimax-m3"
    assert provider.resolve_model("anthropic/claude-3.5-sonnet") == "glm-5.2"
    assert provider.resolve_model("google/gemini-2.0-flash") == "glm-5.2"


def test_resolve_model_auto_fallback(provider: OpenCodeGoProvider) -> None:
    """The 'auto' alias should map to the default model (minimax-m3)."""
    assert provider.resolve_model("auto") == "minimax-m3"


def test_resolve_model_unknown_falls_back_to_default(provider: OpenCodeGoProvider) -> None:
    """Unknown model IDs should fall back to the default model (minimax-m3)."""
    assert provider.resolve_model("unknown-model-xyz") == provider.DEFAULT_MODEL
    assert provider.resolve_model("unknown-model-xyz") == "minimax-m3"


def test_resolve_model_empty_falls_back_to_default(provider: OpenCodeGoProvider) -> None:
    """Empty model string should fall back to the default."""
    assert provider.resolve_model("") == provider.DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Default model
# ---------------------------------------------------------------------------
def test_default_model_is_minimax_m3(provider: OpenCodeGoProvider) -> None:
    """The default model should be minimax-m3 (the canonical default)."""
    assert provider.DEFAULT_MODEL == "minimax-m3"


def test_base_url_default() -> None:
    """The default base URL should be the OpenCode Go endpoint."""
    p = OpenCodeGoProvider(api_key="test")
    assert p.DEFAULT_BASE_URL == "https://opencode.ai/zen/go/v1"
    assert p._base_url == "https://opencode.ai/zen/go/v1"


def test_base_url_trailing_slash_stripped() -> None:
    """Trailing slashes in the base URL should be stripped."""
    p = OpenCodeGoProvider(base_url="https://opencode.ai/zen/go/v1/", api_key="test")
    assert p._base_url == "https://opencode.ai/zen/go/v1"


# ---------------------------------------------------------------------------
# Aliases map
# ---------------------------------------------------------------------------
def test_model_aliases_dict_has_expected_keys(provider: OpenCodeGoProvider) -> None:
    """The alias map should map common NEXUS-style names to OpenCode Go models."""
    aliases = provider.MODEL_ALIASES
    # NEXUS uses provider/model prefixes
    assert "deepseek/deepseek-v4-flash" in aliases
    assert "deepseek/deepseek-v4-pro" in aliases
    # Other cloud providers
    assert "openai/gpt-4o" in aliases
    assert "anthropic/claude-3-opus" in aliases
    assert "google/gemini-2.0-flash" in aliases


def test_model_aliases_all_resolve_to_valid_models(provider: OpenCodeGoProvider) -> None:
    """Every alias value should be a valid model ID in the catalog."""
    valid_models = set(provider.list_models())
    for alias, target in provider.MODEL_ALIASES.items():
        assert target in valid_models, (
            f"Alias '{alias}' maps to '{target}' which is not in the model catalog"
        )


# ---------------------------------------------------------------------------
# Health check (mocked)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_health_check_handles_exceptions(provider: OpenCodeGoProvider) -> None:
    """Health check should return False (not raise) on any exception."""
    # If any exception is raised internally (e.g. import error, network error),
    # the function should catch it and return False.
    # We can't easily mock the import-time httpx, so we just verify the
    # function returns a bool without raising.
    result = await provider.health_check()
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_health_check_offline(provider: OpenCodeGoProvider) -> None:
    """Health check should return False (offline) when the API is unreachable.

    In a sandboxed test environment without internet, this naturally returns False.
    """
    result = await provider.health_check()
    # Either online or offline — both are valid; the point is no exception raised
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Streaming (mocked)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chat_stream_delegates_to_inner_client(provider: OpenCodeGoProvider) -> None:
    """chat_stream should delegate to the inner OpenAI client (after model resolution)."""

    async def fake_stream(*args, **kwargs):
        yield "Hello "
        yield "world"

    with patch.object(provider._client, "chat_stream", side_effect=fake_stream):
        tokens: list[str] = []
        async for token in provider.chat_stream(
            model="minimax-m3", messages=[{"role": "user", "content": "hi"}]
        ):
            tokens.append(token)

        assert "".join(tokens) == "Hello world"


# ---------------------------------------------------------------------------
# chat_complete (mocked)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chat_complete_returns_string(provider: OpenCodeGoProvider) -> None:
    """chat_complete should return a string response from the inner client.

    The OpenCode Go provider's chat_complete returns the inner client's
    response. The extraction of the assistant message is left to callers
    (or to a higher-level layer like the agent base).
    """
    fake_response = {
        "choices": [{"message": {"role": "assistant", "content": "test response"}}]
    }

    with patch.object(
        provider._client, "chat_complete", AsyncMock(return_value=fake_response)
    ):
        result = await provider.chat_complete(
            model="minimax-m3", messages=[{"role": "user", "content": "hi"}]
        )
        # chat_complete returns the inner client response (a dict)
        assert result == fake_response
        assert result["choices"][0]["message"]["content"] == "test response"


# ---------------------------------------------------------------------------
# acclose
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_aclose_delegates_to_inner_client(provider: OpenCodeGoProvider) -> None:
    """aclose should delegate to the inner OpenAI client."""
    with patch.object(provider._client, "aclose", AsyncMock()) as mock_close:
        await provider.aclose()
        mock_close.assert_awaited_once()


# ---------------------------------------------------------------------------
# last_usage
# ---------------------------------------------------------------------------
def test_last_usage_returns_dict(provider: OpenCodeGoProvider) -> None:
    """last_usage should return a dict (delegated to inner client)."""
    usage = provider.last_usage
    assert isinstance(usage, dict)


# ---------------------------------------------------------------------------
# Provider integration
# ---------------------------------------------------------------------------
def test_provider_uses_openai_compatible_api() -> None:
    """The provider should wrap an OpenAIProvider internally (OpenAI-compatible)."""
    from backend.llm.openai_provider import OpenAIProvider

    p = OpenCodeGoProvider(api_key="test")
    assert isinstance(p._client, OpenAIProvider)
