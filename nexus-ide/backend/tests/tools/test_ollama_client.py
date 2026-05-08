"""Tests for backend.tools.ollama_client — streaming + error handling."""
from __future__ import annotations

import json

import httpx
import pytest

from backend.tests.conftest import make_stream_response
from backend.tools.ollama_client import ChatMessage, OllamaClient, OllamaError


class TestChatMessage:
    def test_to_dict(self) -> None:
        result = ChatMessage(role="user", content="hi").to_dict()
        assert result["role"] == "user"
        assert result["content"] == "hi"
        assert "timestamp" in result


class TestChatStream:
    async def test_streams_every_chunk(self) -> None:
        tokens = ["a", "b", "c", "d"]
        def handler(req: httpx.Request) -> httpx.Response:
            return make_stream_response(tokens)
        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            out = [
                t async for t in client.chat_stream(
                    "qwen2.5:0.5b", [ChatMessage(role="user", content="go")]
                )
            ]
            assert out == tokens
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
                [ChatMessage(role="system", content="sys"),
                 ChatMessage(role="user", content="hi")],
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

    async def test_skips_malformed_lines(self) -> None:
        body = (
            "not json\n"
            + json.dumps({"message": {"content": "x"}, "done": False}) + "\n"
            + json.dumps({"done": True}) + "\n"
        )
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body.encode())
        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            out = [t async for t in client.chat_stream(
                "m", [ChatMessage(role="user", content="q")]
            )]
            assert out == ["x"]
        finally:
            await client.aclose()

    async def test_non_200_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="upstream busy")
        client = OllamaClient("http://mock", transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(OllamaError) as excinfo:
                async for _ in client.chat_stream(
                    "m", [ChatMessage(role="user", content="q")]
                ):
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
            out = await client.chat_complete(
                "m", [ChatMessage(role="user", content="hi")]
            )
            assert out == "Hello world"
        finally:
            await client.aclose()
