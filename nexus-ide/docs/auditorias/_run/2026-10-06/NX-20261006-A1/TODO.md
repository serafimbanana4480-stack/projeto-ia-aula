# TODO — NX-20261006-A1 (única, sincronizada com findings.jsonl)

Deduplicado. Sem itens sem finding associado.

| ID | Finding | Prio | Depende | Ficheiros permitidos | Critério de aceitação | Teste de prova | Estado | Evidência | Revisor independente |
|---|---|---|---|---|---|---|---|---|---|
| NX-T-000 | NX-ENV-003 | **P0** | decisão humana | — | Nenhuma escrita concorrente durante a auditoria, OU auditoria isolada em snapshot/worktree próprio | `git status` + mtimes estáveis | **`BLOCKED`** — requer decisão | E3 | n/a |
| ~~NX-T-001~~ | NX-TEST-001 | ~~P1~~ | — | — | *(critério cumprido)* | Suite verde 119/119 | **`DONE_BY_THIRD_PARTY`** às 01:39:52 — patch desta sessão **retirado** | E3 (exit 0, hashes SAME) | **PENDENTE** |
| NX-T-002 | NX-TEST-002 | P2 | NX-T-000 | por escolher (1 de 3) | Suite inteira e execução isolada dão o mesmo resultado, em árvore parada | Ficheiro completo 2× + isolado | `NOT_VALIDATED` — só corrigir depois de NX-T-000 | E2 (não reproduziu) | **PENDENTE** |
| NX-T-003 | NX-SSRF-002 | P3 | — | `backend/tools/safe_http.py` | Backend injetado inválido falha na construção com erro claro | Teste a injetar backend inválido | `OPEN` | E1 | **PENDENTE** |
| NX-T-004 | NX-SSRF-003 | P2 | — | leitura primeiro; depois o ficheiro confirmado | Cada sink de rede tem origem de URL confirmada (config vs modelo/utilizador) | Leitura + teste por sink confirmed | `OPEN` — `NOT_VALIDATED` | E1 (grep) | **PENDENTE** |
| NX-T-005 | NX-ENV-001 | P2 | decisão humana | — | Volume de teste autorizado, ou C: acima de 5% | `Get-PSDrive` | `BLOCKED` | E3 | n/a |
| NX-T-006 | NX-ENV-002 | P3 | — | — | Origem das +5 entradas de git status identificada | `git status` + autor | `OPEN` | E2 | n/a |
| NX-T-007 | NX-DOC-001 | P3 | — | `AGENTS.md:31` | Doc bate certo com package.json/lockfile | `pnpm --version` vs doc | `OPEN` | E1 | n/a |

## Patch para NX-T-001 — RETIRADO, NÃO APLICAR

**Não aplicar.** As 2 correções abaixo foram já aplicadas por outro processo às **01:39:52**
(hash `a69e6fa…` → `0a3062b…`). Aplicá-las agora seria no-op ou colisão. Mantido apenas como
registo do diagnóstico. O ficheiro é **untracked**, logo `git diff` não serviria de rollback.

Ficheiro: `backend/tests/tools/test_ssrf_tool_guards.py` (untracked `??`)

```diff
@@ linha 137 @@
-    async def guarded_backend_factory(*_args: Any, **_kwargs: Any) -> Any:
+    def guarded_backend_factory(*_args: Any, **_kwargs: Any) -> Any:
         return PublicAddressNetworkBackend(inner=backend, resolver=resolve)
@@ linha 148 @@
-def _public_only_resolver(host: str, port: int) -> list[str]:
+async def _public_only_resolver(host: str, port: int) -> list[str]:
```

Rationale (mantido para auditoria futura):
1. `guarded_backend_factory` tem de **devolver** um backend, não uma coroutine que o produz. Como
   coroutine, é instalada como `_pool._network_backend` e o httpcore morre com
   `'coroutine' object has no attribute 'connect_tcp'`.
2. `safe_http.py:126` faz `await asyncio.wait_for(self._resolver(host, port), ...)` — o resolver
   tem de ser awaitable. Sendo sync, `wait_for` levanta `TypeError`, convertido em
   `ConnectError("Public DNS resolution failed")` — falha fechada, mas **antes** do hop de redirect.

**Nenhum assert foi alterado.** Com estas 2 correcções os 2 testes passam (verificado 2×: pelo
`evidence/ssrf_redirect_probe.py` e pela suite completa). Isto **aumenta** a rigor, não a reduz (I-8).

## Fora de scope nesta sessão

Benchmark T1–T12 e soak: `BLOCKED` por `HORAS_TOTAIS` vazio (ASSUMPTION-01) e por NX-ENV-001.
Nenhuma conclusão sobre autonomia de modelos pequenos é possível: `SUT_MODELOS_LOCAIS` vazio.