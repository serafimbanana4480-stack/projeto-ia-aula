# PLANO CRÍTICO DE MELHORIAS — NEXUS IDE
**Data:** 2026-07-31 · Auditoria completa: prompts → subagentes → modos → dashboard

---

## RESUMO EXECUTIVO

O projeto tem **arquitetura ambiciosa e bem documentada**, mas sofre de um problema sistémico: **muito código escrito, pouco código ligado**. A maioria dos sistemas avançados (subagentes, modos Infinity, advisor, orquestração autónoma) existe como implementação isolada com testes unitários a passar, mas **nunca é invocada no fluxo real**. O resultado: funcionalidades "no papel" que não funcionam na prática.

**Diagnóstico central:** o NEXUS não precisa de mais funcionalidades — precisa de **wiring, consolidação e honestidade operacional**.

---

## 1. PORQUE OS SUBAGENTES NÃO FUNCIONAM (causa raiz confirmada)

### 1.1 Instanciados mas nunca invocados — P0 CRÍTICO
`backend/orchestrator/autonomous_improvement_orchestrator.py:167-168` cria `SubagentRunner` e `SubagentManager`, mas **não existe uma única chamada** a `run_phase()`, `run_subagent()` ou `run_parallel()` em todo o ficheiro. São objetos mortos. O ciclo autónomo corre sem nunca spawnar subagentes.

**Fix:** implementar a fase de execução do ciclo que decompõe propostas em fases RESEARCH → DESIGN → BUILD → VERIFY e as despacha via `subagent_manager.run_phase()`.

### 1.2 Tudo desligado em development — P0 CRÍTICO
`main.py:185-191` (`_svc`): quando `settings.environment == "development"`, **todos** os serviços de background ficam OFF por defeito — DASHBOARD_AGENT, AI_ORCHESTRATOR, AUTO_TRIGGER, SELF_HEALING, GUARDIAN, EXEC_ENGINE, etc. Localmente (onde o projeto é usado) nada disto corre.

**Fix:** inverter o default para dev (ou criar perfil `dev-full`), e expor estes toggles no dashboard/settings em vez de variáveis de ambiente escondidas.

### 1.3 Dois sistemas de subagentes paralelos — P1
`SubagentManager` e `SubagentRunner` coexistem com dataclasses `SubagentResult` **duplicadas e divergentes** (campos diferentes). Risco de drift idêntico ao que o próprio docstring do runner admite ter havido com os budgets.

**Fix:** matar um dos dois (recomendo manter o `SubagentManager`, mais completo: checkpoints, budgets, eventos) e re-exportar compat shims.

### 1.4 Lifecycle com cliente nulo — P1
`SubagentManager.__init__` faz fallback para `AgentLifecycleManager(registry=None, llm_client=None)` — se o chamador não injetar dependências, as fases correm contra um cliente LLM nulo e falham silenciosamente.

**Fix:** falhar alto no construtor (`ValueError`) quando `llm_client` é None.

---

## 2. MODOS (advisor, automático, Infinity Suite)

### 2.1 Modos avançados invisíveis no frontend — P0
Os 11 modos (vibe-infinity, advisor-infinity, forge, swarm-foundry, multiverse, proof, reality-lab, archaeologist, evolve, sentinel, autonomous) existem em `config/modes-advanced.yaml`, têm engine (`advanced_modes.py`, 910 linhas) e rotas (`/api/advanced-modes/*`), mas **o frontend tem ZERO referências** — nenhum seletor de modo, nenhuma chamada à API. São inatingíveis pelo utilizador.

**Fix:** mode selector no chat UI (dropdown com os modos de `modes.yaml` + `modes-advanced.yaml`), página de estado do modo ativo, e ligação do toggle ao engine.

### 2.2 Advisor é heurística de keywords — P0
`agents/advisor.py:_analyze_completion_claim` é **pesquisa de strings** ("test", "security", "it works"...). Não verifica nada: não corre testes, não lê ficheiros, não confirma claims. `supported_actions = set()` — o agente que existe para "verificar diretamente" não tem uma única ação. É teatro de verificação.

**Fix:** dar ao Advisor ações reais (`RUN_TESTS`, `READ_FILE`, `EXECUTE_CODE`) e substituir a heurística por verificação factual (executar a suite, verificar diffs, citar evidência com ficheiro:linha).

### 2.3 Duplicação Advisor — P1
`InterventionLevel` está definido duas vezes (`agents/advisor.py` e `orchestrator/advanced_modes.py`). O AdvisorAgent e o modo advisor-infinity são duas implementações que nunca se cruzam.

**Fix:** uma única fonte de verdade; o modo consome o agente.

### 2.4 Modo `auto` desligado do chat — P1
`config/modes.yaml:auto` promete "consulta subagentes automaticamente", mas `routes/chat.py` não tem qualquer referência a subagentes ou modos avançados. O modo é só um system prompt; a maquinaria prometida não existe no caminho do chat.

**Fix:** pipeline do chat deve resolver modo → carregar config YAML → ativar subagentes/qualidade gates conforme `supports_subagents`.

---

## 3. DASHBOARD

### 3.1 Agente desligado em dev — P0 (mesmo fix de 1.2)
### 3.2 Dois backends de dashboard — P1
`backend/dashboard/` (websocket_server + realtime_dashboard) e `agents/dashboard_agent.py` coexistem sem claridade sobre qual alimenta o frontend `/dashboard`. Risco de métricas divergentes.

**Fix:** uma única fonte de métricas; o dashboard_agent publica para o mesmo stream que o frontend consome.

### 3.3 Telemetria de subagentes/modos ausente — P1
O frontend tem páginas `/dashboard/agents`, `/pipeline`, `/topology`, `/tasks` — mas nada mostra execuções de subagentes (que nem correm), modos ativos, ou intervenções do advisor. Quando 1.1 e 2.1 forem corrigidos, o dashboard deve ser a superfície de observação: fases em curso, budgets consumidos, checkpoints, intervenções.

---

## 4. HIGIENE DO REPOSITÓRIO — P1

- **Ficheiros lixo na raiz:** `hello.py`, `hello_world.py`, `sort.py`, `tmpn8asus67/`, `tmp_test/`, `C:Windowsnexus_test.txt` (nome corrompido), `python3.11_3.11.0~rc1-1~22.04_amd64.deb` (pacote .deb num repo Windows), 5+ `.bat` soltos.
- **Duas venvs dentro do repo:** `.venv/` e `.venv-validation/` — devem ser ignoradas, não conviver com o código.
- **701 ficheiros Python** — massiva sobre-engenharia para o estágio atual; pastas como `quantum/`, `federated_learning/`, `neural_architecture/`, `edge_computing/` são distração face aos P0.
- **Drift de documentação:** ARCHITECTURE.md fala de "24 agentes registados" e lista 9; o registry tem muito mais. `deepseek-v4-flash` é citado como modelo — verificar se existe no OpenRouter.
- **Testes bloqueados no Windows:** `PermissionError` em `Temp\pytest-of-rodri`. Fix permanente: `pytest.ini` com `tmpdir` local ou conftest que define `TMPDIR` antes do import do pytest.

---

## 5. PLANO DE AÇÃO PRIORIZADO

### Sprint 0 — "Fazer funcionar o que existe" (1 semana)
1. **[P0]** Ligar subagentes no ciclo autónomo (1.1) — sem isto, todo o subsistema é decorativo.
2. **[P0]** Perfil dev com serviços ligados + toggles no UI (1.2).
3. **[P0]** Mode selector no frontend (2.1).
4. **[P0]** Limpeza da raiz do repo (4) — 30 minutos, ganho imediato de credibilidade.
5. **[P0]** Fix TMPDIR nos testes (4).

### Sprint 1 — "Verificação real" (1–2 semanas)
6. **[P0]** Advisor com ações reais e verificação factual (2.2).
7. **[P1]** Consolidar SubagentManager/Runner (1.3) e fail-fast no lifecycle nulo (1.4).
8. **[P1]** Unificar AdvisorAgent ↔ advisor-infinity (2.3).
9. **[P1]** Pipeline do chat consome config de modos (2.4).

### Sprint 2 — "Observabilidade honesta" (1 semana)
10. **[P1]** Dashboard único com telemetria de subagentes/modos/advisor (3.2, 3.3).
11. **[P1]** Alinhar ARCHITECTURE.md com a realidade (ou gerar contagens automaticamente).

### Sprint 3 — "Automação avançada" (depois dos P0/P1)
12. **[P2]** Auto-trigger engine com regras visíveis/editáveis no UI.
13. **[P2]** Auditoria dos 701 ficheiros: arquivar módulos sem consumidores (quantum, federated, edge...).
14. **[P2]** CI a correr a suite completa com TMPDIR correto.

---

## PRINCÍPIO ORIENTADOR
> **Antes de adicionar o próximo sistema, provar que o anterior é invocado no fluxo real.** Um modo que funciona vale mais que onze no YAML.
