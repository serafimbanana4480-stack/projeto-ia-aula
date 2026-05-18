# Coverage Report — NEXUS IDE Backend Tests

Relatório de cobertura de testes atual e recomendações para melhoria.

---

## Estado Atual (Antes das Novas Correções)

### Testes Existentes

| Diretório | Ficheiros | Estimativa de Testes |
|-----------|-----------|---------------------|
| **tools/** | 7 ficheiros | ~30 testes |
| **orchestrator/** | 10 ficheiros | ~50 testes |
| **agents/** | ? | ? |
| **config/** | ? | ? |
| **observability/** | 5 ficheiros | ~20 testes |
| **integration/** | 5 ficheiros | ~10 testes |
| **middleware/** | 4 ficheiros | ~10 testes |
| **knowledge/** | 2 ficheiros | ~5 testes |
| **contracts/** | 2 ficheiros | ~5 testes |
| **sandbox/** | 1 ficheiro | ~3 testes |
| **Total** | ~36 ficheiros | ~143 testes |

### Cobertura por Módulo

| Módulo | Cobertura Estimada | Status |
|--------|-------------------|--------|
| `tools/file_ops.py` | ~90% | ✅ Bom |
| `tools/web_search.py` | ~70% | ⚠️ Aceitável |
| `tools/code_executor.py` | ~80% | ✅ Bom |
| `tools/embeddings.py` | ~60% | ⚠️ Baixo |
| `tools/file_manager.py` | ~20% | ❌ Muito baixo (apenas stub) |
| `tools/task_spawner.py` | 0% | ❌ Sem testes |
| `orchestrator/router.py` | ~85% | ✅ Bom |
| `orchestrator/smart_router.py` | 0% | ❌ Sem testes |
| `orchestrator/dependency_graph.py` | 0% | ❌ Sem testes |
| `orchestrator/engine.py` | ~70% | ⚠️ Aceitável |
| `orchestrator/agent_pool.py` | ~80% | ✅ Bom |
| `orchestrator/context_manager.py` | ~70% | ⚠️ Aceitável |

---

## Novos Testes Adicionados (Esta Implementação)

### Phase 1: Testes Unitários em Falta

| Ficheiro | Testes Adicionados | Linhas | Status |
|----------|-------------------|-------|--------|
| `test_task_spawner.py` | 5 testes | ~60 | ✅ Criado |
| `test_dependency_graph.py` | 10 testes | ~150 | ✅ Criado |
| `test_file_manager.py` | 9 testes | ~127 | ✅ Reimplementado |
| `test_smart_router.py` | 8 testes | ~140 | ✅ Criado |

**Total Phase 1:** 32 novos testes unitários

### Phase 2: Testes de Integração

| Ficheiro | Testes Adicionados | Linhas | Status |
|----------|-------------------|-------|--------|
| `test_autonomy_cycle.py` | 6 testes | ~140 | ✅ Criado |

**Total Phase 2:** 6 novos testes de integração

### Phase 3: Testes E2E Manuais

| Documento | Cenários | Status |
|-----------|----------|--------|
| `E2E_TEST_MANUAL.md` | 10 cenários | ✅ Criado |

**Total Phase 3:** 10 cenários de teste manual

---

## Cobertura Após Implementação

### Cobertura por Módulo (Atualizada)

| Módulo | Cobertura Anterior | Cobertura Atual | Melhoria |
|--------|-------------------|-----------------|----------|
| `tools/file_manager.py` | ~20% | ~85% | +65% |
| `tools/task_spawner.py` | 0% | ~60% | +60% |
| `orchestrator/smart_router.py` | 0% | ~75% | +75% |
| `orchestrator/dependency_graph.py` | 0% | ~90% | +90% |
| `orchestrator/engine.py` (ciclo) | ~70% | ~80% | +10% |

### Componentes Sem Testes (Ainda)

| Componente | Prioridade | Recomendação |
|------------|------------|--------------|
| `tools/data_analysis.py` | Média | Adicionar testes de integração |
| `tools/agent_comm.py` | Média | Adicionar testes de comunicação |
| `orchestrator/event_bus.py` | Alta | Adicionar testes de eventos |
| `agents/coder.py` | Alta | Adicionar testes de ReAct loop |
| `agents/debugger.py` | Alta | Adicionar testes de ReAct loop |
| `agents/analyzer.py` | Alta | Adicionar testes de ReAct loop |
| `frontend/components/dashboard/` | Média | Expandir testes React |
| `frontend/components/chat/` | Média | Expandir testes React |

---

## Executar Testes de Cobertura

### Backend

```bash
cd backend
pytest --cov=backend --cov-report=html --cov-report=term-missing
```

### Frontend

```bash
cd frontend
npm test -- --coverage
```

---

## Metas de Cobertura

| Meta | Valor Atual | Alvo | Status |
|------|-------------|------|--------|
| Cobertura geral backend | ~65% | 70% | ⚠️ Próximo |
| Cobertura tools | ~70% | 80% | ⚠️ Próximo |
| Cobertura orchestrator | ~65% | 80% | ⚠️ Próximo |
| Cobertura agents | ~50% | 70% | ❌ Abaixo |
| Cobertura frontend | ~15% | 50% | ❌ Abaixo |

---

## Recomendações

### Curto Prazo (1-2 semanas)

1. **Adicionar testes para agents** — Prioridade alta
   - `test_coder.py` — Testar ReAct loop do CODER
   - `test_debugger.py` — Testar ReAct loop do DEBUGGER
   - `test_analyzer.py` — Testar ReAct loop do ANALYZER

2. **Adicionar testes para event_bus** — Prioridade alta
   - Testar emissão de eventos
   - Testar subscrição de eventos
   - Testar serialização de eventos

3. **Expandir testes de engine** — Prioridade média
   - Testar `_handle_spawn_task_calls` (quando implementado)
   - Testar ciclo completo com mocks
   - Testar retry logic

### Médio Prazo (3-4 semanas)

4. **Expandir testes frontend** — Prioridade média
   - Testar `MetricsGrid.tsx` com loading states
   - Testar `ChatPanel.tsx` com SSE streaming
   - Testar `ModelPanel.tsx` com seleção de modelo

5. **Adicionar testes E2E automatizados** — Prioridade baixa
   - Usar Playwright para testes end-to-end
   - Testar fluxos críticos do usuário
   - Integrar com CI/CD

### Longo Prazo (5-8 semanas)

6. **Atingir 80% de cobertura** em todos os módulos críticos
7. **Adicionar testes de performance** para bottleneck detection
8. **Adicionar testes de segurança** para path traversal e injection

---

## Como Melhorar Cobertura

### 1. Executar pytest com coverage

```bash
cd backend
pytest --cov=backend --cov-report=html
# Abre htmlcov/index.html no browser
```

### 2. Identificar linhas não cobertas

No relatório HTML, verifique:
- Linhas vermelhas = não cobertas
- Linhas amarelas = parcialmente cobertas
- Priorize linhas em módulos críticos (orchestrator, tools)

### 3. Adicionar testes para linhas não cobertas

Para cada linha não coberta:
- Determine o cenário que a linha executa
- Escreva um teste que cobre esse cenário
- Re-execute pytest para verificar cobertura

### 4. Re-executar testes após cada mudança

```bash
pytest --cov=backend --cov-report=term-missing
```

---

## Próximos Passos

1. Executar testes de cobertura atual para obter baseline real
2. Priorizar módulos com cobertura < 50%
3. Adicionar testes para componentes críticos sem cobertura
4. Configurar CI/CD para executar testes de cobertura automaticamente
5. Definir threshold mínimo de cobertura (ex: 70%) para PRs

---

## Notas

- Este relatório foi atualizado em 18/05/2026
- Cobertura estimada baseada em análise manual dos ficheiros
- Executar `pytest --cov` para obter números reais
- Prioridade baseada em criticidade de componentes (Rule #1: CONSULT PLANNING)
