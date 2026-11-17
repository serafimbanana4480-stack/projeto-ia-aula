# PLAN — Closeout NEXUS IDE v3

Programa normativo (§5) de fecho do NEXUS IDE: confirmar a base, medir, corrigir e
fechar com provas. Cada fase tem **exit gate** objetivo; nada avança sem a prova.

- **Raiz git canónica:** `/mnt/c/Users/rodri/Desktop/nexus`
- **Diretório do projeto:** `/mnt/c/Users/rodri/Desktop/nexus/nexus-ide/`
- **Branch de trabalho:** `closeout/nexus-v3` (base `e12c214c232ac8619aa8c52ac46119ea444d0503`)
- **Worktree de baseline:** `/mnt/c/Users/rodri/Desktop/nexus-baseline` (detached HEAD no mesmo SHA)
- **Regra transversal (todas as fases):** NEXUS_FREE_ONLY ON — zero chamadas a
  fornecedores pagos; zero edições a `.env`; zero desativação de *guards*; zero
  `git stash/reset/clean/restore/push/commit de trabalho alheio`.

---

## Ordem e dependências

**A ordem é orientadora.** Dependências inesperadas ou defeitos mais graves reordenam o
plano — e a decisão tem de ficar documentada em **ADR**. É **proibido refactor extenso
sem benefício mensurável**.

Consequência prática para este closeout: as fases estão numeradas pela prioridade do
programa (P0 → P1 → P2), mas se a medição de F0 já tiver exposto um defeito de classe
superior à da fase seguinte (ex.: uma fuga de contexto que atravesse projetos — F5 —
verificada em F1), a fase que trata esse defeito é **antecipada** e a reordenação fica
registada em ADR antes de avançar.

**Estado atual (F0 concluída):** a baseline expôs 34 falhas, das quais uma viola
diretamente o threshold **N3** (fuga de contexto entre sessões concorrentes) e três
afetam o confinamento de projeto. Como N3 é *exit gate* de F5, e o defeito está
observado e reproduzido já em F0, isto **exige uma decisão de reordenação em ADR**
antecipar.o tratamento de N3 — ver `docs/closeout/BASELINE-RESULTS.md`.

**Inventário de defeitos já feito:** `docs/closeout/DEFECTS.md` (40 445 B) é a entrada
pronta para F1..F4; as falhas da baseline não são reinventadas em cada fase, são
referenciadas a partir daí.

---

## F0 — Reconhecimento, preservação e baseline

**Conteúdo**
1. Estado git completo (toplevel, branch, status, log, stash, diff, worktrees) nos dois diretórios.
2. Resposta **D-15** (raiz canónica, divergência de cópias, árvore em runtime).
3. Branch de trabalho `closeout/nexus-v3` + worktree `nexus-baseline`.
4. Backup integral dos dados persistentes (`data/`, `.nexus/`, `config/`, `logs/conversations/`) com SHA256SUMS.
5. Sonda de ambiente (Python, venv, node/npm, layout de testes).
6. Execução da suite de testes de backend no worktree de baseline e registo completo.
7. Documentos BASE: `D-15-CANONICAL-ROOT.md`, `BASELINE.md`, `BASELINE-RESULTS.md`, `PLAN.md`, `STATE.json`, `WORKLOG.md`.

**Exit gate**
- Todos os ficheiros de `docs/closeout/` existem com evidência real (comandos + saídas).
- `git status --porcelain=v1` final **igual** ao inicial (a não ser ficheiros de terceiros assinalados).
- Worktree `nexus-baseline` criado e funcional.
- Resultados de baseline reais gravados, incluindo falhas.
- D-15 respondido com prova.

**Dependências:** nenhuma (fase inicial, bloqueante).
**Riscos:** suite longa (> 1 h) → fragmentação paralela; venv Windows vs Python WSL; portas/processos Windows fora do namespace WSL.
**Critérios de aceitação:** ver "ACCEPTANCE CRITERIA" na entrega da F0.

---

## F0.5 — Higiene da árvore e do git (bloqueada por autorização do utilizador)

> **BLOQUEADA.** Esta fase só arranca com **autorização explícita** do utilizador.
> Nenhuma ação destrutiva foi executada em F0.

**Conteúdo**
1. Confirmar/limpar o resíduo da árvore aninhada `nexus-ide/nexus/` (1 ficheiro, 55 B).
2. Remover worktrees `prunable` obsoletos (6 no arranque).
3. Classificar os 251 ficheiros modificados e 27 não rastreados em: (a) runtime/dados — deixar; (b) código real a comitar; (c) lixo a arquivar.
4. Consolidar a divergência de portas (`8000/3000` vs `8001/3001`) num único launcher documentado.

**Exit gate**
- Inventário de `git status` classificado e publicado; decisões de remoção autorizadas por escrito.
- Nenhum ficheiro de código perdido; nenhuma remoção destrutiva executada.

**Dependências:** F0; **autorização explícita do utilizador**.
**Riscos:** apagar estado de runtime que ainda não está commitado; worktrees `prunable` pertencentes a outras ferramentas (kilo/codex/opencode).
**Critérios de aceitação:** relatório de classificação com contagens exatas por classe; zero ficheiros apagados sem autorização.

---

## F1 (P0) — GoalState canónicoico + persistência transacional + DoD derivado do pedido + gate de evidência

**Resolve:** D-15 / D-05 / D-14.

**Exit gate:** um run real fecha com mapa critério→evidência; taxa de falso sucesso = 0 na
adjudicação; dados preservados.

**Dependências:** F0 (e F0.5 apenas para a classificação do estado da árvore).
**Riscos:** sem gate de evidência, o "sucesso" volta a ser afirmado sem prova; persistência
não transacional perde o run a meio.
**Critérios de aceitação:** mapa critério→evidência observável num run real; zero falsos
positivos na adjudicação; nenhum dado de F0 perdido.

---

## F2 (P0) — Ponto de decisão único + adaptadores + shadow mode + paridade

**Exit gate:** todos os entrypoints (os 9..10 inventariados) decidem no mesmo sítio;
divergências justificadas; modos explícitos intactos.

**Dependências:** F1.
**Riscos:** mais de um caminho de decisão reintroduz a divergência; shadow mode sem
comparação de resultado é decoração.
**Critérios de aceitação:** cada entrypoint demonstrado a decidir no mesmo ponto;
divergência documentada com motivo; nenhum modo implícito.

---

## F3 (P1) — Router adaptativo + manifesto verificado por sondas + telemetria de decisão + explicabilidade

**Exit gate:** testes provam escolha por competência; repetição do melhor agente sem
penalização; decisões explicáveis no UI.

**Dependências:** F2.
**Riscos:** router que escolhe por heurística escondida não é explicável; sondas sem
manifesto verificável degeneram em *healthcheck* cosmético.
**Critérios de aceitação:** teste que force escolha por competência; repetição do melhor
agente sem penalidade observável; explicação visível no UI.

---

## F4 (P1) — Loop orientado a objetivos + orçamentos + progresso/estagnação + checkpoints + retoma idempotente

**Exit gate:** kill real a meio de um run → retoma correcta sem repetir efeitos;
estagnação detectada e resolvida.

**Dependências:** F3.
**Riscos:** retomar repetindo efeitos (dupla escrita); estagnação detectada mas não
resolvida.
**Critérios de aceitação:** kill real documentado com run retomado e sem efeitos
duplicados; caso de estagnação detectado **e** resolvido.

---

## F5 (P1) — Memória, isolamento, compactação, handoff estruturado, paralelismo seguro, skills dinâmicas

**Exit gate:** teste de amnesia passa; zero fuga entre projetos; conflitos de escrita
detectados antes de executar.

**Dependências:** F4.
**Riscos:** **já materializado em F0** — a baseline tem uma fuga de contexto entre sessões
concorrentes (`test_superagent_e2e_scenarios.py::test_scripted_primary_chat_scenarios_pass_in_isolation`,
sessão B devolveu a resposta da sessão A) e um `backend.memory` que não importa
(`MemoryItem` inexistente). Ver ADR de reordenação.
**Critérios de aceitação:** teste de amnesia passa; zero fuga medida entre projetos;
conflito de escrita detetado **antes** de executar.

---

## F6 (P2) — Desempenho, contexto mínimo, latência, streaming, dashboard, documentação verdadeira, arrumação

**Exit gate:** métricas melhoram sem perda de correção; UI fiel ao backend; docs
verificados.

**Dependências:** F5.
**Riscos:** ganhar desempenho perdendo correção; UI a prometer o que o backend não faz;
docs desactualizados a mentir por omissão.
**Critérios de aceitação:** métricas F6 comparadas com F0 sem regressão de correção;
UI validada contra o backend real; docs verificados.

---

## Thresholds não-funcionais pré-registados (verbatim do programa)

| # | Métrica | Limite |
|---|---|---|
| N1 | *router overhead* p95 | **p95 < 50 ms** |
| N2 | regressão de latência *end-to-end* vs baseline | **<= 10 %** |
| N3 | fugas de contexto entre projetos/bots | **zero** |
| N4 | sucesso de retoma (*resume*) sob interrupção induzida | **>= 95 %** |
| N5 | cancelamento efetivo | **< 5 s** |
| N6 | corrupção de SQLite após `kill -9` | **zero** |

Nenhum destes limites pode ser relaxado durante o closeout; uma medição fora do
limite é um defeito a registar, não um limite a mudar.

**Estado mediado em F0 (baseline):** nenhum destes thresholds foi medido em F0 — F0 mede
testes, não desempenho. N3 tem já uma violação *observada na suite* (ver F5). N1, N2, N5,
N6 ficam para F4/F6.

---

## Registo de decisões

| Data | Decisão | Motivo |
|---|---|---|
| 2026-11-12 | Branch e worktree criados **no parent** `Desktop/nexus`, não em `nexus-ide/` | D-15: a raiz git canónica é o parent |
| 2026-11-12 | Suite de baseline fragmentada por diretório em paralelo | A versão em série extrapola > 3 h e excede o limite de execução |
| 2026-11-12 | `probe1_tmp.py` deixado intacto | Pertence a outro agente (`closeout-inventario`); regra proíbe apagar ficheiros de terceiros |
| 2026-11-13 | Fases F1..F6 reescritas com o conteúdo normativo do programa (§5) | O plano do utilizador não é redefinível por mim; a versão anterior era invenção minha |
| 2026-11-13 | Trabalho de higiene movido para **F0.5**, bloqueado por autorização | A higiene não é uma fase do programa; é necessidade local e depende de autorização |
| 2026-11-13 | Inventário de defeitos (`DEFECTS.md`) declarado entrada de F1..F4 | Evita reinventar a classificação em cada fase |
