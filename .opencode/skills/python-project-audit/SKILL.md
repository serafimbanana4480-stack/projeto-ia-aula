---
schema_version: '1.0'
skill_id: python-project-audit
name: python-project-audit
version: 1.0.0
domain: python-quality
status: active
description: Auditar projetos Python com evidência de arquitetura, segurança, testes
  e qualidade. Usar quando o pedido for uma auditoria ou revisão completa de um repositório
  Python.
triggers:
- python audit
- auditoria Python
- auditoria de projeto Python
- python project review
- pytest ruff mypy
tags:
- python
- audit
- quality
- security
- testing
priority: 80
dependencies: []
conflicts: []
required_tools:
- list_dir
- read_file
- run_tests
- run_lint
- type_check
required_mcps: []
max_context_chars: 4000
---
# python-project-audit

## Purpose

Auditar projetos Python com evidência de arquitetura, segurança, testes e qualidade. Usar quando o pedido for uma auditoria ou revisão completa de um repositório Python.

## When to use

Activate only when the task matches one of the frontmatter triggers.

## Workflow

1. Confirmar o alvo e ler AGENTS.md, README, pyproject.toml e configuração de CI; registar o estado Git sem o alterar.
2. Mapear pacotes, entry points, testes, persistência, integrações externas e limites de confiança antes de avaliar comportamentos.
3. Seguir os fluxos principais no código e verificar tratamento de erros, validação de entrada, autenticação, permissões, concorrência e exposição de segredos.
4. Executar primeiro verificações focadas e depois os comandos de testes, lint e tipos definidos pelo próprio projeto; guardar os resultados reais.
5. Ligar cada finding a ficheiro e linha, impacto, cenário de reprodução e correção concreta; separar factos verificados de hipóteses.
6. Não editar código durante uma auditoria read-only. Se o pedido também autorizar correções, implementar em ciclos pequenos e voltar a executar as verificações afetadas.
7. Fechar com resumo por severidade, cobertura observada, comandos e resultados, limitações e itens NÃO VALIDADOS.

## Rules

- Não declarar uma área segura só porque não apareceu um finding; indicar o que foi e não foi inspecionado.
- Não inventar falhas, cobertura, comandos, resultados nem versões de dependências.
- Preservar alterações locais, ficheiros não rastreados, serviços e dados existentes.
- Usar ferramentas e comandos já disponíveis no projeto; não instalar dependências nem chamar serviços externos sem necessidade explícita.

## Verification

- Confirmar que cada finding aponta para evidência atual no código.
- Registar saída e código de retorno de cada comando executado.
- Marcar como NÃO VALIDADO qualquer fluxo que não tenha sido executado ou coberto por evidência suficiente.

## Example

> Pedido: audita este repositório Python e diz-me os riscos e testes que faltam.
