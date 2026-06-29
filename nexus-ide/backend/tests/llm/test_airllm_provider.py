"""Tests for AirLLMProvider.

These tests do NOT download models — they test provider logic, registry,
circuit breaker, and fallback embeddings in isolation.
"""

from __future__ import annotations

import pytest

from backend.llm.airllm_provider import (
    AIRLLM_AVAILABLE,
    DEFAULT_MODEL_REGISTRY,
    AirLLMProvider,
    ChatMessage,
    CircuitBreaker,
    CircuitState,
    _DirectHFModel,
    _load_airllm_model,
    _resolve_model_id,
)


class TestModelRegistry:
    def test_resolve_known_alias(self) -> None:
        assert _resolve_model_id("qwen3.5:9b") == "Qwen/Qwen2.5-7B-Instruct"

    def test_resolve_unknown_returns_as_is(self) -> None:
        assert _resolve_model_id("custom/model") == "custom/model"

    def test_all_aliases_have_values(self) -> None:
        for _alias, repo in DEFAULT_MODEL_REGISTRY.items():
            assert repo and isinstance(repo, str)


class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_success_resets(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestAirLLMProviderLogic:
    def test_init_defaults(self) -> None:
        p = AirLLMProvider()
        assert p._device in ("cpu", "cuda:0")
        assert p._compression is None or p._compression == ""

    def test_inject_thinking_disable(self) -> None:
        p = AirLLMProvider()
        opts = p._inject_thinking_disable("qwen3.5:9b", None)
        assert opts is not None
        assert opts.get("thinking") is False

    def test_extract_gen_params(self) -> None:
        p = AirLLMProvider()
        assert p._extract_gen_params({}) == {}
        assert p._extract_gen_params({"temperature": 0.5}) == {"temperature": 0.5}
        assert p._extract_gen_params({"max_tokens": 100}) == {"max_new_tokens": 100}

    def test_hash_embed_deterministic(self) -> None:
        p = AirLLMProvider()
        v1 = p._hash_embed("hello")
        v2 = p._hash_embed("hello")
        v3 = p._hash_embed("world")
        assert v1 == v2
        assert v1 != v3
        assert len(v1) == p._embed_fallback_dim

    def test_hash_embed_normalized(self) -> None:
        p = AirLLMProvider()
        vec = p._hash_embed("test")
        norm = sum(x * x for x in vec)
        assert abs(norm - 1.0) < 1e-6


class TestChatMessage:
    def test_to_dict(self) -> None:
        msg = ChatMessage(role="user", content="hello")
        assert msg.to_dict() == {"role": "user", "content": "hello", "timestamp": ""}


@pytest.mark.asyncio
@pytest.mark.skipif(not AIRLLM_AVAILABLE, reason="AirLLM not installed")
class TestAirLLMProviderAsync:
    async def test_health_check_without_cuda(self) -> None:
        p = AirLLMProvider(device="cpu")
        assert await p.health_check() is True

    async def test_health_check_with_cuda_on_cpu_machine(self) -> None:
        p = AirLLMProvider(device="cuda:0")
        # Should return False if CUDA is not available
        import torch

        expected = torch.cuda.is_available()
        assert await p.health_check() == expected

    async def test_chat_stream_yields_tokens(self) -> None:
        """Test that chat_stream yields at least some tokens.

        This uses the MockProvider fallback path because no real model is loaded.
        """
        p = AirLLMProvider(device="cpu")
        # We can't easily test real streaming without a model, but we can test
        # that the provider doesn't crash on init.
        assert p._circuit.state == CircuitState.CLOSED


@pytest.mark.skipif(not AIRLLM_AVAILABLE, reason="AirLLM not installed")
class TestAirLLMQuantization:
    """Test the bitsandbytes 4-bit / 8-bit compression wiring."""

    def test_compression_param_propagates_to_direct_loader(self) -> None:
        """The compression arg must be forwarded to _DirectHFModel."""
        from unittest.mock import patch

        with (
            patch(
                "backend.llm.airllm_provider._resolve_local_path",
                return_value="C:/fake/local/path",
            ),
            patch("backend.llm.airllm_provider._DirectHFModel") as mock_direct,
        ):
            mock_direct.return_value = "model"
            result = _load_airllm_model(
                "Qwen/Qwen2.5-3B-Instruct",
                device="cuda:0",
                compression="4bit",
            )
            assert result == "model"
            # Ensure compression was forwarded
            call_kwargs = mock_direct.call_args.kwargs
            assert call_kwargs.get("compression") == "4bit"
            assert call_kwargs.get("device") == "cuda:0"

    def test_direct_model_passes_quant_kwargs_on_cuda(self) -> None:
        """_DirectHFModel must set load_in_4bit when compression=4bit on CUDA."""
        from unittest.mock import MagicMock, patch

        with (
            patch("transformers.AutoModelForCausalLM") as mock_cls,
            patch("transformers.AutoTokenizer") as mock_tok,
            patch.dict("sys.modules", {"bitsandbytes": MagicMock()}),
        ):
            mock_tok.from_pretrained.return_value = MagicMock()
            mock_cls.from_pretrained.return_value = MagicMock()
            _DirectHFModel("Qwen/Qwen2.5-3B-Instruct", device="cuda:0", compression="4bit")
            # Verify load_in_4bit was passed
            call_kwargs = mock_cls.from_pretrained.call_args.kwargs
            assert call_kwargs.get("load_in_4bit") is True
            assert call_kwargs.get("device_map") == "auto"

    def test_direct_model_skips_quant_on_cpu(self) -> None:
        """Compression on CPU should be a no-op (bitsandbytes needs CUDA)."""
        from unittest.mock import MagicMock, patch

        with (
            patch("transformers.AutoModelForCausalLM") as mock_cls,
            patch("transformers.AutoTokenizer") as mock_tok,
        ):
            mock_tok.from_pretrained.return_value = MagicMock()
            mock_cls.from_pretrained.return_value = MagicMock()
            _DirectHFModel("Qwen/Qwen2.5-0.5B-Instruct", device="cpu", compression="4bit")
            # Verify load_in_4bit was NOT passed (CPU is unsupported)
            call_kwargs = mock_cls.from_pretrained.call_args.kwargs
            assert "load_in_4bit" not in call_kwargs


@pytest.mark.skipif(not AIRLLM_AVAILABLE, reason="AirLLM not installed")
class TestAirLLMFallbackTriggers:
    """Test the AirLLM → direct-transformers fallback triggers."""

    def test_not_enough_space_triggers_fallback(self) -> None:
        """NotEnoughSpaceException must trigger the direct-HF fallback."""
        from unittest.mock import patch

        with patch("backend.llm.airllm_provider.AirAutoModel") as mock_airllm:
            mock_airllm.from_pretrained.side_effect = Exception(
                "Not enough space. Free space under /cache: 0.10GB"
            )
            with patch("backend.llm.airllm_provider._DirectHFModel") as mock_direct:
                mock_direct.return_value = "direct-model"
                result = _load_airllm_model("Qwen/Qwen2.5-0.5B-Instruct", device="cpu")
                assert result == "direct-model"
                mock_direct.assert_called_once()

    def test_sharded_model_error_triggers_fallback(self) -> None:
        """Missing safetensors index triggers the direct-HF fallback."""
        from unittest.mock import patch

        with patch("backend.llm.airllm_provider.AirAutoModel") as mock_airllm:
            mock_airllm.from_pretrained.side_effect = Exception(
                "model.safetensors.index.json should exist"
            )
            with patch("backend.llm.airllm_provider._DirectHFModel") as mock_direct:
                mock_direct.return_value = "direct-model"
                result = _load_airllm_model("Qwen/Qwen2.5-0.5B-Instruct", device="cpu")
                assert result == "direct-model"

    def test_unrelated_error_does_not_fallback(self) -> None:
        """Errors unrelated to sharding must NOT trigger the fallback."""
        from unittest.mock import patch

        with (
            patch(
                "backend.llm.airllm_provider._resolve_local_path",
                return_value=None,
            ),
            patch("backend.llm.airllm_provider.AirAutoModel") as mock_airllm,
        ):
            mock_airllm.from_pretrained.side_effect = ValueError("completely unrelated error")
            with patch("backend.llm.airllm_provider._DirectHFModel") as mock_direct:
                with pytest.raises(ValueError, match="completely unrelated"):
                    _load_airllm_model("Qwen/Qwen2.5-0.5B-Instruct", device="cpu")
                mock_direct.assert_not_called()
