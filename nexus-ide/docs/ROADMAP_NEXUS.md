# Roadmap NEXUS IDE — De 9.3 para 10/10

## 🔴 Prioridade IMEDIATA (1-2h)

| # | Ação | Impacto |
|---|------|---------|
| 1 | Configurar OpenRouter API key (`LLM_PROVIDER=openrouter`) | LLM real em vez de fallback |
| 2 | Criar projeto de teste no frontend (ex: VER PRECOS) | Chat pode usar tools |
| 3 | Apagar dead code: `events_temp.py`, `types.py`, `main_enhanced.py` | -40% código morto |
| 4 | Corrigir `IntegrityError` no `agent_bus._persist_message()` | Erro nos logs |
| 5 | Consolidar 2 EventBus (orchestrator/ + swarm/) | Duplicação removida |

## 🟡 Curto prazo (1-2 dias)

| # | Ação | Impacto |
|---|------|---------|
| 6 | Implementar `TeamLeader.delegate()` real (não stub) | Swarm executa agentes |
| 7 | Unificar memória: 4 sistemas → 1 SQLite | Consistência de dados |
| 8 | Testes unitários: pytest coverage > 60% | Quality gate real |
| 9 | `CommunicationProtocol` com transporte real | Bus funcional |
| 10 | `NEXUS_AUTO_APPLY=true` em produção | Self-healing ativo |

## 🟢 Projetos-alvo para testar autonomia real

O NEXUS IDE com auto mode + swarm mode + self-healing pode melhorar:

| Projeto | Como usar NEXUS |
|---------|----------------|
| **VER PRECOS** | Swarm: CODER analisa modelo, ANALYZER revê dados, DEBUGGER verifica R² |
| **CS2 External** | Auto: DEBUGGER encontra bugs, CODER corrige, ANALYZER revê stealth |
| **Brawl Stars bot** | Swarm: CODER optimiza pathfinding, DEBUGGER testa ADB, ANALYZER mede performance |
| **FiveM** | Auto: ciclo Plan→Verify→Fix para features novas |

Para usar: criar projeto no NEXUS, apontar para o diretório do projeto, usar modo `auto` com `"Melhora o R² do modelo de preços"`