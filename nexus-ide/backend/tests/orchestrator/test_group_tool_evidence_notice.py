"""Group conversation must not present model prose as tool evidence."""

import json

import httpx
import pytest

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app
from backend.orchestrator.routes import bot_groups as routes


@pytest.mark.asyncio
async def test_false_tool_claim_has_notice_in_stream_and_persisted_history(monkeypatch):
    class Provider:
        async def chat_stream(self, model, messages):
            yield "Corri os testes e passaram.\n[OBJETIVO_CONCLUIDO]"

    async def resolve(selected, client):
        return Provider(), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    token = create_access_token({"sub": "evidence-owner", "email": "evidence@test.local"})
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        ids = []
        for name in ("Um", "Dois"):
            response = await client.post("/api/bots", headers=headers, json={
                "name": name, "provider": "lmstudio", "model": "test-model",
            })
            assert response.status_code == 201
            ids.append(response.json()["id"])
        group = await client.post("/api/bot-groups", headers=headers, json={
            "name": "Evidência", "bot_ids": ids,
        })
        group_id = group.json()["id"]
        response = await client.post(f"/api/bot-groups/{group_id}/messages", headers=headers, json={
            "message": "Corre os testes",
        })
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        tokens = [frame["content"] for frame in frames if frame["type"] == "token"]
        assert "nenhuma leitura de ficheiros, teste" in tokens[0]
        assert "Corri os testes" in "".join(tokens)
        history = (await client.get(f"/api/bot-groups/{group_id}/messages", headers=headers)).json()["messages"]
        assert history[-1]["content"] == "".join(tokens[len(tokens)//2:])
