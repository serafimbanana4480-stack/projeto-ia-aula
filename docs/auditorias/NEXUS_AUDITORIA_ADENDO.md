# Adendo à auditoria — verificação da própria auditoria

**Data:** 16 de agosto de 2026 · complementa `NEXUS_AUDITORIA_2026-08-16.md`

Pediste-me para verificar se respondi de forma completa, se fiz mesmo o que disse e se
falhei algo importante. Fiz esse exercício com verificações reais, não por leitura.
Resultado: **1 defeito grave que falhei, 2 afirmações minhas erradas, e 4 requisitos teus
que não cobri.**

---

## 1. Retratações — coisas que disse mal

### R1. "Literal `Infinity` renderizado no canto inferior esquerdo" (era P9e) — **FALSO**

`Infinity` é o botão do **Infinity Suite** (modos avançados), com ícone próprio.
`frontend/components/chat/AdvancedModeSelector.tsx:291` → `<span>Infinity</span>`,
`title="Advanced Modes (Infinity Suite)"`. É funcionalidade, não bug.
**Reportei uma feature como defeito. Retiro P9e.**

### R2. "`spawn_task` rejeita `priority: 2`" — **erro meu, não do NEXUS**

O schema declara `priority` como `string` com enum `low|medium|high|critical`. O meu
stub enviou o inteiro `2`. A rejeição (`arguments.priority has invalid type`) foi
**validação correta**. Corrigi os argumentos e repeti — foi aí que encontrei o defeito
real, o P10 abaixo.

### R3. Contadores de tokens a zero (P9d) — **mantém-se, mas a causa era outra**

Suspeitei que fosse culpa do meu stub. Verifiquei: o NEXUS **nunca envia
`stream_options: {include_usage: true}`** nos pedidos de streaming
(`backend/llm/openai_provider.py` não tem a chave; o pedido registado tem só
`model, messages, stream, tools, max_tokens, temperature`). Um provider
OpenAI-compatible não devolve `usage` num stream a menos que lho peçam. O defeito é do
NEXUS e agora tem causa-raiz identificada.

---

## 2. Re-verificação do defeito principal (P1)

Antes de acrescentar coisas novas, testei se tinha exagerado. Marquei a 1ª resposta com
`ALFA` e a 2ª com `BETA` e procurei os marcadores em **todos os campos de todos os
eventos** do stream SSE:

```
routing         ALFA=False BETA=False
agent_started   ALFA=False BETA=False
progress        ALFA=False BETA=False   'li 3 ficheiro(s)'
progress        ALFA=False BETA=False   '6 entradas na raiz do projeto...'
token           ALFA=False BETA=True    'AUDITORIA-MARCADOR-BETA'
metric          ALFA=False BETA=False
agent_finished  ALFA=False BETA=False
done            ALFA=False BETA=False

Ocorrências de ALFA (resposta real) em TODO o stream: 0
```
A resposta real não está escondida num `thinking`, num acordeão colapsado nem em campo
nenhum. **P1 confirmado, não exagerado.**

---

## 3. O defeito que falhei

### P10 — `spawn_task` diz "spawned" quando a delegação foi negada *(crítico)*

**Problema**
A política de spawn nega a delegação, mas a ferramenta devolve ao modelo um resultado a
dizer que o sub-agente foi criado e está a correr em background. Nenhum sub-agente
arranca. O modelo é levado a reportar ao utilizador trabalho que nunca vai existir.

**Prompt que causou o erro**
`Delega a analise profunda do modulo de scoring a um sub-agente ANALYZER.`
(tool call válida: `spawn_task{name:"analisar-scoring", agent:"ANALYZER", priority:"high", context:"..."}`)

**Resposta obtida** — dois sinais contraditórios no **mesmo run**:

Runtime (seq 5) — negado:
```
status_update | "o agente primário trata isto: analisar-scoring"
reason: "the primary agent handles this directly: no concrete objective..."
```
Resultado devolvido ao modelo — afirma sucesso:
```json
{"status": "spawned", "task_name": "analisar-scoring", "agent": "ANALYZER",
 "priority": "high", "background": true, "instance_id": "3dcb5ee231ab4a53",
 "message": "ANALYZER continua em background; a conversa principal permanece livre."}
```

**Comportamento esperado**
`{"status": "denied", "reason": "..."}` — a ferramenta tem de refletir a decisão da
política. Um modelo honesto só pode ser honesto se as ferramentas lhe disserem a verdade.

**Causa encontrada**
Divergência entre a `SpawnPolicy` (`backend/runtime/spawn_policy.py`, default
`PRIMARY_AGENT_ONLY`) e o handler de `spawn_task` no registry de tools: a política decide
no runtime, a tool constrói a resposta de sucesso independentemente dessa decisão.
Não há caminho de retorno da decisão para o resultado da ferramenta.

**Evidência**
- Zero eventos `agent_started` com `agent=ANALYZER` (a única ocorrência da string está
  dentro do próprio resultado ecoado).
- `GET /api/tasks` → `{"detail":"Not Found"}` — não há sequer lista onde verificar.
- `instance_id` gerado para um processo inexistente.

**Componente responsável**
`backend/tools/` (handler de `spawn_task`) ↔ `backend/runtime/spawn_policy.py`.

**Como reproduzir**
`POST /api/chat` com `autonomous:true`; fazer o modelo emitir uma `spawn_task` válida.
Comparar o evento `status_update` com o `tool_result`.

**Confiança na conclusão: 96%**

*Porque é grave:* é a categoria que pediste explicitamente para caçar — o sistema **diz
que executou** algo que não executou. Ao contrário do P8 (onde o modelo mente), aqui é a
**própria infraestrutura** a mentir ao modelo. Nenhum prompt de honestidade corrige isto.

---

### P11 — Modo SWARM expõe o protocolo interno em cru, sempre *(crítico)*

**Problema**
No modo SWARM os `<event>` tags nunca são parseados. O utilizador recebe o protocolo
interno como se fosse a resposta — em **todos** os runs, não em casos raros.

**Prompt que causou o erro**
`Analisa o projeto taskflow em profundidade com varios agentes.` (`mode: "swarm"`,
`swarm_strategy: "divide"`)

**Resposta obtida** (texto final, literal)
```
✅ Concluído em 3.6s (5 tokens).
✅ Concluído em 6.2s (5 tokens).
<event>thinking|iteration:1</event><event>warning|Resultado provisório — a executar
auditoria autónoma de melhorias</event><event>thinking|iteration:2</event>AGENTE-D-RESPOSTA<event>answer</event>
<event>thinking|iteration:1</event><event>warning|Resultado provisório — ...</event>...
```

**Comportamento esperado**
Texto limpo por agente, com o raciocínio em eventos estruturados.

**Causa encontrada**
Mesma raiz do P2 (sinalização *in-band*), mas aqui **incondicional**: o caminho SWARM
agrega as saídas dos agentes sem as passar pelo `_IncrementalResponseParser`, por isso os
`<event>` viajam intactos até ao ecrã. Confirma que o P2 não é um caso de fronteira — é
estrutural.

**Evidência**
5 × `agent_started` (SWARM, ARCHITECT, ANALYZER ×2, SWARM) mas só 4 chamadas ao modelo;
`AGENTE-D-RESPOSTA` aparece **duplicado**, com o bloco inteiro repetido — dois agentes
mostram a mesma resposta. O `✅ Concluído` declara sucesso para saídas que são lixo.

**Componente responsável**
`backend/orchestrator/swarm.py` + agregação no caminho `mode=swarm` de `routes/chat.py`.

**Como reproduzir**
Qualquer prompt com `"mode": "swarm"`. Reproduz 100% das vezes.

**Confiança na conclusão: 95%**

---

### P12 — `consult_agent` contamina a resposta do agente principal *(grave)*

**Problema**
A resposta do sub-agente consultado contém `<event>` tags. Ao ser injetada no fluxo do
agente principal, quebra o parser deste e a envelope A2A em JSON cru chega ao utilizador.

**Prompt que causou o erro**
`Delega a analise (...) e consulta o DEBUGGER sobre o teste que falha.`
(tool call: `consult_agent{agent:"DEBUGGER", question:"Porque falha o teste de paginacao?"}`)

**Resposta obtida** (texto final)
```
AUDIT-COORD", "a2a_message_id": "c93d800886f7455c", "a2a_correlation_id":
"cc5aa273800b450e", "a2a_task_type": "debugging", "timed_out": false, "evidence":
{"kind": "a2a_consultation", "verified": true, ...}}</event>OVF2
```

**Comportamento esperado**
A resposta do DEBUGGER em texto, ou um erro claro.

**Causa encontrada**
`tool_result` do `consult_agent` = `{"response": "<event>warning|Resultado provisório —
a executar auditoria autónoma de melhorias..."}`. É P1 + P2 em cascata: o sub-agente
corre a sua própria passagem de auditoria (P1 multiplica-se por sub-agente) e emite
`<event>` tags que rebentam o parser do pai (P2).

**Componente responsável**
`backend/tools/agent_comm.py` (A2A) + `_IncrementalResponseParser`.

**Como reproduzir**
Qualquer `consult_agent`.

**Confiança na conclusão: 93%**

---

## 4. O que NÃO cobri (honestamente)

Contra os teus 14 pontos:

| # | Requisito | Estado |
|---|---|---|
| 1 | Arquitetura completa | **Parcial.** Mapeei chat/runtime/agents/tools/triage/providers. **Não** li a fundo: subsistema de memória, dashboard agent, conectores MCP, editor Monaco, terminal xterm.js |
| 2 | Usar a UI real | ✅ Feito (Playwright, login, seleção de projeto, chat, captura de rede) |
| 3 | "Muitos" prompts, dificuldade crescente | **Parcial.** ~20 e2e + 24 de triage. Poucos para o que pediste, e a progressão parou em tarefas de ~7 passos |
| 4 | Tarefas reais de programação (12 itens) | **7/12.** Feitos: localizar funções, executar comandos, executar testes, terminal, contexto do projeto, continuar tarefas, multi-passo. **Não feitos:** analisar vários ficheiros relacionados, explicar código, perceber arquitetura, interpretar erros/stacktraces |
| 5 | Não inventa ficheiros/funções/resultados | ✅ (P8, e agora P10 que é pior) |
| 6 | Variações: simples/complexos/ambíguos/mal escritos/longos | ✅ Feito na triage; **só parcialmente** end-to-end |
| 7 | Verificar contra código/ficheiros/terminal/logs/testes/API | ✅ Feito |
| 8 | Investigar bloqueios até à causa | ✅ Feito |
| 9 | Confirmar afirmações de execução | ✅ Feito — e é onde estava o P10 que falhei |
| 10 | Tarefas consecutivas | ✅ 3 turnos |
| 11 | Projetos pequeno / médio / grande | **Parcial.** Pequeno (13 ficheiros) e grande (repo NEXUS). **Não construí um projeto médio** — não sei onde a qualidade começa a degradar |
| 12 | Achar info certa sem carregar lixo | **Não testado a sério** |
| 13 | Vários agentes/tools, coordenação | **Estava por fazer.** Fi-lo agora → P10, P11, P12 |
| 14 | Não corrigir automaticamente | ✅ Respeitado — não alterei uma linha do teu código |

Erro de método que reconheço: **encerrei o relatório antes de cobrir o ponto 13.** O
ponto 13 continha o defeito mais grave de todos os que encontrei (P10). Escrevi
"auditoria concluída" com 4 requisitos por fechar — precisamente o comportamento que
critiquei no NEXUS.

---

## 5. Formato

Pediste um bloco de 9 campos por problema (Problema / Prompt / Resposta obtida /
Comportamento esperado / Causa / Evidência / Componente / Como reproduzir / Confiança).
O relatório principal não seguiu esse formato de forma consistente — P1–P8 têm a maior
parte dos campos mas fora da estrutura, e os itens de P9 quase nenhum. Os P10–P12 acima
seguem o formato pedido. Se quiseres, reescrevo P1–P9 no mesmo molde.

---

## 6. Pontuações revistas

A coordenação multi-agente estava por testar quando pontuei. Está pior do que assumi.

```
                                    antes  →  agora
Funcionamento geral:                 45    →   40/100
Programação em projetos locais:      35    →   32/100
Compreensão do projeto:              55    →   55/100
Contexto:                            40    →   40/100
Memória:                             45    →   45/100
Uso de tools:                        65    →   45/100   (spawn_task mente; consult_agent corrompe)
Execução no terminal:                55    →   55/100
Qualidade das respostas:             20    →   18/100
Autonomia:                           40    →   30/100   (delegação não funciona e não o admite)
Confiabilidade:                      25    →   20/100

Pode ser usado autonomamente em projetos locais reais?
NÃO  (inalterado, com mais fundamento)
```

**Principais problemas (lista atualizada)**
1. P1 — a resposta do modelo é descartada e substituída por uma auditoria cega ao contexto.
2. P2/P11/P12 — sinalização *in-band*: em SWARM e em `consult_agent` acontece **sempre**, não em casos raros.
3. P10 — `spawn_task` devolve "spawned" quando a política negou. A infraestrutura mente ao modelo.
4. P3 — verificação verde sem correr um teste.
5. P4 — sem projeto selecionado, a UI aponta o agente ao repo do próprio NEXUS.
6. P5 — sem orçamento de contexto.

**O que mudou na conclusão**
A tese de fundo mantém-se e sai reforçada: os defeitos são de *plumbing*, não de
inteligência. Mas há um agravante que não tinha visto — **a camada de ferramentas
também reporta falsamente**. Enquanto o `spawn_task` disser "spawned" a uma delegação
negada, nenhum prompt de honestidade produz um agente honesto, porque o próprio agente
está a ser enganado.
