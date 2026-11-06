"""Durable group execution, evidence handoff and owner isolation."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app
from backend.orchestrator.routes import bot_groups as routes
from backend.persistence import bot_group_runs


def auth(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': user, 'email': user + '@test.local'})}"}


@pytest.mark.asyncio
@pytest.mark.parametrize('fail', ['', 'first', 'second'])
async def test_run_survives_request_and_scopes_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fail: str) -> None:
    (tmp_path / 'example.txt').write_text('real evidence', encoding='utf-8')
    entered, release = asyncio.Event(), asyncio.Event()
    prompts: list[list[dict[str, str]]] = []

    class Provider:
        async def chat_stream(self, model: str, messages: list[dict[str, str]]):
            prompts.append(messages)
            if model == 'first':
                entered.set()
                await release.wait()
            if fail == model:
                raise RuntimeError('provider down')
            yield 'analysis' if model == 'first' else 'review'

    async def resolve(_selection: Any, _client: Any):
        return Provider(), None

    monkeypatch.setattr(routes, '_request_provider_client', resolve)
    monkeypatch.setattr(routes, '_resolve_project_root', lambda *_args: tmp_path)
    # Exercise the real reader with the same project confinement used in production.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=auth('alice')) as client:
        ids = [(await client.post('/api/bots', json={'name': model, 'provider': 'lmstudio', 'model': model})).json()['id'] for model in ('first', 'second')]
        group = (await client.post('/api/bot-groups', json={'name': 'test', 'bot_ids': ids})).json()['id']
        assert (await client.post(f'/api/bot-groups/{group}/runs', json={'message': 'inspect', 'file_path': '../outside'})).status_code == 400
        response = await client.post(f'/api/bot-groups/{group}/runs', json={'message': 'inspect', 'file_path': 'example.txt'})
        assert response.status_code == 202, response.text
        await asyncio.wait_for(entered.wait(), 3)
        run_id = response.json()['id']
        assert (await client.get(f'/api/bot-groups/{group}/runs', headers=auth('bob'))).status_code == 404
        # The initiating HTTP request has already finished while the worker is blocked.
        assert bot_group_runs.get('alice', group, run_id)['status'] == 'running'
        release.set()
        for _ in range(100):
            run = bot_group_runs.get('alice', group, run_id)
            if run['status'] in ('completed', 'failed'):
                break
            await asyncio.sleep(.01)
        assert run['status'] == ('failed' if fail else 'completed')
        assert run['records'][1]['payload']['content'] == 'real evidence'
        assert run['records'][1]['payload']['call_id'] == run['records'][0]['id']
        if fail == 'first':
            assert [task['status'] for task in run['tasks']] == ['failed', 'skipped']
        else:
            handoff = run['records'][2]['payload']
            assert handoff['read_result_id'] == run['records'][1]['id']
            assert handoff['analysis'] == 'analysis'
            assert 'não verificada' in prompts[1][1]['content']
            if fail == 'second':
                assert [task['status'] for task in run['tasks']] == ['completed', 'failed']
            else:
                assert [task['result'] for task in run['tasks']] == ['analysis', 'review']


def test_restart_marks_unfinished_without_replaying() -> None:
    from backend.persistence import bot_groups, bots
    first = bots.create_bot('alice', {'name': 'A', 'description': '', 'instructions': '', 'provider': 'lmstudio', 'model': 'x'})
    second = bots.create_bot('alice', {'name': 'B', 'description': '', 'instructions': '', 'provider': 'lmstudio', 'model': 'x'})
    group = bot_groups.create_group('alice', 'G', [first['id'], second['id']])
    run_id = bot_group_runs.create('alice', group['id'], 'request', '.', 'a', [first, second])
    bot_group_runs.set_run(run_id, 'running')
    bot_group_runs.interrupt_unfinished()
    run = bot_group_runs.get('alice', group['id'], run_id)
    assert run['status'] == 'interrupted'
    assert [task['status'] for task in run['tasks']] == ['interrupted', 'interrupted']
    assert run['records'] == []
