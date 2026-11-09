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
            assert handoff['trust'] == 'analysis_unverified'
            assert handoff['previous_analyses'] == [
                {'task_id': run['tasks'][0]['id'], 'bot_id': ids[0], 'bot_name': 'first',
                 'analysis': 'analysis'},
            ]
            assert 'não verificadas' in prompts[1][1]['content']
            if fail == 'second':
                assert [task['status'] for task in run['tasks']] == ['completed', 'failed']
            else:
                assert [task['result'] for task in run['tasks']] == ['analysis', 'review']


@pytest.mark.asyncio
async def test_run_includes_every_member_and_hands_all_analyses_forward(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / 'example.txt').write_text('real evidence', encoding='utf-8')
    prompts: list[list[dict[str, str]]] = []

    class Provider:
        async def chat_stream(self, model: str, messages: list[dict[str, str]]):
            prompts.append(messages)
            yield f"analise-{model}"

    async def resolve(_selection: Any, _client: Any):
        return Provider(), None

    monkeypatch.setattr(routes, '_request_provider_client', resolve)
    monkeypatch.setattr(routes, '_resolve_project_root', lambda *_args: tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=auth('carol')) as client:
        first = (await client.post('/api/bots', json={'name': 'primeiro', 'provider': 'lmstudio', 'model': 'M1'})).json()
        second = (await client.post('/api/bots', json={'name': 'segundo', 'provider': 'lmstudio', 'model': 'M2'})).json()
        third = (await client.post('/api/bots', json={'name': 'revisor', 'provider': 'lmstudio', 'model': 'M3'})).json()
        unconfigured = (await client.post('/api/bots', json={'name': 'sem modelo', 'provider': 'lmstudio'})).json()
        group = (await client.post('/api/bot-groups', json={'name': 'trio', 'bot_ids': [first['id'], second['id'], third['id'], unconfigured['id']]})).json()['id']
        # A run refuses to start until EVERY member has provider + model.
        assert (await client.post(f'/api/bot-groups/{group}/runs', json={'message': 'x', 'file_path': 'example.txt'})).status_code == 400
        configured = await client.patch(f"/api/bots/{unconfigured['id']}", json={'model': 'M4'})
        assert configured.status_code == 200, configured.text
        response = await client.post(f'/api/bot-groups/{group}/runs', json={'message': 'avaliar', 'file_path': 'example.txt'})
        assert response.status_code == 202, response.text
        run_id = response.json()['id']
        for _ in range(200):
            run = bot_group_runs.get('carol', group, run_id)
            if run['status'] in ('completed', 'failed', 'interrupted'):
                break
            await asyncio.sleep(.01)
        assert run['status'] == 'completed'
        assert [task['status'] for task in run['tasks']] == ['completed', 'completed', 'completed', 'completed']
        assert [task['result'] for task in run['tasks']] == ['analise-M1', 'analise-M2', 'analise-M3', 'analise-M4']
        assert len(prompts) == 4
        final_prompt = prompts[3][1]['content']
        assert 'analise-M1' in final_prompt
        assert 'analise-M2' in final_prompt
        assert 'analise-M3' in final_prompt
        # The last participant is asked to review the earlier analyses.
        assert 'revê criticamente' in prompts[3][0]['content']


@pytest.mark.asyncio
async def test_run_cancel_stops_in_flight_provider_and_midway_tasks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / 'example.txt').write_text('real evidence', encoding='utf-8')
    entered = asyncio.Event()
    release = asyncio.Event()

    class Provider:
        async def chat_stream(self, model: str, _messages: list[dict[str, str]]):
            if model == 'L1':
                entered.set()
                await release.wait()
            yield 'feito'

    async def resolve(_selection: Any, _client: Any):
        return Provider(), None

    monkeypatch.setattr(routes, '_request_provider_client', resolve)
    monkeypatch.setattr(routes, '_resolve_project_root', lambda *_args: tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=auth('dale')) as client:
        ids = [(await client.post('/api/bots', json={'name': f'bot-{model}', 'provider': 'lmstudio', 'model': model})).json()['id'] for model in ('L1', 'L2', 'L3')]
        group = (await client.post('/api/bot-groups', json={'name': 'cancelar', 'bot_ids': ids})).json()['id']
        response = await client.post(f'/api/bot-groups/{group}/runs', json={'message': 'trabalharem', 'file_path': 'example.txt'})
        assert response.status_code == 202, response.text
        run_id = response.json()['id']
        await asyncio.wait_for(entered.wait(), 3)
        cancelled = await client.post(f'/api/bot-groups/{group}/runs/{run_id}/cancel')
        assert cancelled.status_code == 202, cancelled.text
        assert cancelled.json() == {'run_id': run_id, 'status': 'cancelling', 'cancelled': True}
        # Release the blocked provider so the CancelledError is observed in the executor.
        release.set()
        for _ in range(200):
            run = bot_group_runs.get('dale', group, run_id)
            if run['status'] == 'cancelled':
                break
            await asyncio.sleep(.01)
        assert run['status'] == 'cancelled'
        assert [task['status'] for task in run['tasks']] == ['interrupted', 'interrupted', 'interrupted']
        assert run['tasks'][0]['error'] == 'Execução interrompida a pedido do utilizador.'
        # A finished run cannot be cancelled again: the endpoint reports the truth.
        after = await client.post(f'/api/bot-groups/{group}/runs/{run_id}/cancel')
        assert after.status_code == 202
        payload = after.json()
        assert payload['cancelled'] is False
        assert payload['status'] == 'cancelled'


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
