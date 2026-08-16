# NEXUS IDE — Auditoria end-to-end

**Data:** 16 de agosto de 2026
**Branch:** `codex/phase3-nexus-primary` (HEAD `34c7652`)
**Método:** stack completa (FastAPI + Next.js 15 + Chromium real) a correr num sandbox
isolado, com um endpoint OpenAI-compatible **instrumentado** a substituir o OpenRouter.
Esse endpoint regista o prompt exato que o NEXUS envia e devolve respostas guionadas —
o que permite separar *qualidade do modelo* de *qualidade do sistema*.

---

## 0. Limitação honesta desta auditoria

O sandbox não tem rota para `openrouter.ai`, `api.deepseek.com`, `huggingface.co` nem
`ollama.com` (só `pypi`, `npm`, `github`). Os modelos que tens localmente
(`foundry-qwen35-9b-q4-xl`, `qwen3.6`, `nomic-embed-text`) são grandes demais para
transferir. O desktop só concede terminal em modo *click* e browser em modo *read*, por
isso não foi possível conduzir a tua máquina.

**Consequência:** não meço a qualidade das respostas de um modelo real. **Meço tudo o
resto** — e, ao controlar o "modelo", consigo responder a uma pergunta mais útil:
*se o modelo for competente, o NEXUS entrega o resultado dele ao utilizador?*

A resposta é **não**. É o defeito nº 1 abaixo.

---

## 1. O que funciona bem

| Área | Evidência |
|---|---|
| Loop de ferramentas real | `read_file`, `list_dir`, `write_file`, `run_shell`, `execute_code`, `index_symbols`, `run_tests` executam de verdade e o resultado volta ao contexto |
| Escrita de ficheiros | `write_file` alterou o ficheiro no disco, criou backup em `.nexus/backups/` e devolveu `verified: true` |
| Sandbox de caminhos | `/etc/passwd` → `Access to system path '/etc' is blocked`; `/root/nx/app/.env` → `Access to sensitive component '.env' is blocked` |
| Allowlist de shell | `ls`, `python --version`, `pytest -q` passam; `python -c "..."` é recusado por desenho (vai para `execute_code`, que é sandboxed) |
| Tool call malformado | O backend diz explicitamente ao modelo: *"NOTHING was executed and NO file was created or changed. Do not claim otherwise."* — engenharia acima da média |
| Heartbeat SSE | 5 frames `: nexus-heartbeat` durante uma paragem de 75 s do provider; a stream não morre |
| Recuperação a vermelho | Testes falharam → `a recuperar: 0 passaram, 1 falharam` → nova ronda de observação |
| Histórico multi-turno | `role=user`/`role=assistant` persistem entre turnos; memória semântica recupera factos de conversas anteriores |
| Ordenação de eventos | Todos os frames trazem `run_id` + `seq` (trabalho da fase 2 mantém-se) |
| Erro do provider | Resposta vazia → `LLM stream failed: OpenAI stream completed without text content` em 0,38 s, sem run zombie |
| UI | Interface polida, streaming incremental, painel de atividade, mapa de contexto |

---

## 2. O que falha

### P1 — A resposta real do modelo é deitada fora *(crítico)*

**Prompt:** `Ha algum bug na paginacao do TaskRepo? Verifica no codigo.`

**O modelo produziu:**
> "Encontrei o bug: em `list_page` o offset é `page * size` em vez de `(page - 1) * size`,
> por isso a página 1 devolve os itens 11-20 e a primeira página nunca é alcançável.
> O teste `tests/test_repo.py::test_first_page_returns_first_items` falha por causa disto."

**O utilizador viu (UI real, screenshot):**
> `AUDIT: a auditoria nao encontrou mais nada a fazer.`

**Comportamento esperado:** a resposta do modelo chega ao utilizador.

**Causa (provada):** `backend/agents/base.py`, linha ~2219. Com `request.autonomous`
verdadeiro — que é o **default da UI** — a loop não emite a resposta final: acrescenta
`_AUTONOMOUS_COMPLETION_AUDIT` ao contexto e faz `continue`. A 2ª chamada torna-se
"a resposta". E essa 2ª chamada **não recebe a 1ª resposta no contexto**: os prompts
registados não têm uma única mensagem `role=assistant` dentro do turno. Pede-se ao
modelo para "auditar o resultado já produzido" sem lhe mostrar esse resultado.

**Evidência (3 turnos, respostas etiquetadas R1..R6):**
```
VISIVEL apos "pergunta um":  'R2-AUDIT'      (R1-ANSWER perdida)
VISIVEL apos "pergunta dois":'R4-AUDIT'      (R3-ANSWER perdida)
VISIVEL apos "pergunta tres":'R6-AUDIT'      (R5-ANSWER perdida)
histórico guardado: [user]pergunta um [assistant]R2-AUDIT ...
```
A resposta certa não é só escondida — **não fica no histórico**, por isso o modelo
também não se lembra dela no turno seguinte.

**Custo medido:**
```
autonomous=true  (default UI): 41 s → "AUDITORIA-SEM-CONTEXTO"   (errado)
autonomous=false             : 21 s → "RESPOSTA-REAL-DO-MODELO"  (certo)
```
**Duplica a latência e troca a resposta certa pela errada.** Com o teu qwen35-9b local
a ~40-60 s por chamada, isto é exatamente o atraso de ~2 minutos que descreveste.

**Reproduzir:** qualquer prompt pela UI. Comparar com `curl` a enviar `"autonomous": false`.

**Confiança: 99%.**

---

### P2 — Um ficheiro com `<tool_call>` ou `<thinking>` parte o chat *(crítico)*

**Prompt:** `le probe_thinking.py` (ficheiro de 3 linhas: `A = 1` / `MARK = "<thinking>"` / `B = 2`)

**Resposta obtida:**
```
<event>tool_result|read_file|{"path": "/root/nx/projects/taskflow/probe_thinking.py", "content": "A = 1\nMARK = ...
```
O protocolo interno e o conteúdo cru do ficheiro são renderizados como se fossem a
resposta do assistente. A resposta real do modelo desaparece **e o evento estruturado
`tool_result` nunca é emitido** (logo a loop perde a evidência da ferramenta).

**Isolamento controlado:**

| Ficheiro | `tool_result` emitido | Visível ao utilizador |
|---|---|---|
| 4000 linhas, sem markup | ✅ sim | resposta correta |
| 3 linhas com `<thinking>` | ❌ não | `<event>tool_result\|read_file\|{...` |
| 3 linhas com `<tool_call>` | ❌ não | `<event>tool_result\|read_file\|{...` |
| 3 linhas com `<event>` | ✅ sim | resposta correta |

**Não depende do tamanho** — depende do conteúdo.

**Causa:** sinalização *in-band*. `backend/agents/base.py` L2602 emite
`<event>tool_result|{tool}|{json}</event>` **no mesmo canal de texto** dos tokens do
modelo, sem escaping. O `_IncrementalResponseParser`
(`backend/orchestrator/routes/chat.py` L209-246) tem uma máquina de estados para
`<thinking>`/`<tool_call>` que corre antes do regex `_INLINE_EVENT_RE`; quando o payload
do evento contém esses marcadores, dessincroniza e o `<event>` já não casa.

**Impacto real:** apanha o **próprio repo NEXUS**, qualquer projeto de agentes,
qualquer repo de prompt engineering, e qualquer ficheiro de testes que mencione tags.

**Confiança: 98%.**

---

### P3 — Falso verde: verificação "passa" sem correr um único teste *(crítico)*

**Sequência:** o agente alterou `app/repos/task_repo.py` → a fase de verificação disparou
`run_tests` → resultado:
```json
{"status":"failed","returncode":1,"passed":0,"failed":0,
 "stderr_tail":"/usr/bin/python: No module named pytest\n"}
```
**Evento emitido ao utilizador:** `test_result | ok=True | "0 passaram, 0 falharam"`.

**Comportamento esperado:** "não consegui correr os testes" — nunca verde.

**Causa dupla:**
1. `backend/tools/test_runner.py` L49: `cmd = ["python", "-m", "pytest", *args]` — usa o
   `python` do PATH, **não** `sys.executable` nem o venv do projeto. No sandbox o backend
   corria em 3.12 e o PATH dava 3.11 sem pytest. Na tua máquina Windows, com o venv do
   projeto por ativar, dá o mesmo.
2. `backend/orchestrator/routes/chat_primary.py::_verify`:
   `ok = bool(raw.get("ok")) and int(payload.get("failed", 0) or 0) == 0`.
   Zero testes executados ⇒ `failed == 0` ⇒ **verde**.

Quando o pytest *existe*, a verificação funciona corretamente (`ok=False`,
`0 passaram, 1 falharam`) — o defeito é específico do caminho "não consegui executar".

**Confiança: 97%.**

---

### P4 — A UI sem projeto envia `project_path: "."` *(grave)*

Pedido capturado no browser:
```json
{"message":"O que faz app/repos/task_repo.py? Le o ficheiro.",
 "project_path":".", "mode":"auto", "thinking_strength":"low"}
```
O backend resolve `.` contra o CWD do processo → o **PROJECT STATE construído foi o do
próprio repo NEXUS**:
```
- raiz: .
- conteúdo da raiz: .dockerignore, .env, ARCHITECTURE.md, backend/, config/, frontend/ ...
--- README.md (início) --- # NEXUS IDE — IDE Assistida por IA ...
```
O cabeçalho diz "Sem projeto ativo — seleciona um projeto para usar ferramentas", mas
envia `"."` em vez de `""`. `chat_primary._snapshot_project` trata `""` como "sem
projeto" e `"."` como diretório válido. O agente trabalha no projeto errado **em
silêncio**. Nesse run o `read_file` falhou e a UI mostrou na mesma
**"Trabalho concluído ✓"** com "1 erro" escondido.

**Confiança: 96%.**

---

### P5 — Sem orçamento de contexto *(grave para modelos locais)*

Ler `backend/orchestrator/routes/chat.py` (4023 linhas) num projeto grande:
```
call 1:  23.985 chars (~6.000 tokens)
call 2:  32.259 chars (~8.000 tokens)
call 3: 203.454 chars (~50.900 tokens)   <- +45k só do resultado de UMA ferramenta
call 4: 203.888 chars (~51.000 tokens)
```
O bloco "Context from previous steps" cresce sem truncatura. Dois ficheiros destes
estouram 128k; **um** já estoura a janela típica de um modelo local quantizado. Existem
`context_budget.py` e `context_compressor.py` no repo, mas não estão neste caminho.

**Confiança: 95%.**

---

### P6 — `search_symbols` sem ranking e com mensagem enganadora *(médio)*

Depois de `index_symbols` (35 chunks, sucesso):

- `compute_priority_decay` → 8 resultados, **todos com `score: 1.0`**. A definição real
  (`app/utils/scoring.py`) aparece em **último**. Não há ranking; com `limit` num projeto
  grande, a definição fica de fora.
- `recalculate_sla_window` (símbolo **inexistente**) → `{"results": [], "message":
  "Codebase not indexed yet. Use the index_symbols tool to index the project first."}`
  — **na mesma sessão em que a indexação tinha acabado de correr com sucesso**.

O modelo não consegue distinguir "não existe" de "não indexado". É um motor de
alucinação: perante esta mensagem, um modelo razoável ou entra em loop a re-indexar ou
assume que o símbolo existe.

Os chunks `overview` guardam ainda uma reescrita **incorreta** dos imports:
`import datetime.datetime, timedelta` quando o ficheiro diz
`from datetime import datetime, timedelta`.

**Confiança: 94%.**

---

### P7 — Triage desequilibrada *(médio)*

| Prompt | Classe | Devia ser |
|---|---|---|
| `ola` | **direct** | conversational |
| `obrigado!` | **direct** | conversational |
| `podes ver se esta tudo bem?` | **conversational** | direct (não usa ferramenta nenhuma) |
| `audita o repositorio, implementa as correcoes, valida com testes e escreve um relatorio` | **direct** | planned |
| `Preciso de um plano completo para migrar de Flask para FastAPI...` | **direct** | planned |
| `isso` / `faz` / `arranja isto` | direct | pedir clarificação |

"Olá" desencadeia varrimento do projeto + 2 chamadas ao modelo. `PLANNED` exige ~30+
palavras **e** as 4 fases **e** alvo de projeto — na prática quase nunca dispara, o que
torna `_run_pipeline` (planner/architect/swarm) código morto no uso normal. Prompts
ambíguos nunca geram pedido de clarificação.

**Confiança: 93%.**

---

### P8 — Execuções falsas não são contestadas *(grave)*

**Prompt:** `Verifica se ha bugs no projeto e corre os testes.`

**Modelo respondeu (zero tool calls):**
> "Analisei todos os ficheiros do projeto, corri a suite de testes (4 passed) e confirmei
> que não há bugs. A função `recalculate_sla_window` em `app/services/sla.py` está correta."

Tudo inventado: nenhum ficheiro lido, nenhum teste corrido pelo modelo,
`app/services/sla.py` não existe, `recalculate_sla_window` não existe.

**O NEXUS correu a verificação por sua conta e obteve `0 passaram, 1 falharam`** — ou
seja, **sabia** que a afirmação era falsa. Mesmo assim entregou ao utilizador:
> `AUDIT: confirmado, tudo verificado.`

Existe uma guarda (`[TAREFA NÃO CONCLUÍDA] O agente terminou sem executar ferramentas
com evidência suficiente`) mas não disparou. Não há reconciliação entre o veredito da
verificação e o texto do modelo.

**Confiança: 92%.**

---

### P9 — Defeitos menores confirmados

| # | Problema | Evidência |
|---|---|---|
| a | `NEXUS_FREE_ONLY` = **true** por defeito. Sem catálogo de modelos grátis validado, o chat morre com `No validated healthy free provider satisfies the request` — **antes de qualquer chamada ao modelo** (0 pedidos no log) | reproduzido no arranque |
| b | Frontend não instala: `npm install` → ERESOLVE (`@monaco-editor/react@4.6.0` vs `react 19`); `pnpm 9` → `packages field missing or empty`. Só `pnpm 10` funciona | logs npm/pnpm |
| c | Nomes de agentes inconsistentes na UI: mensagens antigas aparecem como **ROUTER / "NEXUS IDE"**, novas como **NEXUS**; o modo `plan` mostra **ARCHITECT** | screenshots |
| d | Contadores de tokens sempre a `0` (ENTRADA 0 / SAÍDA 0) enquanto "Tools 380" | painel Sessão |
| e | Literal **`Infinity`** renderizado no canto inferior esquerdo em todas as páginas | screenshots |
| f | Tool call malformado / ferramenta inexistente: **nenhum evento** chega ao utilizador (o modelo é avisado, o utilizador não) | T3 |
| g | O aviso "tool call em formato inválido" nunca é limpo do contexto — persiste 5 chamadas depois, já com ferramentas bem-sucedidas pelo meio | T3 |
| h | Durante 75 s de paragem do provider o utilizador vê zero progresso (só heartbeats invisíveis) | T2 |
| i | `run_shell` corre com o `python` do PATH (3.11), diferente do backend (3.12) — mesmo problema-raiz do P3 | T-shell |
| j | `test_runner.py` define `_has_pytest_module` duas vezes (código morto) | L26 e L37 |

---

## 3. Testes existentes

`backend/tests/{runtime,orchestrator}` → **699 passaram, 10 falharam** (6m18s).

Verifiquei cada falha: **5 de `test_verification.py` são ambientais** —
`DiskPressureError: free_percent=4.61%, threshold_percent=5.00%` (o sandbox tinha pouca
folga de disco). **Não são defeitos de código.** As restantes são fixtures a colidir com
o backend que eu tinha a correr. Não encontrei regressões reais na suite.

Nota lateral: o `disk_guard` bloqueia escritas abaixo de 5% de disco livre. Num portátil
cheio, o NEXUS recusa trabalhar — comportamento correto, mas vale a pena saber.

---

## 4. Respostas às tuas perguntas

**Problemas com modelos locais** — o `_snapshot_project` + prompt de sistema já ocupam
~24k chars antes de qualquer ferramenta; um `read_file` de um ficheiro médio leva o
contexto a 50k+ tokens sem truncatura (P5). Um 9B q4 com janela de 8-32k não sobrevive.
Somando o P1, cada turno custa **duas** inferências completas.

**Problemas de contexto** — P4 (projeto errado), P5 (sem orçamento), P1 (a resposta do
modelo nunca entra no contexto da chamada seguinte dentro do mesmo turno).

**Problemas de memória** — o histórico multi-turno e a memória semântica funcionam,
mas guardam a **resposta errada** (o texto da auditoria em vez da resposta real, P1).
A memória está tecnicamente saudável e semanticamente corrompida.

**Problemas dos agentes** — o `NEXUS PRIMARY` é sólido; o problema está na camada
`agents/base.py` por baixo dele. Nomes inconsistentes (P9c). Delegação nunca testada
na prática porque o `PLANNED` quase não dispara (P7).

**Problemas das tools** — P3 (interpretador errado), P6 (ranking e mensagem),
P2 (resultado destrói a stream), P9f (falhas silenciosas).

**Problemas do terminal** — `run_shell` funciona com a allowlist mas usa o interpretador
errado (P9i). `execute_code` funciona bem e é sandboxed.

**Problemas de frontend/backend** — P4 é frontend; P1/P2/P3 são backend; P9c/d/e são
frontend.

**Respostas inventadas** — não observei o harness a inventar factos, mas observei-o a
**mostrar conteúdo que o modelo nunca produziu** (P2) e a **entregar afirmações falsas
que ele próprio já tinha desmentido** (P8).

**Execuções falsas** — P3 é a pior: o sistema declara verificação verde sem executar
nada.

**Onde perdeu contexto** — P1 (dentro do turno), P4 (projeto errado), P5 (overflow).

**Onde ficou bloqueado** — nunca ficou preso indefinidamente. Timeouts, heartbeats e
saída de erro comportaram-se bem em todos os cenários.

---

## 5. Veredito

```
Funcionamento geral:                45/100
Programação em projetos locais:     35/100
Compreensão do projeto:             55/100
Contexto:                           40/100
Memória:                            45/100
Uso de tools:                       65/100
Execução no terminal:               55/100
Qualidade das respostas:            20/100
Autonomia:                          40/100
Confiabilidade:                     25/100

Pode ser usado autonomamente em projetos locais reais?
NÃO
```

**Porquê "NÃO" e não "PARCIALMENTE":** os defeitos P1 e P3 são *silenciosos*. O sistema
não falha de forma visível — entrega a resposta errada com um visto verde. Uma
ferramenta que erra em voz alta é usável com cuidado; uma que erra em silêncio e diz
"Trabalho concluído ✓" não é.

**Principais problemas**
1. P1 — a resposta do modelo é descartada e substituída por uma auditoria cega ao contexto (duplica também a latência).
2. P2 — qualquer ficheiro com `<tool_call>`/`<thinking>` faz o protocolo interno vazar para o chat.
3. P3 — a verificação declara verde quando o pytest nem sequer arranca.
4. P4 — sem projeto selecionado, a UI aponta o agente ao repo do próprio NEXUS.
5. P5 — sem orçamento de contexto: inviabiliza modelos locais.
6. P8 — afirmações falsas do modelo não são contestadas, mesmo quando o sistema já as desmentiu.

**Principal limitação atual**
O `backend/runtime/` da fase 3 (loop, telemetria, scheduler, triage) está bem desenhado
e é sólido. Mas continua a assentar sobre o `agents/base.py` da fase 1 — 2831 linhas com
sinalização de controlo *in-band* e uma passagem de auditoria forçada que destrói a
resposta. **A fase 3 substituiu o orquestrador, não o executor.** É aí que está tudo o
que interessa.

**O que impede o NEXUS IDE de funcionar como uma IDE de IA realmente autónoma**

1. **A resposta certa não chega ao utilizador.** Enquanto P1 existir, nenhuma melhoria
   de modelo, contexto ou ferramentas é visível — o output é sempre substituído.
2. **A verificação não é fiável, logo a autonomia não é segura.** Autonomia = agir sem
   supervisão. Isso exige um verificador que nunca diga verde sem prova. Hoje diz.
3. **O canal entre executor e UI não é um protocolo.** Eventos de controlo e texto do
   modelo partilham a mesma stream sem escaping. Precisa de frames estruturados
   separados, não de tags no texto.
4. **Não há gestão de contexto no caminho real.** Sem truncatura de resultados de
   ferramentas e sem seleção de ficheiros, projetos grandes e modelos locais são
   incompatíveis por construção.
5. **Só o utilizador sabe qual é o projeto.** Enquanto `"."` for aceite como caminho
   válido, o agente pode trabalhar no repo errado sem que ninguém dê por isso.

Nenhum destes cinco é um problema de inteligência do modelo. São todos de plumbing —
o que é boa notícia: são reparáveis e verificáveis com testes.
