"""Cenários end-to-end: os mesmos prompts da auditoria, agora medidos.

Cada cenário imprime ANTES (o que a auditoria de 2026-08-16 observou) e
DEPOIS (o que a stack faz agora), com a evidência recolhida do stream SSE real.

Executar:  python -m backend.tests.e2e_audit_scenarios
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from backend.tests.e2e_audit_harness import (
    PROVIDER,
    build_client,
    sse,
    visible_text,
)

RESULTS: list[dict] = []


def record(name: str, before: str, after: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(
        {"cenario": name, "antes": before, "depois": after, "ok": ok, "detalhe": detail}
    )
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}")
    print(f"       antes : {before}")
    print(f"       depois: {after}")
    if detail:
        print(f"       nota  : {detail}")


def make_project(root: Path) -> Path:
    project = root / "taskflow"
    (project / "app" / "repos").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "app" / "repos" / "task_repo.py").write_text(
        "class TaskRepo:\n"
        "    def list_page(self, page: int, size: int):\n"
        "        offset = page * size  # bug: deveria ser (page - 1) * size\n"
        "        return self._items[offset : offset + size]\n",
        encoding="utf-8",
    )
    # Um ficheiro hostil: menciona os marcadores do protocolo interno.
    (project / "probe_thinking.py").write_text(
        'A = 1\nMARK = "<thinking>"\nTOOL = "<tool_call>"\nB = 2\n', encoding="utf-8"
    )
    return project


def scenario_p1_answer_reaches_user(client, project: Path) -> None:
    """P1 — a resposta real do modelo tem de chegar ao utilizador."""
    PROVIDER.load(
        [
            '```tool\n{"tool": "read_file", "arguments": '
            '{"path": "app/repos/task_repo.py"}}\n```',
            "RESPOSTA-REAL: o offset em list_page é page * size em vez de "
            "(page - 1) * size, por isso a página 1 devolve os itens 11-20.",
            "AUDIT: a auditoria nao encontrou mais nada a fazer.",
        ]
    )
    started = time.time()
    response = client.post(
        "/api/chat",
        json={
            "message": "Ha algum bug na paginacao do TaskRepo? Verifica no codigo.",
            "session_id": "e2e-p1",
            "project_path": str(project),
            "autonomous": True,
        },
    )
    elapsed = time.time() - started
    events = sse(response.content)
    text = visible_text(events)
    ok = "RESPOSTA-REAL" in text and "AUDIT:" not in text
    record(
        "P1 resposta do modelo entregue",
        "visível: 'AUDIT: a auditoria nao encontrou mais nada a fazer.' (resposta real perdida)",
        f"visível: {text.strip()[:90]!r}",
        ok,
        f"chamadas ao modelo: {PROVIDER.calls} | {elapsed:.2f}s",
    )

    history = client.get("/api/sessions/e2e-p1/history")
    stored = ""
    if history.status_code == 200:
        messages = history.json().get("messages", [])
        stored = next(
            (m["content"] for m in messages if m["role"] == "assistant"), ""
        )
    record(
        "P1 memória guarda a resposta certa",
        "histórico guardava o texto da auditoria",
        f"histórico guarda: {stored.strip()[:80]!r}",
        "RESPOSTA-REAL" in stored,
    )


def scenario_p1_latency(client, project: Path) -> None:
    """P1 — o custo: uma pergunta de leitura não pode pagar duas inferências."""
    PROVIDER.load(
        [
            '```tool\n{"tool": "read_file", "arguments": '
            '{"path": "app/repos/task_repo.py"}}\n```',
            "RESPOSTA-UNICA: a paginação está errada em list_page.",
            "AUDIT-NAO-DEVIA-ACONTECER",
        ]
    )
    client.post(
        "/api/chat",
        json={
            "message": "Explica o que faz list_page.",
            "session_id": "e2e-p1-lat",
            "project_path": str(project),
            "autonomous": True,
        },
    )
    record(
        "P1 custo por turno (pergunta de leitura)",
        "2 inferências por turno (41s medidos vs 21s sem auditoria)",
        f"{PROVIDER.calls} inferência(s) neste turno (1 tool call + 1 resposta)",
        PROVIDER.calls == 2,
    )


def scenario_p2_hostile_file(client, project: Path) -> None:
    """P2 — um ficheiro com <thinking>/<tool_call> não pode partir o chat."""
    PROVIDER.load(
        [
            '```tool\n{"tool": "read_file", "arguments": {"path": "probe_thinking.py"}}\n```',
            "RESPOSTA-APOS-LEITURA: o ficheiro define A, MARK, TOOL e B.",
        ]
    )
    response = client.post(
        "/api/chat",
        json={
            "message": "le probe_thinking.py",
            "session_id": "e2e-p2",
            "project_path": str(project),
            "autonomous": True,
        },
    )
    events = sse(response.content)
    text = visible_text(events)
    kinds = [e.get("type") for e in events]
    leaked = "<event>" in text or "tool_result|" in text
    record(
        "P2 ficheiro com marcadores do protocolo",
        "chat mostrava '<event>tool_result|read_file|{...' em vez da resposta",
        f"texto limpo: {not leaked} | eventos: {sorted(set(kinds))}",
        not leaked,
    )


def scenario_p3_false_green(client, project: Path) -> None:
    """P3 — verificação nunca verde sem testes executados."""
    import asyncio

    from backend.orchestrator.routes.chat_primary import _verify
    from backend.runtime.primary import PrimaryTurn, VerificationRequest

    async def fake_execute_tool(*args, **kwargs):
        return {
            "ok": True,
            "result": {
                "status": "not_run",
                "ran": False,
                "executed": False,
                "passed": 0,
                "failed": 0,
                "error": "pytest não arrancou: No module named pytest",
            },
        }

    import backend.tools.registry as registry_mod

    original = registry_mod.execute_tool
    registry_mod.execute_tool = fake_execute_tool
    try:
        result = asyncio.run(
            _verify(
                VerificationRequest(
                    turn=PrimaryTurn(query="corrige a paginação"),
                    changed_files=("app/repos/task_repo.py",),
                ),
                session_id="e2e-p3",
                project_path=str(project),
            )
        )
    finally:
        registry_mod.execute_tool = original

    record(
        "P3 verificação sem pytest",
        "evento test_result | ok=True | '0 passaram, 0 falharam'",
        f"ok={result.ok} | {result.summary[:70]!r}",
        result.ok is False and "NÃO VERIFICADO" in result.summary,
    )


def scenario_p4_no_project(client) -> None:
    """P4 — sem projeto selecionado, o agente não pode escrever no repo do NEXUS."""
    PROVIDER.load(["Preciso que selecione um projeto primeiro."])
    response = client.post(
        "/api/chat",
        json={
            "message": "O que faz app/repos/task_repo.py? Le o ficheiro.",
            "session_id": "e2e-p4",
            "project_path": "",
            "autonomous": True,
        },
    )
    prompt = PROVIDER.last_prompt_text().lower()
    says_no_project = "sem projeto selecionado" in prompt
    # A regressão original: o PROJECT STATE era construído a partir do próprio
    # repositório do NEXUS (README.md, backend/, frontend/ ...) sem que
    # ninguém percebesse.
    points_at_nexus_repo = "nexus-ide" in prompt or "arquitetura do nexus" in prompt
    record(
        "P4 sem projeto selecionado",
        "PROJECT STATE era o repo do NEXUS ('.' resolvido contra o CWD do backend)",
        f"contexto diz 'sem projeto selecionado': {says_no_project} | "
        f"aponta para o repo do NEXUS: {points_at_nexus_repo}",
        says_no_project and not points_at_nexus_repo,
        "a UI já não envia '.'; o backend avisa quando recorre à raiz",
    )


def scenario_p5_context_budget(client, project: Path) -> None:
    """P5 — um read_file grande não pode encher a janela de contexto."""
    big = project / "big_module.py"
    big.write_text("# linha de código\n" * 12000, encoding="utf-8")
    PROVIDER.load(
        [
            '```tool\n{"tool": "read_file", "arguments": {"path": "big_module.py"}}\n```',
            "Li o ficheiro: são 12000 linhas repetidas.",
        ]
    )
    client.post(
        "/api/chat",
        json={
            "message": "le big_module.py e resume",
            "session_id": "e2e-p5",
            "project_path": str(project),
            "autonomous": True,
        },
    )
    sizes = PROVIDER.prompt_chars()
    growth = max(sizes) - min(sizes) if sizes else 0
    record(
        "P5 orçamento de contexto",
        "+45k chars de UMA ferramenta; 203k chars na 3ª chamada",
        f"maior prompt: {max(sizes) if sizes else 0} chars | crescimento: {growth}",
        bool(sizes) and max(sizes) < 60000,
        f"ficheiro lido: {big.stat().st_size} chars",
    )


def scenario_p8_false_claims(client, project: Path) -> None:
    """P8 — afirmações falsas do modelo têm de ser contestadas."""
    PROVIDER.load(
        [
            "Analisei todos os ficheiros do projeto, corri a suite de testes "
            "(4 passed) e confirmei que não há bugs.",
        ]
    )
    response = client.post(
        "/api/chat",
        json={
            "message": "Verifica se ha bugs no projeto e corre os testes.",
            "session_id": "e2e-p8",
            "project_path": str(project),
            "autonomous": True,
        },
    )
    events = sse(response.content)
    text = visible_text(events)
    contested = "não são suportadas pela evidência" in text or any(
        "afirmações não suportadas" in str((e.get("data") or {}).get("label", ""))
        for e in events
    )
    record(
        "P8 afirmações inventadas",
        "'AUDIT: confirmado, tudo verificado.' apesar de 0 passaram/1 falharam",
        f"contestada no output: {contested}",
        contested,
    )


def scenario_p10_spawn(client, project: Path) -> None:
    """P10 — spawn_task não pode dizer 'spawned' a uma delegação negada."""
    PROVIDER.load(
        [
            '```tool\n{"tool": "spawn_task", "arguments": {"name": "analisar-scoring",'
            ' "description": "", "agent": "ANALYZER", "priority": "high"}}\n```',
            "A delegação foi negada; trato eu próprio.",
        ]
    )
    response = client.post(
        "/api/chat",
        json={
            "message": "Delega a analise profunda do modulo de scoring a um sub-agente ANALYZER.",
            "session_id": "e2e-p10",
            "project_path": str(project),
            "autonomous": True,
        },
    )
    events = sse(response.content)
    tool_results = [
        e.get("tool_result")
        for e in events
        if e.get("type") == "tool_result" and e.get("tool_name") == "spawn_task"
    ]
    claimed_spawned = any(
        isinstance(r, dict) and r.get("status") == "spawned" for r in tool_results
    )
    record(
        "P10 delegação negada",
        "tool_result dizia {'status': 'spawned', 'instance_id': ...} para um agente inexistente",
        f"resultados: {[r.get('status') if isinstance(r, dict) else r for r in tool_results]}",
        not claimed_spawned,
    )


def scenario_multiturn_memory(client, project: Path) -> None:
    """Execução longa: 5 turnos seguidos, memória e contexto sob controlo."""
    marks = []
    sizes = []
    for turn in range(1, 6):
        PROVIDER.load([f"RESPOSTA-TURNO-{turn}: analisei o pedido {turn}."])
        response = client.post(
            "/api/chat",
            json={
                "message": f"pergunta {turn} sobre o TaskRepo",
                "session_id": "e2e-long",
                "project_path": str(project),
                "autonomous": True,
            },
        )
        text = visible_text(sse(response.content))
        marks.append(f"RESPOSTA-TURNO-{turn}" in text)
        sizes.extend(PROVIDER.prompt_chars())

    history = client.get("/api/sessions/e2e-long/history")
    messages = history.json().get("messages", []) if history.status_code == 200 else []
    assistant = [m for m in messages if m["role"] == "assistant"]
    correct = sum(1 for m in assistant if "RESPOSTA-TURNO" in m["content"])
    record(
        "Execução longa (5 turnos)",
        "cada turno guardava a auditoria; a resposta certa nunca entrava na memória",
        f"{sum(marks)}/5 turnos entregaram a resposta certa | "
        f"{correct}/{len(assistant)} mensagens corretas no histórico | "
        f"maior prompt: {max(sizes) if sizes else 0} chars",
        all(marks) and correct == len(assistant) and bool(assistant),
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="nexus-e2e-"))
    try:
        project = make_project(tmp)
        with build_client(project) as client:
            scenario_p1_answer_reaches_user(client, project)
            scenario_p1_latency(client, project)
            scenario_p2_hostile_file(client, project)
            scenario_p3_false_green(client, project)
            scenario_p4_no_project(client)
            scenario_p5_context_budget(client, project)
            scenario_p8_false_claims(client, project)
            scenario_p10_spawn(client, project)
            scenario_multiturn_memory(client, project)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for r in RESULTS if r["ok"])
    print(f"\n=== {passed}/{len(RESULTS)} cenários com o comportamento corrigido ===")
    Path("e2e_audit_results.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
