"""A stalled group participant must not block the following participant."""

import asyncio
import json

import httpx
import pytest

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app
from backend.orchestrator.routes import bot_groups as routes


@pytest.mark.asyncio
async def test_stalled_provider_times_out_and_next_bot_answers(monkeypatch):
    cancelled = asyncio.Event()

    class Provider:
        async def chat_stream(self, model, messages):
            if model == "stalled":
                yield "Resposta parcial"
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            else:
                yield "Resposta do segundo bot"

    async def resolve(selected, client):
        return Provider(), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    monkeypatch.setattr(routes, "_TURN_TIMEOUT_SECONDS", 0.1)
    token = create_access_token({"sub": "timeout-owner", "email": "timeout@test.local"})
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers) as client:
        ids = []
        for name, model in (("Primeiro", "stalled"), ("Segundo", "working")):
            response = await client.post("/api/bots", json={"name": name, "provider": "lmstudio", "model": model})
            assert response.status_code == 201
            ids.append(response.json()["id"])
        group = await client.post("/api/bot-groups", json={"name": "Timeout", "bot_ids": ids})
        group_id = group.json()["id"]
        response = await client.post(f"/api/bot-groups/{group_id}/messages", json={"message": "Analisa"})
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert frames[-1]["status"] == "partial"
        assert cancelled.is_set()
        history = (await client.get(f"/api/bot-groups/{group_id}/messages")).json()["messages"]
        assert [item["role"] for item in history] == ["user", "error", "assistant"]
        assert "tempo limite" in history[1]["content"]
        assert "Resposta parcial" in history[1]["content"]
        assert "Resposta do segundo bot" in history[2]["content"]
