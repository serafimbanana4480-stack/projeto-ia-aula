# PROMPT — Auto-diagnóstico e melhoria autónoma do NEXUS IDE

> Cola este bloco inteiro no chat do NEXUS IDE (modo agente / auto, max autonomy).

---

## MISSÃO

És o agente autónomo do NEXUS IDE e o teu alvo é **o próprio NEXUS IDE**, em `C:\Users\rodri\Desktop\nexus\nexus-ide`.

Objetivo: provar, com execução real e evidência, o que funciona, o que está partido e o que está mal desenhado neste ambiente — e depois **corrigir**. Não confies em nenhum README, comentário ou documento existente: cada afirmação que fizeres tem de vir de um comando que corres ou de um endpoint/página que tocas. Se não executaste, não sabes.

Tens autonomia total: arranca serviços, corre testes, altera código, cria testes, faz commits. Trabalha até ao fim sem me pedir permissão a cada passo.

---

## REGRAS DE ENGAGEMENT

1. **Branch dedicada.** `git checkout -b selfcheck/<YYYY-MM-DD>` antes de qualquer alteração. Nada de commits diretos em `main`.
2. **Nunca apagar** dados do utilizador: `data/`, `.nexus/backups/`, `logs/`, `.env`. Antes de mexer na BD, copia o ficheiro SQLite.
3. **Segredos nunca aparecem no relatório.** Se leres `.env`, reporta só o *nome* da chave e se está presente/válida — nunca o valor.
4. **Ambiente Windows.** Python em `C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe` (ou `.venv`), frontend com `pnpm`/`npm` em `frontend/`. Se um comando do `Makefile` for bash-only, traduz para PowerShell em vez de reportares "não testável".
5. **Um problema = uma entrada rastreável** com: ficheiro:linha, comando que o reproduz, output real (colado), causa raiz, correção, e como validaste que ficou corrigido.
6. **Timeout de 5 min por comando.** Se algo pendurar, mata, registra como "hang" com o que estava a fazer, e continua. Um passo bloqueado não pára a auditoria.
7. **Proibido inventar.** Se não conseguiste testar algo (falta Ollama, falta Redis, falta API key), escreve `NÃO TESTADO — motivo`. Zero suposições apresentadas como factos.

---

## FASE 0 — Inventário do ambiente

- Versões reais: Python, Node, pnpm/npm, Docker, Redis, Ollama. Compara com o que o `README.md` / `STARTUP.md` exigem e aponta divergências.
- `.env` vs `.env.example`: variáveis em falta, variáveis a mais, defaults perigosos, chaves presentes mas inválidas.
- `git status` e `git log --oneline -20`: ficheiros não commitados, artefactos que não deviam estar no repo.
- Lixo no repo: enumera e classifica (`.pytest-tmp*`, `.pytest-run`, `.venv-validation`, `C:\Windows\nexus_test.txt` na raiz de `nexus-ide/`, `tmp_dev.log`, `test-results/`, `nexus_ide_backend.egg-info`). Diz quais devem ir para `.gitignore` e quais são sintoma de bug (um path Windows literal como nome de ficheiro **é** um bug de escrita de ficheiros — encontra o código que o criou).

## FASE 1 — Estática e tipos

Corre e cola o output resumido (contagens + top ofensores):

- `ruff check backend/` e `python -m mypy backend/ --ignore-missing-imports`
- `cd frontend && npm run lint` e `npm run type-check`
- Deteta código morto e duplicado. Suspeitos declarados a investigar: `backend/orchestrator/events_temp.py`, múltiplos `*_orchestrator.py` sobrepostos, e as **três fontes de verdade** de modelos (`config/models.yaml`, `backend/orchestrator/routes/models_ui.py`, mapa `MODEL_TO_TIER` em `frontend/components/chat/ChatPanel.tsx`).
- `backend/orchestrator/main.py` registra 40+ routers. Verifica quantos têm testes, quantos têm auth, e quantos são features mortas nunca chamadas pelo frontend.

## FASE 2 — Testes

- `python -m pytest backend/tests/ --cov=backend --cov-report=term-missing -q` → total, falhados, skipped, **cobertura real**. Nota: o `Makefile` usa `--cov-fail-under=5`; diz-me a cobertura verdadeira e se 5% é um gate honesto.
- Por área: `backend/tests/agents/`, `tools/`, `knowledge/`, `orchestrator/`, `contracts/`, `middleware/`.
- `cd frontend && npm test` (vitest) e `npx playwright test` (e2e).
- Para cada teste falhado: causa raiz e se o teste está errado ou o código está errado.
- Identifica **testes teatro**: os que passam sem assertar nada de útil, com tudo mockado, ou que testam o mock e não o sistema. Lista-os explicitamente.

## FASE 3 — Boot real

- Arranca o backend: `python -m uvicorn backend.orchestrator.main:app --host 0.0.0.0 --port 8000`. Mede o tempo de arranque e **cola todos os WARNING/ERROR** do startup.
- Arranca o frontend: `cd frontend && npm run dev` (127.0.0.1:3000). Cola os erros de build/hydration.
- `scripts/healthcheck.sh` (ou equivalente PowerShell), `scripts/smoke_test_complete.py`, `scripts/selftest/run_diagnostics.py`, `scripts/validate_config.py`.
- Percorre `GET /openapi.json` e testa **cada** rota `/api/*`: status, latência, shape da resposta. Marca as que dão 500, as que devolvem stub/hardcoded, e as que aceitam input não validado.
- Testa degradação: com Ollama **desligado**, com Redis **desligado**, com API key **inválida**. O sistema falha com mensagem clara ou explode com stack trace? Falha graciosa é requisito, não bónus.

## FASE 4 — UI e dashboard (clicar de verdade)

Abre o browser e visita **todas** as rotas de `frontend/app/`: `/`, `/dashboard`, `/simple-dashboard`, `/editor`, `/nexus`, `/mission-control`, `/models`, `/providers` (settings), `/projects`, `/analysis`, `/analytics`, `/database`, `/documents`, `/pdf`, `/scraping`, `/search`, `/swarm`, `/tools`, `/mcp`, `/settings`, `/login`.

Para cada página: carrega sem erro? consola limpa? os dados são reais ou placeholder? os botões fazem algo? Cola os erros de consola e as chamadas de rede que falham.

Testes de fluxo obrigatórios:

1. **Chat end-to-end** — escolhe um modelo específico, envia mensagem, confirma nos logs do backend **qual modelo foi realmente executado**. (Há um bug conhecido: o selector envia `tier` em vez do `id` do modelo, ver `AUDITORIA-PROVIDER-UI.md`. Confirma se ainda existe e corrige-o de raiz: provider com `list_models()`, uma única fonte de verdade, id do modelo a chegar intacto ao provider.)
2. **Editor Monaco** — abrir ficheiro, editar, gravar, confirmar no disco.
3. **Terminal xterm** — correr comando, ver output.
4. **Providers/keys** — meter uma chave, ver a lista de modelos daquele provider popular-se, escolher um, usá-lo.
5. **Cancelamento** — arranca uma tarefa longa e cancela. Para mesmo ou continua a queimar tokens em background?

## FASE 5 — Segurança e robustez

- Path traversal nos endpoints de ficheiros/workspace (`../../`, paths absolutos, symlinks).
- Injeção de comandos no endpoint de terminal e nas tools de execução.
- SQL: confirma que não há concatenação de strings em queries (houve um fix recente de SQL injection — verifica se ficou completo).
- Auth: quais routers estão sem autenticação e expostos? CORS permissivo? rate limiting real ou decorativo?
- Sandbox de execução de código: consegues escapar dela? (documenta, não exploras fora do repo).
- Dependências: `pip list --outdated`, `npm audit`. Vulnerabilidades críticas primeiro.

## FASE 6 — Performance

- Tempo de arranque do backend (perfila com `scripts/profile_startup.py`) e do primeiro paint do frontend.
- Latência p50/p95 dos endpoints mais usados. Deteta N+1 e queries sem índice.
- Uso de RAM em idle e sob chat. Leaks entre pedidos.
- Bundle do frontend: tamanho, o que está a inflá-lo, o que devia ser lazy.

## FASE 7 — Correção (executa)

Ordena tudo por `impacto ÷ esforço` e **corrige**, do topo para baixo:

- **P0** — quebra funcionalidade central ou é falha de segurança. Corrige já.
- **P1** — funciona mal, mente ao utilizador, ou é dado falso na UI. Corrige.
- **P2** — dívida técnica, duplicação, testes fracos. Corrige o que couber.
- **P3** — documenta e deixa proposto.

Para cada correção: escreve primeiro um teste que falha, corrige, mostra o teste a passar. Commits pequenos e atómicos, formato `fix|feat|test|chore: <o que mudou e porquê>`. No fim, corre a suite completa outra vez e confirma que não regrediu nada.

---

## ENTREGÁVEIS

1. `docs/SELFCHECK-<data>.md` — o relatório:
   - **Veredicto em 10 linhas**: o que funciona de verdade, o que está partido, o risco maior.
   - **Scorecard** por área (arquitetura, testes, segurança, performance, UX, docs) com nota /10 e a evidência que justifica a nota.
   - **Tabela de achados**: ID · severidade · ficheiro:linha · reprodução · causa raiz · estado (corrigido/proposto).
   - **O que corrigi** com links para os commits.
   - **O que NÃO testei** e porquê.
   - **Top 5 melhorias** que dariam o maior salto de qualidade, com estimativa de esforço.
2. `docs/SELFCHECK-evidence/` — outputs crus, logs de startup, screenshots das páginas, coverage report.
3. Branch com os commits das correções + resultado da suite final.

## CRITÉRIO DE SUCESSO

Termina apenas quando conseguires responder, com evidência colada, a estas cinco perguntas:

1. Se eu clonar isto num PC limpo e seguir o `README`, arranca? (testa mesmo, num diretório novo)
2. O modelo que escolho na UI é o modelo que corre? (prova com logs)
3. Que percentagem da dashboard mostra dados reais e não placeholder?
4. Qual é a coisa mais perigosa que um utilizador consegue fazer sem autorização?
5. Onde é que este projeto está a mentir sobre si próprio — features documentadas que não existem, testes que não testam, métricas inventadas?

Sê brutalmente honesto. Prefiro um relatório que diz "6/10 e aqui estão os 40 problemas" do que um que diz "9.3/10, tudo excelente" sem provas. Elogios sem evidência são ruído.

---

## Reforços obrigatórios para continuidade e segurança

Antes da Fase 0, acrescenta estes controlos:

1. **Worktree sujo não autoriza misturar trabalho.** Regista staged/unstaged/untracked. Não faças commit de ficheiros que já tinham alterações alheias sem conseguires separar o patch.
2. **Distingue histórico de execução.** Uma sessão “persistiu” apenas se mensagens, run em curso, etapa/checkpoint e capacidade de retoma forem testados separadamente.
3. **Teste de restart em três níveis:** reload por alteração de `.py`, restart manual limpo e kill inesperado durante stream. Mede PID, `run_id`, último checkpoint e primeiro evento após restart.
4. **Nunca uses bearer token em URL.** Procura `?token=`, confirma access logs, browser history e proxy logs, e exige header/cookie seguro.
5. **Baseline/green separados.** Guarda o output antes e depois de cada correção; não aceites um teste criado já verde como prova de regressão.
6. **Processos órfãos.** Depois de cada timeout, confirma que filhos `pytest`, `uvicorn`, `next`, `node` e browsers foram terminados.
7. **Caches concorrentes.** Testa `next dev` enquanto `next build` corre e confirma diretórios de output distintos.
8. **Rate limits nos E2E.** Faz login uma vez por worker/suíte; não contornes segurança aumentando limites.
9. **Redação automática.** Antes de entregar evidence, procura e mascara JWTs, API keys, passwords, cookies e query strings sensíveis.
10. **Critério de paragem honesto.** Se a suíte integral exceder 5 minutos, escreve TIMEOUT; não extrapoles resultados de testes alvo.

## Prompt curto — investigar só reinícios e retoma

```text
No NEXUS IDE, reproduz a perda de continuidade sem assumir a causa.
1) cria um run controlado com contador/checkpoint;
2) testa alteração de .py, restart limpo e kill inesperado;
3) em cada caso regista PID, session_id, run_id, mensagens persistidas,
   estado em memória e se retoma automaticamente;
4) escreve primeiro um teste que falha;
5) corrige o launcher e/ou implementa checkpoint/resume;
6) prova o resultado durante pelo menos dois ciclos de restart.
Não apagues dados, faz backup SQLite e não reveles segredos.
```

## Prompt curto — validar modelo selecionado

```text
Escolhe na UI um ID de modelo concreto, envia uma mensagem marcador e prova:
UI model id -> payload /api/chat -> provider resolvido -> model enviado ao SDK.
Não aceites tier, label ou default como prova. Guarda eventos SSE e um log
sanitizado com provider+model. Repete com dois providers ou marca NÃO TESTADO.
```

## Prompt curto — segurança operacional

```text
Audita auth, paths, terminal, SSE e logs do NEXUS. Não explores fora do repo.
Testa chamadas sem token, traversal, paths absolutos e inputs de shell inofensivos.
Procura bearer tokens em URLs/logs e segredos serializados por settings.
Para cada falha: reprodução, impacto, teste vermelho, correção e teste verde.
```
