# D-15 — Raiz Canónica do Projeto NEXUS IDE

**Decisão (BLOCKING):**
```
RAIZ GIT CANÓNICA      = /mnt/c/Users/rodri/Desktop/nexus        (≡ C:\Users\rodri\Desktop\nexus)
SUB-DIRETÓRIO PROJETO  = /mnt/c/Users/rodri/Desktop/nexus/nexus-ide
ENTRYPOINT RUNTIME     = python -m uvicorn backend.orchestrator.main:app   (CWD = nexus-ide/)
```

> **A raiz canónica NÃO é `Desktop/nexus/nexus-ide/`.** O candidato "principal" da TAREFA é o
> **sub-diretório de projeto** dentro da raiz git real `Desktop/nexus`.

---

## 1. Prova da raiz git

### 1.1 Ambos os comandos apontam para o parent

Comando executado a partir de **cada um** dos diretórios candidatos:

```
$ cd /mnt/c/Users/rodri/Desktop/nexus/nexus-ide && git rev-parse --show-toplevel
/mnt/c/Users/rodri/Desktop/nexus

$ cd /mnt/c/Users/rodri/Desktop/nexus && git rev-parse --show-toplevel
/mnt/c/Users/rodri/Desktop/nexus
```

Saída bruta gravada em `../../../artifacts/closeout/logs/git-state-outer.txt` e
`git-state-parent.txt` (os dois contêm o **mesmo** bloco inicial: `--show-toplevel`,
`--abbrev-ref HEAD` → `cursor/bots-chat-v2-e082`, `HEAD` → `e12c214c232ac8619aa8c52ac46119ea444d0503`).

Conclusão: `Desktop/nexus` **é** um repositório git próprio (tem `.git/`), e
`Desktop/nexus/nexus-ide` **não** é raiz de repo — está dentro do repo do parent.

### 1.2 `nexus-ide/` é um subdiretório do repo parent (não um repo aninhado)

```
$ cd /mnt/c/Users/rodri/Desktop/nexus && git ls-files | head -5
.github/workflows/autonomy-soak.yml
.github/workflows/ci.yml
.gitignore
.kilo/agents/code-skeptic.md
.kilo/agents/frontend-specialist.md
```
```
$ cd /mnt/c/Users/rodri/Desktop/nexus && git ls-files nexus-ide/docs | wc -l
156
```
```
$ cd /mnt/c/Users/rodri/Desktop/nexus && git ls-files nexus-ide/backend | wc -l
(ver abaixo — ver secção 3)
```

O parent rastreia `nexus-ide/**` (156 ficheiros só em `nexus-ide/docs`), logo o código
do projeto está versionado pela raiz `Desktop/nexus`.

### 1.3 O parent NÃO é uma árvore de código duplicada

```
$ for d in backend frontend src app tests config; do [ -e "/mnt/c/Users/rodri/Desktop/nexus/$d" ] && echo "$d EXISTS" || echo "$d absent"; done
backend   : absent
frontend  : absent
src       : absent
app       : absent
tests     : absent
config    : absent
```

O parent só contém: `.github/workflows/`, `AGENTS.md`, `README.md`, `docs/`, `data/`
(`trace_lake.db` 12.9 MB + `runs/` 185 ficheiros), `.nexus/`, `deliverables/`,
`INICIAR_NEXUS.bat`, `NEXUS_TERMINAL.bat`, logs soltos e alguns diretórios
ignorados (`.kilo`, `_fixes`, `_fixes2`, `_to_delete`, `_xfer`, `.projectmind`,
`.opencode`, `.nexus-presentation-build`, `node_modules`).

Ou seja: o parent é a **raiz de CI/documentação/dados**, não uma cópia de código.

---

## 2. Qual árvore corre em runtime

### 2.1 `.github/workflows/ci.yml` declara a topologia (linhas 8-17)

```
# REPO LAYOUT — works from BOTH layouts without edits:
#
#   * nexus-ide/ IS the repository root          -> PROJECT_DIR=.
#   * nexus-ide/ is one level BELOW the repo root -> PROJECT_DIR=nexus-ide
#     (this is the layout today: the git root is C:/Users/rodri/Desktop/nexus)
#
# The "Locate project root" step decides at run time and exports PROJECT_DIR;
# every backend command runs from "$PROJECT_DIR", which is why all paths below
# are relative (`backend/tests/...`, `tools/ci/...`).
```

O CI ativo está no **parent** (`Desktop/nexus/.github/workflows/ci.yml` e
`autonomy-soak.yml`). O `.github/workflows/` do `nexus-ide/` não tem workflows
activos: os antigos estão preservados em `nexus-ide/archive/workflows/`
(incluíndo `ci-root-2026-10-06.yml`, ver comentário do próprio ci.yml linhas 3-7).

### 2.2 Scripts de arranque resolvem o CWD para `nexus-ide/`

`/mnt/c/Users/rodri/Desktop/nexus/INICIAR_NEXUS.bat` (linhas 4-5):
```bat
set RAIZ=C:\Users\rodri\Desktop\nexus
set IDE=%RAIZ%\nexus-ide
```
… e passo [4/6]:
```bat
start "NEXUS Backend" cmd /k "cd /d %IDE% && set BACKEND_HOST=127.0.0.1&& .venv\Scripts\python.exe -m uvicorn backend.orchestrator.main:app --host 127.0.0.1 --port 8000"
start "NEXUS Frontend" cmd /k "cd /d %IDE%\frontend && set NEXT_PUBLIC_API_URL=http://127.0.0.1:8000&& pnpm run dev"
```

`nexus-ide/start-nexus.bat` (WSL path `…/nexus-ide/start-nexus.bat`, portas **8001/3001**):
```bat
start "NEXUS Backend" cmd /k "cd /d C:\Users\rodri\Desktop\nexus\nexus-ide && ... .venv\Scripts\python.exe -m uvicorn backend.orchestrator.main:app --host 127.0.0.1 --port 8001"
start "NEXUS Frontend" cmd /k "cd /d C:\Users\rodri\Desktop\nexus\nexus-ide\frontend && ... pnpm run dev --hostname 127.0.0.1 --port 3001"
```

Nota de portas: `INICIAR_NEXUS.bat` usa **8000/3000**; `start-nexus.bat` usa **8001/3001**.
O timer do launcher do parent espera `/health` em `http://127.0.0.1:8000/health`.

`nexus-ide/Makefile` (linha 15-17):
```make
# NOTE: pytest targets run from the nexus-ide root (where pyproject.toml lives)
```
e o alvo `backend` documenta: *"NOTA: corre a partir da raiz do repo — `cd backend`
quebrava o import de `backend.orchestrator.main`"*.

`nexus-ide/STARTUP.md` secção "Starting the Servers": `cd nexus-ide` / `python -m backend.orchestrator.main`, backend em `:8000`.

### 2.3 Confirmação por resolução de módulos

Executado no venv Windows a partir de `C:\Users\rodri\Desktop\nexus\nexus-ide`:

```
$ ./.venv/Scripts/python.exe -c "os.chdir(r'C:\Users\rodri\Desktop\nexus\nexus-ide'); print(u.find_spec('backend.orchestrator.main').origin)"
resolved: C:\Users\rodri\Desktop\nexus\nexus-ide\backend\orchestrator\main.py
```

### 2.4 `docker/docker-compose.yml` usa `context: ..` e `../frontend`

```
$ grep -n "context:" nexus-ide/docker/docker-compose.yml
4:      context: ..
46:      context: ../frontend
```
Consistente com `nexus-ide/` a ser a raiz de build do projeto.

---

## 3. Divergência entre cópias

### 3.1 Árvore aninhada `nexus-ide/nexus/` — NÃO é duplicado de código

```
$ find /mnt/c/Users/rodri/Desktop/nexus/nexus-ide/nexus -mindepth 1 | sort
nexus/nexus-ide
nexus/nexus-ide/__init__.py

$ du -sh /mnt/c/Users/rodri/Desktop/nexus/nexus-ide/nexus
0	nexus

$ cat nexus/nexus-ide/__init__.py
# Make the directory a package so cache can be imported
```

Totais: **1 directório + 1 ficheiro (55 B)**. Comando:
`find nexus -mindepth 1 | wc -l` → **2**; `-type f` → **1**; `-type d` → **1**.

Comparação `backend/` outer vs. nested: **não aplicável** — a árvore aninhada não tem
`backend/`. Divergência = **0 ficheiros idênticos / 0 diferentes / 1 só-em-um-lado**
(o `__init__.py` só existe no lado "outer"). Confirmado também por contagem de
ficheiros em `nexus-ide/backend`: **5546 ficheiros** (excl. `__pycache__`/`.pytest_cache`/`.mypy_cache`/`.ruff_cache`), nenhum dos quais na árvore aninhada.

### 3.2 A árvore aninhada está rastreada pelo git (1 ficheiro)

```
$ cd /mnt/c/Users/rodri/Desktop/nexus && git ls-files nexus-ide/nexus
nexus-ide/nexus/nexus-ide/__init__.py
(count: 1)

$ git check-ignore -v nexus-ide/nexus/nexus-ide/__init__.py nexus-ide/nexus
(sem saída; rc=1)
```

Não há regra de `.gitignore` que a ignore: está **tracked**. Note-se que
`git check-ignore` no `.gitignore` do parent (linha com `.nexus/`) não a afeta porque
o caminho é `nexus-ide/nexus/`, não `.nexus/`.

### 3.3 Conclusão da divergência

| Par                                             | Ficheiros (outer) | Ficheiros (nested/outro) | Idênticos | Diferentes | Só num lado |
|-------------------------------------------------|------------------:|-------------------------:|----------:|-----------:|------------:|
| `nexus-ide/nexus/` (aninhada)                   | 1 (`__init__.py`) | 0                        | 0         | 0          | 1 (outer)   |
| `nexus-ide/backend/`                            | 5546             | n/a (não existe cópia)   | n/a       | n/a        | n/a         |
| `Desktop/nexus/` vs `nexus-ide/` (código)       | 0 (sem backend/frontend/src/app/tests/config) | 5546+ | 0 | 0 | todos em `nexus-ide/` |
| `/mnt/c/Users/rodri/nexus-nexus-ide` (cópia antiga) | — **NÃO EXISTE** (ver abaixo) | — | — | — | — |

```
$ ls -la /mnt/c/Users/rodri/nexus-nexus-ide
ls: cannot access '/mnt/c/Users/rodri/nexus-nexus-ide': No such file or directory
```

O candidato `/mnt/c/Users/rodri/nexus-nexus-ide` **não existe** neste sistema.

---

## 4. Processos em execução / portas

```
$ ps aux | grep -Ei 'uvicorn|nexus|next|node|python' | grep -v grep
root              312  0.0  0.1   107040  23096 ?      Ssl  21:57 00:00 /usr/bin/python3 /usr/share/unattended-upgrades/unattended-upgrade-shutdown --wait-for-signal
```
(1 linha; só o `unattended-upgrade` do sistema.)

```
$ ss -ltnp
LISTEN 0      4096    127.0.0.53%lo:53         0.0.0.0:*    users:(("systemd-resolve",pid=176,fd=15))
LISTEN 0      4096    127.0.0.54:53             0.0.0.0:*    users:(("systemd-resolve",pid=176,fd=17))
LISTEN 0      4096    127.0.0.1:33095           0.0.0.0:*    users:(("containerd",pid=233,fd=15))
LISTEN 0      1000    10.255.255.254:53         0.0.0.0:*
```

**Nenhum backend (`:8000`/`:8001`) nem frontend (`:3000`/`:3001`) está a correr**
(visto do lado WSL; estes são processos Windows e o WSL2 tem o seu próprio namespace
de rede por defeito — ver limitação abaixo). Nada a proteger contra acesso concorrente
aos ficheiros SQLite durante o backup.

### Limitação de verificação (explícita)

O `ps`/`ss` acima observam o namespace de rede do **WSL2**, não o do Windows host.
Um servidor NEXUS iniciado por `INICIAR_NEXUS.bat` corre no Windows e poderia estar
LISTENING sem aparecer aqui. **Não foi possível** inspecionar `/proc/<pid>/cwd` de
processos Windows a partir do WSL. No entanto: (a) as portas 8000/8001/3000/3001 não
respondem neste namespace; (b) nenhum ficheiro `*.db-wal` dos alvos de backup estava
a crescer no momento da cópia; (c) os `-shm`/`-wal` foram copiados em conjunto.

---

## 5. Resposta D-15 (bloqueante)

1. **Raiz git canónica:** `/mnt/c/Users/rodri/Desktop/nexus`
   (`git rev-parse --show-toplevel`, executado de ambos os diretórios → mesmo resultado).
2. **Diretório do projeto:** `/mnt/c/Users/rodri/Desktop/nexus/nexus-ide/`
   (subdiretório rastreado do repo parent; `git ls-files nexus-ide/docs | wc -l` → 156).
3. **Árvore que corre em runtime:** a **outer** `nexus-ide/` (CWD do uvicorn é
   `nexus-ide/`, confirmado por `INICIAR_NEXUS.bat`, `start-nexus.bat`, `Makefile`,
   `STARTUP.md`, resolução de `backend.orchestrator.main` →
   `…\nexus-ide\backend\orchestrator\main.py`, e `docker-compose.yml` `context: ..`).
4. **A árvore aninhada `nexus-ide/nexus/` NÃO é um duplicado de código:** 1 ficheiro,
   55 B, apenas `nexus/nexus-ide/__init__.py`. É resíduo.
5. **O parent NÃO é uma árvore de código duplicada:** não tem `backend/`, `frontend/`,
   `src/`, `app/`, `tests/`, `config/`. É raiz de CI/docs/dados (`.github/workflows/`,
   `README.md`, `AGENTS.md`, `docs/`, `data/trace_lake.db` 12.9 MB, `data/runs/`,
   `.nexus/`, `deliverables/`).
6. **Consequência operacional (aplicada):** o branch de trabalho
   `closeout/nexus-v3` e o worktree `nexus-baseline` foram criados a partir de
   `/mnt/c/Users/rodri/Desktop/nexus`; o projeto no worktree vive em
   `/mnt/c/Users/rodri/Desktop/nexus-baseline/nexus-ide/`.

---

## 6. Ficheiros de evidência

| Ficheiro | Conteúdo |
|---|---|
| `../../../artifacts/closeout/logs/git-state-outer.txt` | estado git correndo a partir de `nexus-ide/` (todos os comandos da TAREFA 1) |
| `../../../artifacts/closeout/logs/git-state-parent.txt` | estado git correndo a partir de `Desktop/nexus` (+ `git ls-files`, contagens) |
| `../../../artifacts/closeout/logs/git-status-INITIAL.txt` | `git status --porcelain=v1` inicial (278 linhas, SHA256 `78eae6c4…`) |
| `../../../artifacts/closeout/logs/git-status-AFTER-BRANCH.txt` | `git status` após criar branch/worktree |
| `../../../artifacts/closeout/logs/base-sha.txt` | branch anterior, base SHA, branch de trabalho |
| `../../../artifacts/closeout/logs/ps-listeners.txt` | `ps aux` filtrado |
| `../../../artifacts/closeout/logs/db-inventory.txt` | inventário de `*.db`/`*.sqlite3` |
| `../../../artifacts/closeout/logs/digest-outer-backend.txt` | sha256 de cada ficheiro de `nexus-ide/backend/` |
