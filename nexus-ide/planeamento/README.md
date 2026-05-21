# Planeamento Técnico NEXUS IDE

Este diretório contém toda a documentação técnica do projeto NEXUS IDE em português, organizada sequencialmente por tópicos.

## Índice

1. **[01-visao-geral.md](01-visao-geral.md)** - Visão geral, filosofia de design, objetivos e diferenciais competitivos
2. **[02-arquitetura-tecnica.md](02-arquitetura-tecnica.md)** - Stack tecnológico, justificativas, design detalhado
3. **[03-modelos-llm.md](03-modelos-llm.md)** - Seleção de modelos Ollama, trade-offs, matriz de modelos
4. **[04-agentes.md](04-agentes.md)** - Detalhes dos 9 agentes especializados, prompts, casos de uso
5. **[05-orchestrator.md](05-orchestrator.md)** - Motor de orquestração, routing, fallback, dependency graph
6. **[06-ferramentas-react.md](06-ferramentas-react.md)** - Ferramentas ReAct (web search, code executor, embeddings)
7. **[07-frontend.md](07-frontend.md)** - Arquitetura frontend, componentes, state management
8. **[08-observabilidade.md](08-observabilidade.md)** - Métricas Prometheus, OpenTelemetry tracing
9. **[09-seguranca.md](09-seguranca.md)** - Camadas de segurança, sanitização, sandbox
10. **[10-ci-cd.md](10-ci-cd.md)** - Pipeline de CI/CD, automação
11. **[11-testes.md](11-testes.md)** - Estratégia de testes, cobertura, fixtures
12. **[12-implantacao.md](12-implantacao.md)** - Deploy, Docker, operações
13. **[13-decisoes.md](13-decisoes.md)** - Decisões técnicas e trade-offs
14. **[14-escalabilidade.md](14-escalabilidade.md)** - Estratégia de scaling horizontal/vertical
15. **[15-roadmap.md](15-roadmap.md)** - Roadmap detalhado de 36 semanas (atualizado pós-auditoria)
16. **[16-historico-mudancas.md](16-historico-mudancas.md)** - Histórico de correções e mudanças aplicadas

## Relatórios de Auditoria (Raiz do Projeto)

Os seguintes relatórios foram gerados durante a auditoria completa de Maio 2026:

- **[CRITICAL_FILES.md](../CRITICAL_FILES.md)** - 40+ ficheiros críticos documentados
- **[SYSTEM_PROMPT.md](../SYSTEM_PROMPT.md)** - Prompt de sistema para o chat
- **[AUTONOMY_FLOW.md](../AUTONOMY_FLOW.md)** - Fluxo Plan → Execute → Verify → Iterate
- **[FILE_TERMINAL_ACCESS_REPORT.md](../FILE_TERMINAL_ACCESS_REPORT.md)** - Verificação de acesso a ficheiros/terminal
- **[UI_USER_FRIENDLY_REPORT.md](../UI_USER_FRIENDLY_REPORT.md)** - Análise de interface user-friendly
- **[AGENT_AUTONOMY_REPORT.md](../AGENT_AUTONOMY_REPORT.md)** - Análise de autonomia do agente
- **[PRODUCTION_READY_REPORT.md](../PRODUCTION_READY_REPORT.md)** - Verificação production-ready
- **[AUDIT_SUMMARY.md](../AUDIT_SUMMARY.md)** - Resumo executivo completo

## Como Usar

Para entender o projeto do zero ao aprofundado:
1. Comece com `01-visao-geral.md`
2. Prossiga sequencialmente até `15-roadmap.md`
3. Consulte `16-historico-mudancas.md` para ver o que já foi implementado

Para referência rápida:
- Arquitetura: `02-arquitetura-tecnica.md`
- Agentes: `04-agentes.md`
- Segurança: `09-seguranca.md`
- Deploy: `12-implantacao.md`
