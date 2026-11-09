"""Opt-in real-model coding tasks with an independent behavioural oracle.

Run from nexus-ide with NEXUS_REAL_TASK_URL and NEXUS_REAL_TASK_MODEL set.
The endpoint is restricted to loopback. This exercises the primary chat
runtime in process, not the HTTP endpoint, browser, restart or production DB.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

CASES = {
    "pagination": {
        "source": "def page(items, number, size):\n    start = number * size\n    return items[start:start + size]\n",
        "prompt": "Corrige a paginação em app/pagination.py: a primeira página tem número 1. Executa os testes existentes e comunica o resultado real. Preserva todo o trabalho já existente.",
        "oracle": "assert m.page(list(range(10)), 1, 3) == [0,1,2]; assert m.page(list(range(10)), 2, 3) == [3,4,5]; assert m.page([1], 2, 3) == []",
    },
    "discount": {
        "source": "def total(price, percent):\n    return price + price * percent / 100\n",
        "prompt": "Corrige o desconto em app/pricing.py: percent representa a percentagem a subtrair. Executa os testes existentes e comunica o resultado real. Preserva todo o trabalho já existente.",
        "oracle": "assert m.total(100, 20) == 80; assert m.total(100, 0) == 100; assert m.total(50, 100) == 0",
    },
}

# An optional third run asks the agent to encounter the known failing test
# before fixing it. It is kept separate from the two comparison scenarios.
if os.environ.get('NEXUS_REAL_TASK_RECOVERY') == '1':
    CASES['recovery'] = {
        **CASES['discount'],
        'prompt': ('Executa primeiro os testes existentes para observar a falha. '
                   'Depois corrige o desconto em app/pricing.py: percent representa a '
                   'percentagem a subtrair. Volta a executar os testes e comunica o '
                   'resultado real. Preserva todo o trabalho já existente.'),
    }


def snapshot(project: Path) -> dict[str, str]:
    return {p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in project.rglob('*') if p.is_file() and '__pycache__' not in p.parts
            and '.pytest_cache' not in p.parts}


def verify(project: Path, target: str, oracle: str) -> dict:
    # The oracle is kept outside the agent's project and imports the actual result.
    program = ("import importlib.util,sys; "
               "s=importlib.util.spec_from_file_location('subject',sys.argv[1]); "
               "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); " + oracle)
    try:
        result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(project / target)],
                                capture_output=True, text=True, timeout=15, cwd=project)
        return {"passed": result.returncode == 0, "returncode": result.returncode,
                "output": (result.stdout + result.stderr)[-4000:]}
    except subprocess.TimeoutExpired:
        return {"passed": False, "returncode": None, "output": "oracle timeout"}


@pytest.mark.parametrize(('case_name', 'correct'), [
    ('pagination', 'def page(items, number, size):\n    start = (number - 1) * size\n    return items[start:start + size]\n'),
    ('discount', 'def total(price, percent):\n    return price - price * percent / 100\n'),
])
def test_oracle_detects_bug_and_fix(case_name: str, correct: str, tmp_path: Path) -> None:
    target = tmp_path / 'subject.py'
    target.write_text(CASES[case_name]['source'], encoding='utf-8')
    assert not verify(tmp_path, target.name, CASES[case_name]['oracle'])['passed']
    target.write_text(correct, encoding='utf-8')
    assert verify(tmp_path, target.name, CASES[case_name]['oracle'])['passed']


@pytest.mark.parametrize('case_name', list(CASES))
@pytest.mark.asyncio
async def test_real_task(case_name: str, tmp_path: Path, monkeypatch) -> None:
    endpoint = os.environ.get('NEXUS_REAL_TASK_URL', '')
    model = os.environ.get('NEXUS_REAL_TASK_MODEL', '')
    if not endpoint or not model:
        pytest.skip('set NEXUS_REAL_TASK_URL and NEXUS_REAL_TASK_MODEL to run real tasks')
    assert urlparse(endpoint).hostname in {'localhost', '127.0.0.1', '::1'}
    artifact_root = Path(os.environ['NEXUS_REAL_TASK_ARTIFACTS']).resolve()
    assert artifact_root.is_dir(), 'create the artifact directory first'
    artifact = artifact_root / case_name
    artifact.mkdir(exist_ok=False)
    case = CASES[case_name]
    project = tmp_path / 'project'
    (project / 'app').mkdir(parents=True)
    (project / 'tests').mkdir()
    name = 'pagination' if case_name == 'pagination' else 'pricing'
    target = f'app/{name}.py'
    (project / target).write_text(case['source'], encoding='utf-8')
    (project / 'WORK_IN_PROGRESS.txt').write_text('Trabalho existente: manter intacto.\n', encoding='utf-8')
    visible_assert = ('assert page([0, 1, 2, 3], 1, 2) == [0, 1]' if case_name == 'pagination'
                      else 'assert total(100, 20) == 80')
    function = 'page' if case_name == 'pagination' else 'total'
    (project / 'tests' / 'test_task.py').write_text(
        f'from app.{name} import {function}\n\ndef test_regression():\n    {visible_assert}\n', encoding='utf-8')
    before = snapshot(project)
    baseline = verify(project, target, case['oracle'])
    assert not baseline['passed'], 'invalid scenario: the initial bug must fail the oracle'

    from backend.agents.base import AgentBase
    from backend.core import conversation_log, workspace_backup
    from backend.knowledge.memory import EmbeddingService
    from backend.llm.lmstudio_provider import LMStudioProvider
    from backend.models.api import ChatRequest
    from backend.orchestrator import advanced_modes
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.registry import get_registry
    from backend.orchestrator.routes import chat_primary
    from backend.runtime import events as runtime_events

    monkeypatch.setenv('NEXUS_EVENT_JOURNAL', '1')
    monkeypatch.setenv('NEXUS_ADVISOR_ENABLED', '0')
    monkeypatch.setenv('NEXUS_EXPERIENCE_OFF', '1')
    monkeypatch.setenv('NEXUS_REASONING_VISIBILITY', 'off')
    monkeypatch.setenv('NEXUS_PRIMARY_MAX_CYCLES', '8')
    monkeypatch.setenv('OPENROUTER_API_KEY', '')
    monkeypatch.setattr(runtime_events, 'run_event_journal_path', lambda run_id: artifact / f'{run_id}.jsonl')
    monkeypatch.setattr(conversation_log, '_DEFAULT_LOG_DIR', tmp_path / 'logs')
    # This opt-in benchmark runs only on disposable fixtures. Record the full
    # tool response and the exact rendering appended to the model context;
    # normal activity events intentionally omit details for failed tools.
    render_result = AgentBase._render_tool_result_for_context.__func__
    def capture_result(cls, tool_name, result):
        rendered = render_result(cls, tool_name, result)
        with (artifact / 'tool_context.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'tool': tool_name, 'result': result, 'rendered': rendered},
                                    ensure_ascii=False, default=str) + '\n')
        return rendered
    monkeypatch.setattr(AgentBase, '_render_tool_result_for_context', classmethod(capture_result))
    async def isolated_backup_dir(_path):
        return artifact / 'backups'
    monkeypatch.setattr(workspace_backup, '_backup_dir_for', isolated_backup_dir)
    monkeypatch.setattr(chat_primary, 'run_integration_enabled', lambda: False)
    allowed = ('read_file', 'read_multiple_files', 'list_dir', 'search_in_files', 'write_file', 'run_tests')
    monkeypatch.setattr(chat_primary, '_tool_policy_context', lambda *_a, **_kw: {'_allowed_tools': allowed})

    async def local_embedding(self, text):
        return self._fallback_embed(text)
    monkeypatch.setattr(EmbeddingService, 'embed', local_embedding)

    class NoModes:
        def build_active_execution_profile(self): return {}
        def prepare_active_execution_profile(self, _message): return {}
    monkeypatch.setattr(advanced_modes, 'get_orchestrator', lambda: NoModes())
    provider = LMStudioProvider(base_url=endpoint, api_key='', default_model=model, fast_model=model, coder_model=model)
    request = ChatRequest(message=case['prompt'], session_id=f'benchmark-{case_name}', mode='assisted',
                          project_path=str(project), provider='lmstudio', model=model,
                          model_is_concrete=True, autonomous=True)
    decision = chat_primary.plan_turn(case['prompt'], 'assisted', str(project))
    frames = []
    started = time.monotonic()
    error = None
    try:
        async with asyncio.timeout(float(os.environ.get('NEXUS_REAL_TASK_TIMEOUT', '180'))):
            async for raw in chat_primary.run_primary_chat(request, provider, get_registry(), ContextStore(),
                                                           decision=decision, owner_id='benchmark'):
                if raw.startswith('data: '):
                    frames.append(json.loads(raw[6:].strip()))
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    finally:
        await provider.aclose()
        after = snapshot(project)
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        new_nexus_files = [p for p in changed if p.startswith('.nexus/') and p not in before]
        actual = verify(project, target, case['oracle'])
        report = {'scenario': case_name, 'model_requested': model, 'endpoint': endpoint,
                  'duration_seconds': round(time.monotonic() - started, 2), 'baseline': baseline,
                  'oracle': actual, 'changed_files': changed,
                  'new_nexus_files': new_nexus_files,
                  'unexpected_changes': [p for p in changed if p != target and p not in new_nexus_files],
                  'tool_calls': [f.get('tool_name') for f in frames if f.get('type') == 'tool_call'],
                  'response': ''.join(f.get('content') or '' for f in frames if f.get('type') == 'token'),
                  'error': error, 'cost': None, 'cost_status': 'not measured',
                  'scope': 'in-process primary runtime; provider on loopback; no HTTP or browser'}
        (artifact / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        (artifact / 'frames.json').write_text(json.dumps(frames, indent=2, ensure_ascii=False), encoding='utf-8')
        if (project / target).is_file():
            (artifact / 'result.py.txt').write_text((project / target).read_text(encoding='utf-8'), encoding='utf-8')
    assert error is None, error
    assert actual['passed'], actual['output']
    assert not report['unexpected_changes'], report['unexpected_changes']
    assert target in changed, 'target file was not changed'
