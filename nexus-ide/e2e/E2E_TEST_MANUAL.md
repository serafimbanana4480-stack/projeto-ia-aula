# E2E Manual Tests — NEXUS IDE

Roteiro de testes manuais end-to-end para validar o ciclo completo de autonomia e fluxos críticos do usuário.

---

## Pré-requisitos

- Backend running em `http://localhost:8000`
- Frontend running em `http://localhost:3000`
- Ollama running em `http://localhost:11434` com modelos instalados
- Docker disponível (para code executor sandbox)

---

## Chat Flow Tests

### Cenário 1: Chat Básico

**Objetivo:** Verificar que o chat funciona para queries simples.

**Passos:**
1. Abrir frontend no browser em `http://localhost:3000`
2. Selecionar modelo (ex: qwen3.5:4b) no painel de modelos
3. Enviar query: "Quanto é 2+2?"
4. Verificar que a resposta é correta ("4")
5. Verificar que o streaming de tokens funciona (texto aparece gradualmente)

**Resultado Esperado:**
- ✅ Resposta correta
- ✅ Streaming funcional
- ✅ Sem erros no console do browser

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

### Cenário 2: Chat com Modo Auto

**Objetivo:** Verificar o ciclo completo Plan→Execute→Verify→Iterate.

**Passos:**
1. Abrir frontend
2. Selecionar modo "auto" no painel de configuração
3. Enviar query: "Cria uma função Python que soma dois números com testes unitários"
4. Verificar que o sistema cria um plano estruturado
5. Verificar que o agente CODER escreve o código
6. Verificar que o agente DEBUGGER verifica o código
7. Verificar que o resultado final é funcional

**Resultado Esperado:**
- ✅ Plano criado com steps
- ✅ CODER escreve código
- ✅ DEBUGGER executa verificação
- ✅ Código final funcional

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

### Cenário 3: Chat com Project Context

**Objetivo:** Verificar que o CODER pode ler ficheiros do projeto.

**Passos:**
1. Criar ou abrir um projeto existente
2. Navegar para um ficheiro existente no editor
3. Enviar query no chat: "O que faz a função neste ficheiro?"
4. Verificar que o CODER lê o ficheiro
5. Verificar que a resposta é correta baseada no conteúdo do ficheiro

**Resultado Esperado:**
- ✅ CODER lê o ficheiro
- ✅ Resposta correta
- ✅ Sem erros de path traversal

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

## Dashboard Tests

### Cenário 1: Métricas em Tempo Real

**Objetivo:** Verificar que o dashboard mostra métricas atualizadas.

**Passos:**
1. Abrir dashboard em `http://localhost:3000/dashboard`
2. Verificar que métricas aparecem (tasks completed, failed, latency)
3. Enviar algumas queries no chat
4. Verificar que métricas atualizam em tempo real
5. Parar o backend
6. Verificar que aparece indicador "OFFLINE — Dados de exemplo"
7. Reiniciar o backend
8. Verificar que dados reais aparecem novamente

**Resultado Esperado:**
- ✅ Métricas atualizam em tempo real
- ✅ Indicador "OFFLINE" aparece quando backend desconectado
- ✅ Dados reais aparecem quando backend reconectado
- ✅ Não há mistura de dados mock com reais

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

### Cenário 2: Agent Activity

**Objetivo:** Verificar que o dashboard mostra atividade dos agentes.

**Passos:**
1. Enviar query complexa no chat (modo auto)
2. Verificar dashboard mostra agentes ativos (CODER, DEBUGGER, ANALYZER)
3. Verificar contadores de tasks completed/failed
4. Verificar latência média

**Resultado Esperado:**
- ✅ Dashboard mostra agentes ativos
- ✅ Contadores atualizados
- ✅ Latência média visível

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

## Editor Tests

### Cenário 1: Editar Ficheiro

**Objetivo:** Verificar que o editor funciona e o CODER pode ler ficheiros editados.

**Passos:**
1. Abrir editor
2. Navegar para um ficheiro existente
3. Editar o ficheiro (adicionar código)
4. Verificar que mudanças são salvas
5. Enviar query no chat: "Lê o ficheiro X e explica o que faz"
6. Verificar que CODER lê a versão editada

**Resultado Esperado:**
- ✅ Editor salva mudanças
- ✅ CODER lê ficheiro editado
- ✅ Resposta correta baseada em versão editada

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

## Terminal Tests

### Cenário 1: Executar Comando

**Objetivo:** Verificar que o terminal funciona e o code executor sandbox está operacional.

**Passos:**
1. Abrir terminal no frontend
2. Executar comando simples: `echo "hello"`
3. Verificar output correto ("hello")
4. Executar comando Python: `python -c "print(2+2)"`
5. Verificar output "4"

**Resultado Esperado:**
- ✅ Comando bash funciona
- ✅ Comando Python funciona
- ✅ Output correto

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

### Cenário 2: Timeout e Erros

**Objetivo:** Verificar que o sandbox impede comandos perigosos e respeita timeouts.

**Passos:**
1. Executar comando longo: `sleep 60` (com timeout 5s)
2. Verificar que timeout funciona (comando é interrompido)
3. Executar comando com erro: `python -c "1/0"`
4. Verificar que erro é capturado e mostrado
5. Tentar comando perigoso: `rm -rf /` (deve ser bloqueado)

**Resultado Esperado:**
- ✅ Timeout funciona
- ✅ Erros são capturados
- ✅ Comandos perigosos são bloqueados

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

## Autonomy Cycle Tests

### Cenário 1: Ciclo Completo Plan→Execute→Verify→Iterate

**Objetivo:** Validar o ciclo completo de autonomia com uma tarefa real.

**Passos:**
1. Enviar query: "Cria uma calculadora em Python com operações básicas e testes"
2. Verificar que o sistema cria um plano
3. Verificar que o plano tem múltiplos steps (implementação, testes, verificação)
4. Verificar que os steps executam em paralelo quando possível
5. Verificar que o DEBUGGER é chamado para verificação
6. Verificar que iterações de correção funcionam se houver erros
7. Verificar que o ANALYZER faz revisão final
8. Verificar que o resultado final é funcional

**Resultado Esperado:**
- ✅ Plano criado
- ✅ Steps executam em ordem correta
- ✅ Paralelismo quando possível
- ✅ DEBUGGER verificação
- ✅ Iterações de correção
- ✅ ANALYZER revisão final
- ✅ Resultado funcional

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

## Smart Router Tests

### Cenário 1: Roteamento por Tipo de Query

**Objetivo:** Verificar que o smart router seleciona o modelo correto.

**Passos:**
1. Enviar query trivial: "Quanto é 2+2?"
   - Verificar que usa modelo micro (qwen2.5:0.5b)
2. Enviar query de código: "Cria uma função Python"
   - Verificar que usa modelo coder (qwen2.5-coder:7b)
3. Enviar query de reasoning: "Explica passo a passo como funciona"
   - Verificar que usa modelo reasoning (deepseek-r1:8b)
4. Enviar query complexa: longa (>100 palavras)
   - Verificar que usa modelo deep (qwen2.5:32b)

**Resultado Esperado:**
- ✅ Queries triviais → micro
- ✅ Queries de código → coder
- ✅ Queries de reasoning → reasoning
- ✅ Queries complexas → deep

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

## Tool Tests

### Cenário 1: Web Search Tool

**Objetivo:** Verificar que a ferramenta web_search funciona.

**Passos:**
1. Enviar query: "Pesquisa na web sobre Python 3.12"
2. Verificar que o agente usa a ferramenta web_search
3. Verificar que resultados são retornados
4. Verificar que a resposta é baseada nos resultados da pesquisa

**Resultado Esperado:**
- ✅ web_search é chamada
- ✅ Resultados são retornados
- ✅ Resposta usa resultados

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

### Cenário 2: File Operations Tool

**Objetivo:** Verificar que as ferramentas file_ops funcionam.

**Passos:**
1. Enviar query: "Cria um ficheiro test.txt com conteúdo hello"
2. Verificar que o agente usa write_file
3. Verificar que o ficheiro é criado
4. Enviar query: "Lê o ficheiro test.txt"
5. Verificar que o agente usa read_file
6. Verificar que o conteúdo é retornado corretamente

**Resultado Esperado:**
- ✅ write_file funciona
- ✅ Ficheiro criado
- ✅ read_file funciona
- ✅ Conteúdo correto

**Status:** ⬜ PASS / ⬜ FAIL

**Notas:**
- Data: ___/___/___
- Browser: ___________
- Screenshots: ___________

---

## Bugs Encontrados

Durante os testes E2E, documentar bugs encontrados:

| Bug ID | Descrição | Severidade | Status |
|--------|-----------|------------|--------|
| BUG-001 | | | ⬜ OPEN / ⬜ FIXED |
| BUG-002 | | | ⬜ OPEN / ⬜ FIXED |
| BUG-003 | | | ⬜ OPEN / ⬜ FIXED |

---

## Resumo de Execução

**Data de execução:** ___/___/___

**Tester:** ___________

**Ambiente:**
- Backend version: ___________
- Frontend version: ___________
- Ollama models: ___________
- Docker version: ___________

**Resultados:**
- Total cenários: __
- PASS: __
- FAIL: __
- Taxa de sucesso: __%

**Recomendações:**
- ________________________________________________
- ________________________________________________
- ________________________________________________
