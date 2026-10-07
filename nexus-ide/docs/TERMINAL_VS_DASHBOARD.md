# NEXUS Terminal vs NEXUS Dashboard

São **duas faces do mesmo produto**, não dois produtos.

| | NEXUS Dashboard | NEXUS Terminal |
|---|---|---|
| Onde corre | browser (localhost:3000) | shell local (este REPL) |
| Para quem | humanos que preferem UI | humanos/agentes que preferem teclado |
| Lançamento | `INICIAR_NEXUS.bat` (arranca backend + frontend + browser) | `nexus-terminal.bat` (só o terminal) |
| Backend | o mesmo (porta 8000/8001) | o mesmo |
| Modelos | os mesmos | os mesmos |
| Memória | a mesma (`.nexus/memory/`) | a mesma |
| Sessão | uma por separador | uma por invocação |
| Workers | sim (workers persistentes) | sim (workers persistentes) |
| Tools | sim | sim |
| Advisor | sim | sim |

## Quando usar o Terminal

- Estás a trabalhar via SSH / remote dev container
- Queres automatizar NEXUS (script, cron, pipe)
- Queres diff/grep/open/run dentro do mesmo loop
- Queres ver o thinking e os tool calls em tempo real sem perder o scroll
- Estás a delegar tarefas a workers em background e queres voltar mais tarde com `/wait`

## Quando usar o Dashboard

- Preferes ver artefatos, código, charts lado a lado
- Estás a rever uma sessão completa
- Queres drag-and-drop, multi-painéis, gestor de projetos
- Estás a mostrar o trabalho a alguém

## Coexistem

Podes ter Dashboard e Terminal abertos ao mesmo tempo. Apontam para o
mesmo backend, com sessões diferentes. O que um worker fizer, o outro
vê.

## Atalhos

- `INICIAR_NEXUS.bat` — arranca **só o Dashboard** (backend + frontend + browser)
- `nexus-terminal.bat` (raiz) — arranca **só o Terminal**
- `nexus-ide/nexus-terminal.bat` — mesmo que o anterior mas dentro de `nexus-ide`

## Comandos novos do Terminal v2

| Comando | Função |
|---|---|
| `/tree [depth] [path]` | árvore de pastas |
| `/open <ficheiro>` | abre com syntax highlight |
| `/grep <padrão> [--ext py,ts] [--path sub]` | procura texto em ficheiros |
| `/diff <ficheiro>` | diff git |
| `/patch <descrição>` | aplica patch via agente |
| `/run <cmd>` | executa shell na pasta do projeto |
| `/result <id>` | última resposta completa de um worker |
| `/clear` | limpa o ecrã |
| `/help` | ajuda completa, categorizada |
