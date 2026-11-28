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
from backend.persistence.db import close_pool, init_db


def auth(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': user, 'email': user + '@test.local'})}"}


@pytest.mark.asyncio
@pytest.mark.parametrize('fail', ['', 'first', 'second'])
async def test_run_survives_request_and_scopes_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fail: str) -> None:
    (tmp_path / 'example.txt').write_text('real evidence', encoding='utf-8')
    entered, release = asyncio.Event(), asyncio.Event()
    prompts: list[list[dict[str, str]]] = []

    class Provider:
        async def chat_stream(self, model: str, messages: list[dict[str, str]], **_options: Any):
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


@pytest.mark.asyncio
async def test_resume_keeps_completed_bots_and_original_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    source = tmp_path / "module.txt"
    source.write_text("evidência original", encoding="utf-8")
    reviews_running = asyncio.Event()
    allow_resume = asyncio.Event()
    calls: list[str] = []
    resumed = False

    class Provider:
        async def chat_stream(
            self, model: str, messages: list[dict[str, str]], *, options: dict, run_id: str,
        ):
            assert options["max_tokens"] == routes._OUTPUT_TOKENS
            assert run_id
            calls.append(model)
            assert "evidência original" in messages[1]["content"]
            assert "ficheiro alterado" not in messages[1]["content"]
            if model == "lead":
                yield "diagnóstico"
                return
            assert "diagnóstico" in messages[1]["content"]
            assert f"instruções {model}" in messages[0]["content"]
            if not resumed:
                if len(calls) == 4:
                    reviews_running.set()
                await reviews_running.wait()
                if model != "ready":
                    await asyncio.Event().wait()
            else:
                await allow_resume.wait()
            yield f"revisão {model}"

    async def resolve(_selection: Any, _client: Any):
        return Provider(), None

    monkeypatch.setattr(routes, "_request_provider_client", resolve)
    monkeypatch.setattr(routes, "_resolve_project_root", lambda *_args: tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=auth("alice"),
    ) as client:
        ids = []
        for model in ("lead", "ready", "pending-a", "pending-b"):
            response = await client.post("/api/bots", json={
                "name": model, "provider": "lmstudio", "model": model, "instructions": f"instruções {model}",
            })
            assert response.status_code == 201
            ids.append(response.json()["id"])
        group = (await client.post("/api/bot-groups", json={"name": "Group", "bot_ids": ids})).json()["id"]
        endpoint = f"/api/bot-groups/{group}/runs"
        request = {"message": "Revê o módulo", "file_path": source.name}
        invalid = await client.post(endpoint, json={**request, "file_path": ".env"})
        assert invalid.status_code == 400
        response = await client.post(endpoint, json=request)
        assert response.status_code == 202, response.text
        run_url = f"{endpoint}/{response.json()['id']}"
        await asyncio.wait_for(reviews_running.wait(), 4)
        assert (await client.post(endpoint, json=request)).status_code == 409
        assert (await client.post(f"{run_url}/interrupt", headers=auth("bob"))).status_code == 404
        assert (await client.post(f"{run_url}/interrupt")).status_code == 200
        close_pool()
        init_db()
        run = (await client.get(run_url)).json()
        assert run["can_resume"] is True
        assert [task["status"] for task in run["tasks"]] == [
            "completed", "completed", "interrupted", "interrupted",
        ]
        assert "instructions" not in run["tasks"][0]

        source.write_text("ficheiro alterado", encoding="utf-8")
        changed = await client.patch(f"/api/bots/{ids[2]}", json={"instructions": "novas instruções"})
        assert changed.status_code == 200
        assert (await client.post(f"{run_url}/resume", headers=auth("bob"))).status_code == 404
        resumed = True
        assert (await client.post(f"{run_url}/resume")).status_code == 202
        assert (await client.post(f"{run_url}/resume")).status_code == 409
        allow_resume.set()
        for _ in range(100):
            run = (await client.get(run_url)).json()
            if run["status"] == "completed":
                break
            await asyncio.sleep(.01)
        assert run["status"] == "completed", run
        assert [task["result"] for task in run["tasks"]] == [
            "diagnóstico", "revisão ready", "revisão pending-a", "revisão pending-b",
        ]
        assert len([record for record in run["records"] if record["kind"] == "tool_call"]) == 1
        read = next(record for record in run["records"] if record["kind"] == "tool_result")
        assert len(read["payload"]["sha256"]) == 64
        assert calls.count("lead") == calls.count("ready") == 1
        summary = (await client.get(endpoint, params={"include_evidence": "false"})).json()["runs"][0]
        assert summary["records"] == []
        assert all(task["result"] is None for task in summary["tasks"])
