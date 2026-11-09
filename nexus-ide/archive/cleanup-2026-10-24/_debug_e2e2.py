import sys, json, tempfile, os
from pathlib import Path
from backend.tests.e2e_audit_harness import PROVIDER, build_client, sse, visible_text

root = Path(tempfile.mkdtemp())
project = root / "taskflow"
(project / "app" / "repos").mkdir(parents=True)
(project / "app" / "repos" / "task_repo.py").write_text(
    "class TaskRepo:\n"
    "    def list_page(self, page: int, size: int):\n"
    "        offset = page * size  # bug\n"
    "        return self._items[offset : offset + size]\n",
    encoding="utf-8",
)

PROVIDER.load([
    '```tool\n{"name": "read_file", "arguments": {"path": "app/repos/task_repo.py"}}\n```',
    'RESPOSTA-REAL: o offset em list_page e page * size.',
])
client = build_client(root)
r = client.post('/api/chat', json={
    'message': 'Ha algum bug na paginacao do TaskRepo? Verifica no codigo.',
    'session_id': 'e2e-debug',
    'project_path': str(project),
    'autonomous': True,
})
print('STATUS', r.status_code)
print('BODY', r.text[:3000])
print('CALLS', PROVIDER.calls)
print('PROMPT SIZES', [sum(len(str(m.get("content",""))) for m in p) for p in PROVIDER.prompts])