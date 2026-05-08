# NEXUS-IDE — Windsurf Cascade Power System

Sistema de regras e workflows para transformar o Cascade de "ajudante genérico" em "engenheiro alinhado com o teu estilo".

## O que foi criado

| Ficheiro | Propósito |
|---|---|
| `.windsurf/index.md` | Mapa completo do sistema — como usar |
| `.windsurf/rules.md` | **Regras por projeto** com prioridades (P0/P1/P2) |
| `.windsurf/workflows/plan.md` | Planeamento com IA — arquitetura antes de codar |
| `.windsurf/workflows/generate.md` | Geração estruturada — ficheiro a ficheiro com validação |
| `.windsurf/workflows/review.md` | Revisão automática — bugs, performance, segurança |
| `.windsurf/workflows/iterate.md` | Iteração guiada — refactoring com prompts curtos |

## Como funciona

1. **Regras carregam automaticamente** em cada sessão Cascade
2. **Workflows invocam-se** com `/plan`, `/generate`, `/review`, `/iterate` ou descrevendo em português
3. **Pipeline:** Plan → Generate → Review → Iterate → (loop)

## Exemplos de uso

```
/plan "Adiciona um agente de review de código ao sistema"
/generate "Implementa o agente DEBUGGER segundo o plano aprovado"
/review "backend/agents/debugger.py"
/iterate "Refactor router.py para reduzir complexidade ciclomática abaixo de 10"
```

Ou em português livre:
```
"Planeia como integrar cache Redis no orchestrator"
"Gera o código do novo agente ANALYZER"
"Revisa o módulo orchestrator por bugs e race conditions"
"Refatora o debugger para função pura"
```
