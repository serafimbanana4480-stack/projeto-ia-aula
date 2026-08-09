"""Tests for backend.tools.ollama_client — streaming + error handling."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.tests.conftest import make_stream_response
from backend.tools.ollama_client import DEFAULT_LIMITS, ChatMessage, OllamaClient, OllamaError


class TestChatMessage:
    def test_to_dict(self) -> None:
        result = ChatMessage(role="user", content="hi").to_dict()
        assert result["role"] == "user"
        assert result["content"] == "hi"
        assert "timestamp" in result


class TestChatStream:
    async def test_uses_httpx_stream_instead_of_buffering_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The response must remain open while tokens are yielded."""

        def handler(req: httpx.Request) -> httpx.Response:
            return make_stream_response(["first", " second"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        stream_calls: list[tuple[tuple, dict]] = []
        original_stream = client._client.stream

        def tracked_stream(*args, **kwargs):
            stream_calls.append((args, kwargs))
            return original_stream(*args, **kwargs)

        async def request_must_not_be_used(*args, **kwargs):
            raise AssertionError("chat_stream must not use AsyncClient.request")

        monkeypatch.setattr(client._client, "stream", tracked_stream)
        monkeypatch.setattr(client._client, "request", request_must_not_be_used)
        try:
            tokens = [
                token
                async for token in client.chat_stream("m", [ChatMessage(role="user", content="q")])
            ]
            assert tokens == ["first", " second"]
            assert len(stream_calls) == 1
            assert stream_calls[0][0][:2] == ("POST", "/api/chat")
        finally:
            await client.aclose()

    async def test_streams_every_chunk(self) -> None:
        tokens = ["a", "b", "c", "d"]

        def handler(req: httpx.Request) -> httpx.Response:
            return make_stream_response(tokens)

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            out = [
                t
                async for t in client.chat_stream(
                    "qwen2.5:0.5b", [ChatMessage(role="user", content="go")]
                )
            ]
            assert out == tokens
        finally:
            await client.aclose()

    async def test_keeps_content_in_the_final_done_frame(self) -> None:
        body = (
            json.dumps({"message": {"content": "Hello "}, "done": False})
            + "\n"
            + json.dumps(
                {
                    "message": {"content": "world"},
                    "done": True,
                    "prompt_eval_count": 3,
                    "eval_count": 2,
                }
            )
            + "\n"
        )

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body.encode())

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            result = await client.chat_complete("m", [ChatMessage(role="user", content="q")])
            assert result == "Hello world"
            assert client._last_usage == {
                "input_tokens": 3,
                "output_tokens": 2,
                "total_tokens": 5,
            }
        finally:
            await client.aclose()

    async def test_request_payload_is_correct(self) -> None:
        captured: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["url"] = req.url.path
            captured["body"] = json.loads(req.content.decode())
            return make_stream_response(["ok"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            async for _ in client.chat_stream(
                "qwen2.5:0.5b",
                [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="hi")],
                options={"temperature": 0.5},
            ):
                pass
            assert captured["url"] == "/api/chat"
            body = captured["body"]
            assert body["model"] == "qwen2.5:0.5b"
            assert body["stream"] is True
            # Check that messages contain required fields (timestamp is now included)
            assert len(body["messages"]) == 2
            assert body["messages"][0]["role"] == "system"
            assert body["messages"][0]["content"] == "sys"
            assert body["messages"][1]["role"] == "user"
            assert body["messages"][1]["content"] == "hi"
            assert body["options"] == {"temperature": 0.5}
        finally:
            await client.aclose()

    async def test_moves_late_system_messages_before_other_turns(self) -> None:
        captured: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["messages"] = json.loads(req.content.decode())["messages"]
            return make_stream_response(["ok"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            async for _ in client.chat_stream(
                "qwen2.5:0.5b",
                [
                    ChatMessage(role="user", content="question"),
                    ChatMessage(role="system", content="recovery directive"),
                    ChatMessage(role="tool", content="evidence"),
                ],
            ):
                pass
            assert [m["role"] for m in captured["messages"]] == ["system", "user", "tool"]
            assert captured["messages"][0]["content"] == "recovery directive"
        finally:
            await client.aclose()

    async def test_disables_qwen_thinking_by_default_but_allows_explicit_override(self) -> None:
        captured: list[dict] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(json.loads(req.content.decode()))
            return make_stream_response(["ok"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            async for _ in client.chat_stream(
                "hf.co/zaakirio/Ornith-1.0-9B-uncensored-GGUF:Q4_K_M",
                [ChatMessage(role="user", content="hi")],
            ):
                pass
            assert captured[0]["think"] is False

            async for _ in client.chat_stream(
                "qwen2.5:0.5b",
                [ChatMessage(role="user", content="hi")],
                options={"think": True},
            ):
                pass
            assert captured[1]["think"] is True
        finally:
            await client.aclose()

    async def test_skips_malformed_lines(self) -> None:
        body = (
            "not json\n"
            + json.dumps({"message": {"content": "x"}, "done": False})
            + "\n"
            + json.dumps({"done": True})
            + "\n"
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body.encode())

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            out = [
                t async for t in client.chat_stream("m", [ChatMessage(role="user", content="q")])
            ]
            assert out == ["x"]
        finally:
            await client.aclose()

    async def test_error_payload_is_not_reported_as_an_empty_success(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b'{"error":"model is unavailable"}\n')

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(OllamaError, match="model is unavailable"):
                async for _ in client.chat_stream("m", [ChatMessage(role="user", content="q")]):
                    pass
        finally:
            await client.aclose()

    async def test_done_without_content_raises_instead_of_returning_blank_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b'{"done":true}\n')

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)
        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(OllamaError, match="completed without content"):
                async for _ in client.chat_stream("m", [ChatMessage(role="user", content="q")]):
                    pass
            assert sleeps == [1, 2, 4, 8]
        finally:
            await client.aclose()

    async def test_non_200_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="upstream busy")

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(OllamaError) as excinfo:
                async for _ in client.chat_stream("m", [ChatMessage(role="user", content="q")]):
                    pass
            assert "503" in str(excinfo.value)
        finally:
            await client.aclose()


class TestChatComplete:
    async def test_concatenates_stream(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return make_stream_response(["Hello ", "world"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            out = await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert out == "Hello world"
        finally:
            await client.aclose()


class TestRetryOnServerError:
    async def test_retry_on_503_then_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(503, text="upstream busy")
            return make_stream_response(["ok"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            result = await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert result == "ok"
            assert call_count == 3
            assert sleeps == [1, 2]
        finally:
            await client.aclose()

    async def test_retry_on_500_then_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, text="internal error")
            return make_stream_response(["ok"])

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            result = await client.chat_complete("m", [ChatMessage(role="user", content="hi")])
            assert result == "ok"
            assert call_count == 2
            assert sleeps == [1]
        finally:
            await client.aclose()

    async def test_503_exhausted_raises_with_history(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("backend.tools.ollama_client.asyncio.sleep", fake_sleep)

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="upstream busy")

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(OllamaError) as excinfo:
                async for _ in client.chat_stream("m", [ChatMessage(role="user", content="q")]):
                    pass
            assert "failed after 5 attempts" in str(excinfo.value)
            assert "HTTP 503" in str(excinfo.value)
            assert sleeps == [1, 2, 4, 8]
        finally:
            await client.aclose()


class TestHealthCheck:
    async def test_health_check_success(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == "/api/tags"
            return httpx.Response(200, json={"models": []})

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            assert await client.health_check() is True
        finally:
            await client.aclose()

    async def test_health_check_failure_status(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="busy")

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            assert await client.health_check() is False
        finally:
            await client.aclose()

    async def test_health_check_failure_exception(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            assert await client.health_check() is False
        finally:
            await client.aclose()

    async def test_health_check_custom_timeout(self) -> None:

        def handler(req: httpx.Request) -> httpx.Response:
            # httpx MockTransport doesn't expose timeout directly,
            # but we can verify the method is callable with a custom timeout
            return httpx.Response(200, json={"models": []})

        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            # Just verify it accepts the timeout parameter without error
            assert await client.health_check(timeout=0.5) is True
        finally:
            await client.aclose()


class TestConnectionPool:
    def test_default_limits_have_50_keepalive(self) -> None:
        assert DEFAULT_LIMITS.max_keepalive_connections == 50
