# NEXUS-IDE Windsurf Cascade System

> Sistema de regras, workflows e prompts técnicos para maximizar a potência do Cascade no projeto NEXUS-IDE.

## Estrutura

```
.windsurf/
├── index.md           ← Este ficheiro (mapa do sistema)
├── rules.md           ← Regras persistentes por projeto (P0/P1/P2)
└── workflows/
    ├── plan.md        ← Planeamento com IA (arquitetura)
    ├── generate.md    ← Geração estruturada (implementação)
    ├── review.md      ← Revisão automática (bugs/performance)
    └── iterate.md     ← Iteração guiada (refactoring)
```

## Como Usar

### 1. Regras (rules.md)

As regras carregam **automaticamente** em cada sessão. Não precisas de fazer nada.

São organizadas por prioridade:
- **P0** = nunca violar
- **P1** = forte preferência
- **P2** = estilo/guia

### 2. Workflows (workflows/*.md)

Invoca um workflow com o nome do ficheiro ou descreve o que queres:

```
/plan "Adiciona um agente de review de código"
/generate "Implementa o agente DEBUGGER"
/review "backend/agents/debugger.py"
/iterate "Refactor router.py para reduzir complexidade"
```

Ou em português:
```
"Planeia como adicionar cache Redis ao router"
"Gera o código do novo agente ANALYZER"
"Revisa o módulo orchestrator por bugs"
"Refatora o debugger para função pura"
```

### 3. Pipeline Completo de Desenvolvimento

```
┌─────────┐    ┌──────────┐    ┌─────────┐    ┌──────────┐
│  PLAN   │ →  │ GENERATE │ →  │  REVIEW │ →  │ ITERATE  │
│  (IA)   │    │   (IA)   │    │  (IA)   │    │  (IA)    │
└─────────┘    └──────────┘    └─────────┘    └──────────┘
     ↑                                            ↓
     └──────────── feedback loop ←───────────────┘
```

**Fluxo recomendado:**
1. Começa com `/plan` para definir arquitetura
2. Segue com `/generate` para implementar ficheiro a ficheiro
3. Aplica `/review` para encontrar bugs e melhorar performance
4. Usa `/iterate` para refatoração contínua

### 4. Dicas de Prompts Técnicos

✅ **Bom** (específico, técnico):
- "Refatora para reduzir complexidade ciclomática abaixo de 10"
- "Transforma em função pura — extrai os efeitos secundários para um handler"
- "Aplica o pattern Factory para criar agents dinamicamente"
- "Adiciona rate limiting com sliding window no endpoint /chat"

❌ **Mau** (vago, genérico):
- "Faz isto melhor"
- "Melhora o código"
- "Otimiza"
- "Arranja bugs"

### 5. Contexto e Multi-File

Para maximizar o contexto:
- Mantém ficheiros organizados (< 300 linhas)
- Usa imports limpos e consistentes
- Divide código em módulos pequenos e coesos
- Nomeia ficheiros de forma clara (`agent_router.py` vs `utils.py`)

## Checklist de Qualidade (antes de cada resposta)

O Cascade aplica automaticamente:
- [ ] Respeita `rules.md` (P0/P1/P2)
- [ ] Verifica ficheiros existentes antes de criar novos
- [ ] Usa `edit`/`multi_edit` em vez de reescrever ficheiros inteiros
- [ ] Cita ficheiros com paths absolutos e números de linha
- [ ] Pergunta quando incerto (não adivinha)
- [ ] Sinaliza falhas de design antes de implementar

---

**Projeto:** NEXUS-IDE  
**Stack:** FastAPI · Next.js · Ollama · Redis · ChromaDB · OpenTelemetry  
**Arquitetura:** Multi-agente com routing inteligente e ReAct loop
