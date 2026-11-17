"""Group turns use durable sessions separate from private bot chats."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.orchestrator.main import app
from backend.persistence import bot_groups, db
from backend.tests.orchestrator.test_group_primary_bridge import (
    ScriptedProvider,
    _auth,
    _configure,
    _create_bot,
    _frames,
)


@pytest.mark.asyncio
async def test_group_and_private_sessions_are_isolated_and_survive_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    owner = "group-isolation-owner"
    provider = ScriptedProvider()
    _configure(monkeypatch, provider, tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://nexus.local",
        headers=_auth(owner),
    ) as client:
        bot = await _create_bot(client, name="Especialista", model="model-private")
        other_bot = await _create_bot(client, name="Outro", model="model-other")
        private_id = bot["session_id"]
        db.add_message(private_id, "user", "SEGREDO-DO-CHAT-PRIVADO")
        groups = []
        for name in ("Alfa", "Beta"):
            result = await client.post(
                "/api/bot-groups",
                json={"name": name, "bot_ids": [bot["id"], other_bot["id"]]},
            )
            assert result.status_code == 201, result.text
            groups.append(result.json()["id"])

        async def send(group_id: str, text: str) -> str:
            start = len(provider.calls)
            response = await client.post(
                f"/api/bot-groups/{group_id}/messages", json={"message": f"@Especialista {text}"}
            )
            assert response.status_code == 200, response.text
            assert _frames(response)[-1]["status"] == "completed", response.text
            calls = provider.calls[start:]
            assert calls
            return json.dumps([call["messages"] for call in calls], ensure_ascii=False)

        alpha_prompt = await send(groups[0], "MARCADOR-DO-GRUPO-ALFA")
        beta_prompt = await send(groups[1], "MARCADOR-DO-GRUPO-BETA")
        alpha_again_prompt = await send(groups[0], "Continua a conversa do grupo")
        assert "SEGREDO-DO-CHAT-PRIVADO" not in alpha_prompt
        assert "SEGREDO-DO-CHAT-PRIVADO" not in beta_prompt
        assert "MARCADOR-DO-GRUPO-ALFA" not in beta_prompt
        assert "MARCADOR-DO-GRUPO-BETA" not in alpha_again_prompt
        assert "MARCADOR-DO-GRUPO-ALFA" in alpha_again_prompt

        alpha_id = bot_groups.participant_session(owner, groups[0], bot["id"])
        beta_id = bot_groups.participant_session(owner, groups[1], bot["id"])
        assert len({private_id, alpha_id, beta_id}) == 3
        private_text = json.dumps(db.get_messages(private_id), ensure_ascii=False)
        assert "SEGREDO-DO-CHAT-PRIVADO" in private_text
        assert "MARCADOR-DO-GRUPO-ALFA" not in private_text
        with pytest.raises(ValueError):
            bot_groups.participant_session("different-owner", groups[0], bot["id"])
        assert alpha_id not in {row["id"] for row in db.list_sessions(user_id=owner)}

        db.close_pool()
        db.init_db()
        assert bot_groups.participant_session(owner, groups[0], bot["id"]) == alpha_id
        assert db.get_messages(alpha_id)
