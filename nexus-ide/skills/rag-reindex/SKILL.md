---
schema_version: "1.0"
skill_id: rag-reindex
name: rag-reindex
version: 1.0.0
domain: knowledge
status: active
description: >-
  Procedimento para reindexar o código/conhecimento e verificar a qualidade do
  retrieval: disparar a indexação, confirmar as estatísticas do índice e validar
  consultas de exemplo antes de confiar nos resultados. Usar após mudanças
  estruturais ou quando o retrieval parece desatualizado.
triggers:
  - rag reindex
  - reindexar código
  - rebuild search index
  - verify retrieval quality
tags: [rag, indexing, retrieval, embeddings, verification]
priority: 75
required_tools: [index_codebase, index_stats, search_codebase, read_file]
required_mcps: []
max_context_chars: 3600
---

# rag-reindex

## Purpose

Garantir que o índice de retrieval reflete o código/conhecimento atual e que as
consultas devolvem resultados relevantes antes de se confiar neles.

## When to use

Ativar apenas quando o pedido corresponder a um dos triggers: reindexar o
código, reconstruir o índice de busca, ou verificar a qualidade do retrieval
após mudanças estruturais.

## Workflow

1. Confirmar o alvo e o escopo da indexação; registar o estado anterior com index_stats (número de ficheiros, símbolos, tamanho).
2. Disparar a reindexação com index_codebase e aguardar a conclusão; não assumir sucesso sem confirmação.
3. Comparar as estatísticas novas com as anteriores (index_stats) e explicar diferenças relevantes (ficheiros adicionados/removidos).
4. Verificar o retrieval com um conjunto pequeno de consultas representativas via search_codebase; confirmar que os resultados esperados aparecem e são relevantes.
5. Ler os ficheiros dos melhores resultados com read_file para confirmar que correspondem ao pedido e não a homónimos.
6. Registar cobertura, consultas testadas, resultados observados e limitações conhecidas do índice.

## Rules

- Não confiar em resultados de retrieval sem os verificar contra o ficheiro real.
- Não reindexar destrutivamente sem registar o estado anterior para comparação.
- Não inventar contagens, cobertura ou relevância; usar apenas as estatísticas e resultados observados.
- Se a reindexação falhar, parar e reportar o erro em vez de prosseguir com um índice parcial.

## Verification

- index_stats confirma um índice completo e consistente após a operação.
- Cada consulta de exemplo devolve o ficheiro/símbolo esperado no topo.
- Os resultados lidos correspondem ao conteúdo real e não a homónimos.

## Example

Pedido: "Reindexa o código e confirma que a busca volta a encontrar os handlers principais."
