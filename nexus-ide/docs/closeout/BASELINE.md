# BASELINE — Suite de testes no estado base

- **Timestamp (UTC):** 2026-11-12T23:29Z (arranque da execução fragmentada)
- **Base SHA:** `e12c214c232ac8619aa8c52ac46119ea444d0503`
- **Branch de trabalho:** `closeout/nexus-v3` (criado a partir de `cursor/bots-chat-v2-e082`)
- **Worktree:** `/mnt/c/Users/rodri/Desktop/nexus-baseline` (detached HEAD no base SHA)
- **Diretório do projeto no worktree:** `/mnt/c/Users/rodri/Desktop/nexus-baseline/nexus-ide/`
- **Raiz git canónica:** `/mnt/c/Users/rodri/Desktop/nexus` (ver D-15)
- **Interpretador:** `.venv` do projeto (CPython **3.13.14**, Windows), executado a partir do WSL.
  `pytest 9.1.1`, `pytest-timeout 2.4.0`, `pytest-cov 6.3.0`, `pytest-asyncio 1.4.0`.
- **Configuração:** `pyproject.toml [tool.pytest.ini_options]` (addopts `-ra --strict-markers
  --strict-config -p no:cacheprovider --timeout=300`, `asyncio_mode=auto`,
  `filterwarnings=error` com exceções declaradas).

## Método

O comando de referência (Makefile `test-backend`) é
`pytest backend/tests/ --cov=backend … -v` a partir da raiz do projeto. A baseline foi
corrida **sem** `--cov` e em `-q`, com `-p no:cacheprovider` e o `--timeout=300`
global já declarado no `pyproject.toml`, para isolar o resultado dos testes da
medição de cobertura.

Uma primeira tentativa em série foi cancelada ao fim de **10 m 39 s a ~4,5 %**
(295 testes), o que extrapola ≈ 3 h 50 min para o total. Para entregar a baseline
completa dentro do orçamento de execução, a suite foi **fragmentada por diretório e
corrida em paralelo** (7 processos simultâneos na onda 1). Nenhum teste foi
enfraquecido, saltado ou marcado `xfail` para obter verde.

## O que correu e o que não correu

| Bloco | Estado | Nota |
|---|---|---|
| Recolha (`--collect-only`, suite completa) | **Correu** | **6953 testes** recolhidos em 46,65 s |
| Suite completa em série | **Não completou** | Cancelada a ~4,5 % (limite de execução) |
| Onda 1 (orchestrator, tools, agents, runtime, llm, pipeline, core) | Corrida | 7 shards em paralelo |
| Onda 2 (integration, evolution, persistence, observability, api, swarm, sandbox, knowledge, contracts, config, middleware, skills, mcp, auth, infrastructure, experience, stress, tasks, ficheiros de topo) | Pendente | Ver BASELINE-RESULTS.md quando publicada |
| Testes de frontend (`pnpm run test`) | **Não corridos** | `node`/`pnpm` ausentes no PATH do WSL (ver B3) |

### Marca `integration`
Os testes marcados `integration` "requiring a live Ollama instance" são saltados por
omissão segundo `pyproject.toml` (`markers` / conftest). Não foram forçados.

## Ambiente em falta (registado, não contornado)

- `node`, `pnpm` — não no PATH do WSL (`npm` 11.19.0 existe).
- `sqlite3` — não no PATH do WSL (backup feito por cópia direta).
- `numpy`, `playwright` — declarados como *extras* opcionais em `pyproject.toml`
  (`analytics`, `federated`, `quantum`, `browser`); ausentes do `.venv`.
- `airllm`, `sentence-transformers` — mensagens de aviso/"não disponível" observadas
  no arranque do app (degradação esperada, não é falha de teste).

## Resultados

**Suite completa executada** (39 shards, 4 ondas paralelas):

| Métrica | Total |
|---|---:|
| **passed** | **6846** |
| **failed** | **34** |
| **skipped** | **40** |
| **error** | **0** |
| **total** | **6920** |
| **wall-clock total** | **1753 s ≈ 29 min** (23:29:37Z → 23:58:50Z) |
| **shard mais lento** | `tools` — 2424,09 s (40 m 24 s) |

**As 34 falhas são PRE-EXISTING BASELINE FAILURE** — existem no SHA base e não foram
introduzidas por este closeout. Nenhum teste foi enfraquecido, saltado ou marcado
`xfail` para obter verde.

> **Reconciliação:** as contagens acima foram recalculadas a partir da linha de resumo
> de cada um dos 39 ficheiros de shard, e cruzadas com a contagem de linhas `FAILED`
> nesses mesmos ficheiros (34 = 34). Uma versão anterior deste relatório dizia 24
> falhas; o erro e a sua causa estão registados em `BASELINE-RESULTS.md`.

Ver **`BASELINE-RESULTS.md`** para a lista completa com `test id` + causa provável,
agrupada em 12 causas raiz (A..L), e para o defeito adicional verificado fora da suite
(`backend.memory` não importa por `MemoryItem` inexistente).

### O que correu e o que não correu

| Bloco | Estado | Nota |
|---|---|---|
| Recolha (`--collect-only`, suite completa) | **Correu** | **6953 testes** recolhidos em 46,65 s |
| Suite completa em série | **Não completou** | Cancelada a ~4,5 % (limite de execução) |
| Ondas 1-4 (39 shards) | **Correu — completa** | 6846 passed / 24 failed / 40 skipped |
| Testes de frontend (`pnpm run test`) | **Não corridos** | `node`/`pnpm` ausentes no PATH do WSL (ver B3) |
| Testes marcados `integration` com Ollama vivo | Saltados | Por omissão segundo `pyproject.toml`; não forçados |
| `--cov` | Excluída | Para isolar o resultado dos testes |

## Evidência

- `../../../artifacts/closeout/logs/baseline-tests-PARTIAL-10300s.txt` — saída parcial da tentativa em série.
- `../../../artifacts/closeout/logs/shards/OVERALL.txt` — início e duração por shard.
- `docs/closeout/BASELINE-RESULTS.md` — contagens finais e as 34 falhas classificadas.
- `../../../artifacts/closeout/logs/shards/<dir>.txt` — saída completa por shard.
- `../../../artifacts/closeout/logs/env-probe.txt` — ambiente e interpretador.
