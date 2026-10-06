"""Integration test for POST /api/chat streaming contract.

Verifies that:
- SSE frames are received
- run_id and seq are present in frames
- the response is not empty
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.middleware.auth import create_access_token
from backend.orchestrator import main as main_module
from backend.tests.conftest import make_stream_response
from backend.tools.ollama_client import OllamaClient


def _install_mock_ollama(tokens: list[str]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/chat":
            return make_stream_response(tokens)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def client_with_mocked_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    mock_transport = _install_mock_ollama(["Hello", " ", "NEXUS"])

    original = OllamaClient.__init__

    def patched_init(self, base_url: str = "", *, transport=None, timeout=None, limits=None):
        kwargs: dict = {"transport": mock_transport}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if limits is not None:
            kwargs["limits"] = limits
        return original(self, base_url, **kwargs)

    monkeypatch.setattr(OllamaClient, "__init__", patched_init)

    for attr in ("ollama", "llm_client"):
        if hasattr(main_module.app.state, attr):
            delattr(main_module.app.state, attr)

    from backend.llm.factory import create_llm_client

    monkeypatch.setattr(
        "backend.llm.create_llm_client",
        lambda: create_llm_client(
            multi_llm_enabled=False,
            llm_provider="ollama",
            ollama_host="http://ollama.test",
            free_only=False,
        ),
    )

    token = create_access_token({"sub": "test-user", "email": "test@test.com"})
    with TestClient(main_module.app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


def _iter_sse_frames(body: bytes) -> list[dict]:
    frames: list[dict] = []
    for line in body.decode().splitlines():
        if line.startswith("data: "):
            frames.append(json.loads(line[len("data: ") :]))
    return frames


class TestChatStreamingIntegration:
    def test_stream_produces_sse_frames_with_run_id_and_seq(
        self, client_with_mocked_ollama: TestClient
    ) -> None:
        response = client_with_mocked_ollama.post(
            "/api/chat",
            json={"message": "what is HTTP?", "session_id": "t-stream"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        frames = _iter_sse_frames(response.content)
        assert frames, "SSE response must not be empty"

        for frame in frames:
            assert "run_id" in frame, f"frame missing run_id: {frame}"
            assert "seq" in frame, f"frame missing seq: {frame}"
            assert isinstance(frame["run_id"], str)
            assert isinstance(frame["seq"], int)
            assert frame["seq"] > 0
