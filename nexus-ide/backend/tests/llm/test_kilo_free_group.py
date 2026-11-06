import httpx
import pytest

from backend.llm.kilo_provider import AnonymousFreeKiloProvider, KiloFreeModelUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [
    None,
    {"id": "example/model:free", "pricing": {"prompt": "0", "completion": "1"}},
    {"id": "example/model:free", "pricing": {"prompt": "0"}},
])
async def test_anonymous_free_kilo_refuses_unverified_models(entry):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [entry] if entry else []})

    provider = AnonymousFreeKiloProvider()
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://ai-gateway.kilo.ai/api", transport=httpx.MockTransport(handle)
    )
    try:
        with pytest.raises(KiloFreeModelUnavailable):
            _ = [chunk async for chunk in provider.chat_stream("example/model:free", [])]
        assert len(requests) == 1
        assert "authorization" not in requests[0].headers
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_anonymous_free_kilo_rejects_paid_model_before_network():
    provider = AnonymousFreeKiloProvider()
    try:
        with pytest.raises(KiloFreeModelUnavailable):
            _ = [chunk async for chunk in provider.chat_stream("example/paid", [])]
    finally:
        await provider.aclose()
