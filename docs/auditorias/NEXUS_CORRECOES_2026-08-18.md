# NEXUS IDE — o que estava partido, o que corrigi, e o que ficou provado

**Data:** 18 de agosto de 2026
**Base:** `main` @ `32a68fa` (contém a fase 3 — NEXUS PRIMARY, runtime, triagem)
**Entrega:** branch `codex/phase3-fixes` (2 commits por cima de `main`) + `_fixes/`
**Método:** stack real (FastAPI + `/api/chat` + NEXUS PRIMARY + loop ReAct + ferramentas
reais) contra um provider OpenAI-compatible **instrumentado**, que regista o prompt exato
enviado e devolve respostas guionadas. Ao controlar o "modelo", mede-se o **sistema**.

---

## 1. O ponto de partida

A auditoria de 16 de agosto encontrou 12 defeitos e deu um veredito duro:

> *"Os defeitos P1 e P3 são silenciosos. O sistema não falha de forma visível — entrega a
> resposta errada com um visto verde."* — Confiabilidade 20/100, autonomia 30/100.

A tese dessa auditoria era que **nenhum destes defeitos era de inteligência do modelo**:
eram todos de plumbing, e portanto reparáveis e verificáveis com testes. Foi exatamente
isso que fiz. Não mudei um único prompt de sistema para "pedir ao modelo que se porte
melhor" — mudei o que o sistema faz com o que o modelo produz.

Um critério guiou tudo:

> **O sistema nunca pode afirmar mais do que mediu.**

---

## 2. As correções, uma a uma

### P1 — a resposta do modelo era deitada fora *(crítico)*

**O que acontecia.** Com `autonomous=true` (o default da UI), o loop nunca emitia a
resposta produzida: acrescentava um pedido de "auditoria de melhorias" ao contexto e fazia
`continue`. A **segunda** resposta tornava-se "a resposta". Pior: essa segunda chamada não
recebia a primeira no contexto — pedia-se ao modelo para auditar um resultado que ele não
via. E o histórico guardava a auditoria, não a resposta.

**O que fiz.** Três mudanças em `backend/agents/base.py`:

1. A passagem de auditoria passa a **receber o resultado que audita**
   (`_render_answer_for_audit`), delimitado explicitamente no contexto.
2. A auditoria só substitui a resposta se **produziu nova evidência** — se executou mais
   ferramentas (`_reconcile_audited_answer`). Um veredito do género "não encontrei mais
   nada" deixa de apagar a análise real; uma auditoria com substância própria é anexada,
   não trocada.
3. A auditoria deixa de correr em turnos **só de leitura**. Uma pergunta respondida com
   `read_file` não tem nada para auditar e pagava uma segunda inferência completa. Quando
   nada foi executado, continua a correr — aí é a diferença entre afirmar e verificar.
   Configurável: `NEXUS_AUTONOMOUS_AUDIT_PASS=auto|off|always`.

Em modo de streaming os tokens da auditoria passam a ser retidos, para não aparecerem
colados por cima de uma resposta que o utilizador já leu.

**Medido (harness end-to-end):**

```
antes  visível: "AUDIT: a auditoria nao encontrou mais nada a fazer."   (resposta real perdida)
agora  visível: "RESPOSTA-REAL: o offset em list_page é page * size..."
antes  histórico: o texto da auditoria
agora  histórico: a resposta real
antes  2 inferências por turno de leitura (41s vs 21s medidos na auditoria)
agora  1 inferência
```

### P2 / P11 / P12 — o protocolo interno vazava para o chat *(crítico)*

**O que acontecia.** O loop emitia `<event>tool_result|read_file|{...}</event>` **no mesmo
canal de texto** dos tokens do modelo, sem escaping. Um ficheiro de três linhas que
mencionasse `<thinking>` ou `<tool_call>` dessincronizava o parser: o evento estruturado
desaparecia e o utilizador via o protocolo cru. No modo SWARM e em `consult_agent`
acontecia **sempre**, não em casos raros.

**O que fiz.** Um módulo novo, `backend/agents/event_protocol.py`, com o protocolo num só
sítio: `encode_event` escapa `&`, `<` e `>` no payload; `decode_payload` reverte;
`split_stream` separa texto de frames. Depois:

- o parser incremental (`routes/chat.py`) trata um frame completo como **atómico**, antes
  da máquina de estados de markup, e descarta um frame truncado em vez de o pintar no chat;
- o SWARM deixa de fazer `"".join(parts)` — os frames são transporte, não resposta (e um
  run que só produziu frames deixa de contar como "✅ Concluído");
- `consult_agent` e o runner de sub-agentes devolvem texto limpo ao agente pai.

**Verificado nos dois sentidos** — no código original, o mesmo input reproduz o defeito:

```
ANTES (código original)
  eventos: ['token', 'token', 'thinking', 'thinking']   <- tool_result nunca emitido
  visível: 'Vou ler o ficheiro. <event>tool_result|read_file|{"content": "A = 1\nMARK = ...'

AGORA
  eventos: ['token', 'tool_call', 'tool_result', 'token']
  visível: texto limpo, sem uma única tag
```

### P3 — falso verde: verificação "passa" sem correr um teste *(crítico)*

**O que acontecia.** `run_tests` chamava `["python", "-m", "pytest"]` — o `python` do PATH,
que na tua máquina com o venv por ativar não tem pytest. Resultado: `No module named
pytest` → 0 falhas → `ok=True` → **verde**. O JUnit XML ia para `/tmp/nexus-junit.xml`, um
caminho POSIX inválido em Windows.

**O que fiz.**

- `backend/tools/interpreters.py` (novo): resolve o interpretador por ordem —
  `NEXUS_PYTHON` → venv do projeto (`venv`/`.venv`, Windows e POSIX) → `sys.executable` →
  PATH.
- `run_tests` distingue agora **três** estados que antes eram um só:
  `not_run` (o runner não arrancou — nunca verde), `no_tests` (o projeto não tem testes —
  não é falha, mas também não é prova) e a execução real.
- `_verify` em `chat_primary.py` exige `executed`. Sem testes executados a resposta é
  `NÃO VERIFICADO: <razão>`, nunca "0 passaram, 0 falharam ✓".
- Removido o `_has_pytest_module` duplicado (P9j).

A distinção `no_tests` importa: tratá-lo como vermelho mandava o loop primário para um
ciclo de recuperação — uma segunda inferência completa — em perguntas só de leitura sobre
projetos sem suite. Encontrei isso a medir a minha própria correção.

### P4 — sem projeto selecionado, o agente trabalhava no repo do NEXUS *(grave)*

A UI enviava `project_path: "."`, que o backend resolvia contra o CWD do processo. O
`PROJECT STATE` construído era o do **próprio repositório do NEXUS**.

`frontend/lib/api.ts` deixa de ter `"."` como default e normaliza `"."`/`"./"`/`".\"` para
`""`. No backend, quando não há projeto e se recorre à raiz, o aviso passa a ser
`warning` (era `status: success`) e o modelo recebe uma instrução explícita para **não
escrever** aí.

### P5 — sem orçamento de contexto *(grave para modelos locais)*

`context += f"\nTool {tool} returned: {json.dumps(result)}"` — o resultado inteiro. Um
`read_file` de um ficheiro médio levava o contexto a 50k+ tokens; dois estouravam 128k.

Agora há um teto por resultado (`NEXUS_TOOL_RESULT_CONTEXT_CHARS`, 6000 por defeito), com
corte head+tail e um marcador que diz ao modelo o que foi omitido e como obter o resto —
e o proíbe explicitamente de afirmar ter lido o que não viu. A truncatura ataca primeiro
as strings grandes, para a estrutura (caminhos, flags, erros) sobreviver intacta.

**Medido:** ficheiro de 228 000 caracteres lido → maior prompt do turno **17 937
caracteres**. Antes: 203 454 numa só chamada.

### P6 — `search_symbols` sem ranking e com mensagem enganadora *(médio)*

Todos os resultados vinham com `score: 1.0` e a definição real aparecia em último; e um
símbolo inexistente devolvia *"Codebase not indexed yet"* na mesma sessão em que a
indexação tinha corrido com sucesso — um motor de alucinação.

Agora há ranking (match exato do nome → chunk que contém a definição → contenção → tipo
concreto → score → tamanho) e a mensagem distingue **"o índice está construído e este
símbolo não existe"** de **"ainda não indexado"**.

### P7 — triagem desequilibrada *(médio)*

Os dez casos que a auditoria listou classificam agora todos como esperado:

| Prompt | Antes | Agora |
|---|---|---|
| `ola` / `obrigado!` | direct (varrimento + 2 chamadas) | conversational |
| `podes ver se esta tudo bem?` | conversational | direct |
| `audita…, implementa…, valida…, escreve relatório` | direct | **planned** |
| `Preciso de um plano completo para migrar…` | direct | **planned** |
| `isso` / `faz` / `arranja isto` | direct (agia às cegas) | pede clarificação |

`PLANNED` exigia 25 palavras **e** 4 fases — na prática nunca disparava, o que tornava o
planeador código morto. Agora 3 fases bastam (10+ palavras), 2 fases num pedido longo
também, e "plano/roadmap/estratégia" por palavras vale como `/plan`. Um pedido sem alvo
concreto passa a `needs_clarification` e o agente faz **uma** pergunta curta em vez de
inventar um objetivo.

### P8 — execuções falsas não eram contestadas *(grave)*

O modelo dizia *"Analisei todos os ficheiros, corri a suite (4 passed)"* e o NEXUS —
que tinha medido `0 passaram, 1 falharam` — entregava aquilo na mesma.

`PrimaryLoop._unsupported_claims` compara agora o que a resposta **afirma** com o que o run
**mediu** (testes executados, ficheiros lidos, ficheiros alterados, sub-agentes iniciados)
e anexa uma correção visível, emitida como delta para o utilizador a ler mesmo:

> ⚠️ **Verificação do próprio NEXUS** — as afirmações seguintes não são suportadas pela
> evidência medida nesta execução:
> - diz que executou testes, mas nenhum teste foi executado nesta execução
> - diz que analisou ficheiros, mas nenhum ficheiro foi lido nesta execução

Os padrões são deliberadamente estreitos: uma resposta honesta ("a função usa um offset
errado; convém confirmares com um teste") não é marcada. Há teste para isso.

### P10 — `spawn_task` dizia "spawned" a uma delegação negada *(crítico)*

A `SpawnPolicy` negava, e a ferramenta devolvia ao modelo `{"status": "spawned",
"instance_id": "3dcb5ee2…"}` para um sub-agente que nunca existiu. *A própria
infraestrutura mentia ao modelo* — nenhum prompt de honestidade corrige isso.

`backend/runtime/spawn_registry.py` (novo) publica a política do run; `spawn_task`
consulta-a e devolve `denied` / `queued` / `not_started` com a razão, e só diz `spawned`
quando existe um `instance_id` real. O schema ganhou `definition_of_done` (obrigatório) —
sem isso a política negava tudo e o modelo não tinha como cumprir a condição.

### P9 — os defeitos menores

| # | Estado |
|---|---|
| a — `NEXUS_FREE_ONLY` mata o chat com erro opaco | erro agora **acionável**: nomeia o guard, os providers avaliados e as duas saídas (modelo local / `NEXUS_FREE_ONLY=false`). Não mexi no default: é uma proteção de custo, e mudá-la sem to perguntar podia gastar-te dinheiro |
| d — contadores de tokens sempre a 0 | duas causas corrigidas: o provider não pedia `stream_options: {include_usage: true}`, e a rota do NEXUS PRIMARY não emitia bloco `usage` nenhum |
| e — literal `Infinity` no canto | **era feature** (botão do Infinity Suite). O próprio adendo já o tinha retirado; confirmei e não toquei |
| g — aviso de formato nunca limpo do contexto | assim que o modelo emite uma tool call executável, a correção é esquecida (sticky directive + contexto) |
| i — `run_shell`/`execute_code` com interpretador errado | resolvido pelo mesmo `interpreters.py`; o caminho local do sandbox já usava `sys.executable` |
| j — `_has_pytest_module` duplicado | removido |
| b — frontend só instala com pnpm 10 | **não corrigido** (ver §5) |
| c — nomes de agentes inconsistentes na UI | parcialmente: a rota primária passa a emitir um `routing` completo, que é o que a UI lê para etiquetar a mensagem |
| f, h | ver §5 |

### Encontrados por mim, fora da lista da auditoria

Ao correr a suite completa apareceram regressões da fase 3 que ninguém tinha registado:

1. **Prompt injection deixou de ser bloqueado.** `detect_injection`, a validação do
   `session_id` e o limite de 50 000 caracteres viviam dentro de `_run_pipeline` — a via
   **legacy**. Todos os pedidos encaminhados para o NEXUS PRIMARY saltavam as três
   guardas. Passaram para a entrada, antes da escolha de via.
2. **Sessões e runs não eram persistidos na via primária.** Sem linha de sessão, o
   `/sessions/{id}/runs` respondia 404 e as ferramentas escreviam contra uma FK
   inexistente. Um turno cortado pelo limite de tokens do provider era indistinguível de
   um turno completo — a via legacy registava-o como `interrupted`.
3. **Truncatura do provider não era reportada** na via primária: agora há evento de aviso,
   nota na resposta e run marcado `interrupted`.
4. **Um turno sem resposta apagava a mensagem do utilizador** do histórico.
5. **Caminhos POSIX não eram reconhecidos** em pedidos: `_existing_directory_from_message`
   só entendia `C:\...`, portanto a imagem Docker e qualquer instalação Linux/WSL
   ignoravam silenciosamente o caminho colado.

---

## 3. Prova

### Suite de testes

```
                    antes            agora
passaram            2 508            2 551
falharam               33               25
```

**Zero falhas novas.** As 8 que desapareceram foram corrigidas de verdade (injeção,
truncatura, histórico auto-mode, routing, caminhos POSIX, config do dev server). As 25 que
restam são pré-existentes e ambientais — falham igualmente na árvore original: correm como
root sob `/root` (o `file_manager` bloqueia caminhos de sistema), `/usr/bin/python3` cai na
blocklist do `shell_runner`, Redis e `sentence-transformers` não estão instalados, e a
API do GitHub responde 403 sem token. Nenhuma é de código.

**43 testes novos**, em quatro ficheiros:

- `backend/tests/runtime/test_audit_2026_08_16_regressions.py` — um teste por defeito
  (P1, P2, P5, P7, P8, P9g, P10, P11, P12);
- `backend/tests/orchestrator/test_incremental_parser_protocol.py` — o parser contra
  conteúdo hostil, frames divididos entre chunks e frames truncados;
- `backend/tests/tools/test_verification_honesty.py` — pytest ausente / zero testes /
  passagem real / resolução de interpretador;
- e a correção dos testes que codificavam o comportamento antigo — o
  `test_spawn_task_keeps_declarative_fallback_without_runtime_manager` afirmava
  literalmente que `spawn_task` devia devolver `"spawned"` sem sub-agente nenhum. Reescrevi
  esse contrato em vez de o silenciar, com o porquê no docstring.

### Harness end-to-end

`backend/tests/e2e_audit_scenarios.py` corre a stack real com o provider instrumentado e
os prompts da auditoria. `python -m backend.tests.e2e_audit_scenarios`:

```
[PASS] P1 resposta do modelo entregue
[PASS] P1 memória guarda a resposta certa
[PASS] P1 custo por turno (pergunta de leitura)
[PASS] P2 ficheiro com marcadores do protocolo
[PASS] P3 verificação sem pytest
[PASS] P4 sem projeto selecionado
[PASS] P5 orçamento de contexto            (228k chars lidos -> prompt de 18k)
[PASS] P8 afirmações inventadas
[PASS] P10 delegação negada
[PASS] Execução longa (5 turnos)           5/5 corretas, 10/10 no histórico, prompt máx 13,5k

=== 10/10 cenários com o comportamento corrigido ===
```

O cenário de execução longa é o que responde à tua pergunta sobre funcionamento a longo
prazo: cinco turnos consecutivos, cada resposta certa entregue **e** guardada, com o maior
prompt a estabilizar nos 13,5k caracteres em vez de crescer sem limite.

---

## 4. Como aplicar

Está tudo no branch **`codex/phase3-fixes`**, dois commits em cima do teu `main` atual.
**Não toquei na tua árvore de trabalho** — e ainda bem, porque tens 12 ficheiros com
alterações por commitar, incluindo `backend/agents/base.py` (alguém está a mudar
`seen_tool_call_keys` → `successful_tool_call_keys`).

```bash
cd C:\Users\rodri\Desktop\nexus

# 1. guarda o trabalho em curso primeiro — é obrigatório, mexo no mesmo base.py
git stash push -m "wip antes das correcoes"

# 2. traz as correcoes (fast-forward, sem merge commit)
git merge --ff-only codex/phase3-fixes

# 3. devolve o teu trabalho; se houver conflito, é em base.py e em zonas diferentes
git stash pop

# 4. confirma
cd nexus-ide
python -m pytest backend/tests/runtime backend/tests/orchestrator -q
python -m backend.tests.e2e_audit_scenarios
```

Se preferires escolher hunk a hunk: `_fixes/nexus-fixes.patch` tem o diff completo
(`git apply -3 _fixes/nexus-fixes.patch`), e `_fixes/` tem os 28 ficheiros finais.

Duas notas sobre o repositório, que não são minhas mas vais tropeçar nelas:
`.git/index.lock` ficou de um processo que crashou a 16/08 às 23:27 (apaga-o quando
nenhum git estiver a correr), e `_to_delete/`, `_xfer/`, `_fixes/`, `_fixes2/` são pastas
de transferência que podes remover quando terminares.

---

## 5. O que **não** está feito

Digo-o em vez de o deixar implícito:

- **P9b — o frontend só instala com pnpm 10.** `@monaco-editor/react@4.6.0` não declara
  compatibilidade com React 19. Não mexi: a escolha entre fixar a versão, forçar
  `overrides` ou trocar de wrapper do Monaco é tua, e qualquer uma delas exige correr o
  frontend para validar — o que este sandbox não faz.
- **P9h — durante uma paragem longa do provider o utilizador não vê progresso.** Os
  heartbeats existem mas são invisíveis. Falta um watchdog que emita progresso visível ao
  fim de N segundos. É a melhoria de UX mais valiosa que ficou por fazer, exatamente para
  o teu caso (modelos locais a 40-60s por chamada).
- **P9f — falhas silenciosas de tool calls malformadas.** Melhorou (há `warning` e
  `tool_error`), mas não cobri todos os caminhos.
- **Qualidade das respostas do modelo.** Continuo sem medir isso: o sandbox não chega a
  `openrouter.ai` nem aos teus modelos locais. Meço o sistema, não o modelo — a diferença
  é que agora, se o modelo for competente, o resultado dele **chega-te**.
- **Não corri a UI real.** As correções de frontend (`api.ts`) estão cobertas por
  raciocínio e pelo contrato do backend, não por um clique no browser.

---

## 6. Onde isto deixa o NEXUS

A auditoria pontuou confiabilidade a 20/100 porque o sistema errava em silêncio. Os seis
mecanismos que produziam esse silêncio estão fechados, cada um com um teste que fica
vermelho se voltar:

1. a resposta certa chega ao utilizador e à memória;
2. o canal entre executor e UI é um protocolo com escaping, não tags soltas no texto;
3. a verificação não pode dizer verde sem ter executado;
4. as ferramentas não podem reportar trabalho que não fizeram;
5. as afirmações do modelo são reconciliadas com a telemetria;
6. o contexto tem um teto.

Não te dou uma pontuação nova: seria eu a avaliar-me a mim próprio no mesmo sítio onde a
auditoria anterior avaliou o código. O que te dou é o harness — corre-o quando quiseres,
com os teus modelos, e a pontuação sai dos números.
