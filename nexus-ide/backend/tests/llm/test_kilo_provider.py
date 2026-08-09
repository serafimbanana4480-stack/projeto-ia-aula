from __future__ import annotations

import asyncio

from backend.llm.kilo_provider import KiloProvider


def test_kilo_uses_gateway_paths_without_v1() -> None:
    provider = KiloProvider(api_key="test-key")
    try:
        request = provider._client.build_request("POST", "/chat/completions")
        assert str(request.url) == "https://api.kilo.ai/api/gateway/chat/completions"
    finally:
        asyncio.run(provider.aclose())
