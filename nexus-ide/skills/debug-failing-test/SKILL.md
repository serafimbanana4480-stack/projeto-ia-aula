---
schema_version: "1.0"
skill_id: debug-failing-test
name: debug-failing-test
version: 1.0.0
domain: debugging
status: active
description: >-
  Procedimento para depurar um teste que falha: reproduzir de forma determinística,
  isolar a causa com evidência, corrigir a mudança mínima e verificar com o teste
  e a suite afetada. Usar quando um teste está vermelho ou é intermitente.
triggers:
  - debug failing test
  - teste a falhar
  - fix red test
  - flaky test investigation
tags: [debug, testing, pytest, reproduction, verification]
priority: 85
required_tools: [list_dir, read_file, search_in_files, run_tests, run_shell]
required_mcps: []
max_context_chars: 4000
---

# debug-failing-test

## Purpose

Transformar um teste vermelho (determinístico ou intermitente) numa causa-raiz
comprovada e numa correção mínima verificada, sem mascarar o sintoma.

## When to use

Ativar apenas quando o pedido corresponder a um dos triggers: depurar um teste
que falha, corrigir um teste vermelho, ou investigar um teste intermitente.

## Workflow

1. Reproduzir a falha de forma determinística: correr o teste isolado e registar a saída completa e o código de retorno com run_tests.
2. Ler o teste e o código sob teste com read_file; entender o contrato esperado e o valor real observado.
3. Isolar a causa: reduzir o input, verificar o ponto exato da asserção e usar search_in_files para localizar definições e usos relacionados.
4. Distinguir erro de produto, erro de teste e ambiente; formar uma hipótese única e falseável antes de editar.
5. Aplicar a menor mudança que endereça a causa; usar run_shell apenas quando necessário e sem efeitos destrutivos.
6. Verificar: correr o teste isolado, depois o módulo/suite afetada, e confirmar que nada mais regrediu.
7. Se a falha for intermitente, registar a taxa de reprodução e a condição de corrida/ordem antes de considerar resolvida.

## Rules

- Não enfraquecer, saltar ou vazar uma asserção para "tornar o teste verde" sem corrigir a causa.
- Não alterar o comportamento esperado do produto para acomodar um teste desatualizado sem confirmação.
- Não declarar sucesso sem reexecutar o teste depois da correção e registar o resultado.
- Preservar mudanças não relacionadas; manter a correção mínima e reversível.

## Verification

- O teste alvo passa de forma repetida após a correção (registar o número de execuções).
- A suite/módulo afetada continua verde.
- A causa-raiz está identificada por evidência (stack trace, valor real vs. esperado), não por suposição.

## Example

Pedido: "Este teste do validador está a falhar de forma intermitente; investiga e corrige."
