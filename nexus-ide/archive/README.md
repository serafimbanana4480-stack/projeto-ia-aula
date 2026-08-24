# Archive

Material histórico e artefactos de execução, mantido por decisão de **não apagar
nada**. Nada aqui é referenciado pelo código em produção nem pelos testes do
CI (`pytest` corre apenas `backend/tests`, ver `testpaths` no `pyproject.toml`).

| Pasta | Conteúdo | Origem |
|---|---|---|
| `cobaias-tools/` | Scripts "hello world"/sort usados como cobaias pelas file-tools do agente durante sessões de teste (`hello.py`, `hello_world.py`, `sorting*.py`, `sort_list.py` + o seu teste) | Raiz do `nexus-ide/` |
| `logs-execucao/` | Logs e outputs de execuções pontuais (`tsc2.txt`, `backend-audit-run.log`, `.backend-runtime.*.log`) | Raiz do `nexus-ide/` |
| `prototipos/` | Protótipos standalone substituídos por implementações reais (`cache.py` → substituído por `backend/cache/` + `backend/redis_cache.py`) | Raiz do `nexus-ide/` |
| `diagnosticos/` | Utilitários de diagnóstico one-off (`discover_env.py`) | Raiz do `nexus-ide/` |

## Regras

1. **Nunca importar** código daqui a partir de `backend/` ou `frontend/`.
2. Se um ficheiro aqui voltar a ser útil, move-o para o sítio certo
   (`scripts/`, `docs/`, etc.) em vez de o editar onde está.
3. Esta pasta pode ser eliminada por inteiro sem afetar o projeto — mas só
   por decisão explícita do dono do repositório.
