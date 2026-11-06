"""Regression coverage for independent group participants and pinned models."""

import pytest

from backend.llm.factory import ResilientLLMProvider
from backend.orchestrator.routes.bot_groups import _context


def test_group_context_excludes_other_bots_but_keeps_user_and_own_history():
    history = [
        {"role": "user", "content": "Analisa o sistema", "bot_name": None},
        {"role": "assistant", "content": "Segurança é o tema", "bot_name": "SHADE", "bot_id": "s"},
        {"role": "assistant", "content": "O meu diagnóstico", "bot_name": "FORGE", "bot_id": "f"},
    ]
    context = _context(history, {"id": "f", "name": "FORGE", "description": "código", "instructions": ""})
    assert "Analisa o sistema" in context[-1]["content"]
    assert "O meu diagnóstico" in context[-1]["content"]
    assert "Segurança é o tema" not in context[-1]["content"]


@pytest.mark.asyncio
async def test_selected_provider_does_not_reuse_its_old_fallback_model(monkeypatch):
    class Provider:
        fallback_model = "old-fallback"

        async def chat_stream(self, model, messages):
            yield model

    client = ResilientLLMProvider(Provider(), [])
    monkeypatch.setattr(client, "_cost_check", lambda *args: None)
    monkeypatch.setattr(client, "_cost_record", lambda *args: None)
    assert [chunk async for chunk in client.chat_stream("chosen-model", [])] == ["chosen-model"]
