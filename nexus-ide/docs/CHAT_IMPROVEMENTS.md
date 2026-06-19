# CHAT Improvements — Iteração 3

**Data:** 2026-06-18
**Foco:** Corrigir bugs do chat (erros desaparecem, multi-chat, thinking blocks)

## Bugs encontrados e corrigidos

### 1. **POST /api/sessions duplicado** (bug pré-existente crítico)

**Sintoma:** Ao criar uma sessão, o `title` enviado no JSON body era **ignorado** e a resposta vinha sempre com `"Nova sessão"`. O sessions.py novo estava shadowed pelo modes.py.

**Causa raiz:** `routes/modes.py` tinha o seu próprio `POST /api/sessions` que recebia `title` como **query param** (não JSON body) e usava o default. Como o FastAPI resolve a primeira rota registada, o nosso novo endpoint nunca era chamado.

**Fix:** Removido o duplicado de `modes.py`. O endpoint correto (com JSON body, validação Pydantic, CRUD completo) está em `routes/sessions.py`.

**Validação:** Test `test_create_session_default` agora passa.

### 2. **Erros desaparecem no refresh**

**Sintoma:** Quando o LLM falha ou o stream quebra, o bubble de erro aparecia no chat, mas ao recarregar a página o erro sumia (não estava no DB).

**Causa raiz:** O `chat.py` só chamava `add_message` em caso de sucesso. Em caso de erro, o user message ficava orfão e o erro era efémero.

**Fix:** Adicionado `add_message` para user + error-assistant nos dois caminhos de erro:
- `chat.py:964-986` (fallback exhausted)
- `chat.py:994-1015` (stream interrupted)

Agora os erros persistem no DB e sobrevivem ao refresh.

### 3. **Não havia lista de sessões**

**Sintoma:** O user só via a sessão actual. Não conseguia ver, escolher, renomear ou apagar outras sessões.

**Causa raiz:** Não havia UI nem endpoint completo de gestão de sessões. O `POST /api/sessions` existente só criava (sem list, get, patch, delete).

**Fix:**
- **Backend:** Criado `routes/sessions.py` com 5 endpoints completos (CRUD)
- **Backend:** Adicionadas funções em `db.py`: `update_session`, `delete_session`, `list_sessions_with_counts`, cache invalidation
- **Frontend:** Criado `useChatSessions` hook com auto-refresh, filtro, e persistência em localStorage
- **Frontend:** Criado `SessionList` sidebar (colapsável, com search, rename inline, delete)

### 4. **Sem retry / feedback de erro persistente**

**Sintoma:** Quando havia erro de conexão ou o user cancelava, o erro era mostrado inline mas não havia forma de recuperar.

**Fix:**
- **Backend:** Erros são agora persistidos no DB (não desaparecem)
- **Frontend:** Criado `Toast` component (singleton store, não-React) com 4 tipos (error/warning/info/success)
- **Frontend:** Erros de stream/history viram toasts que **não somem sozinhos** (sticky)
- **Frontend:** `lastUserMessageRef` permite retry após erro
- **Frontend:** Regenerate usa o ref como fallback

### 5. **Thinking blocks incompletos**

**Sintoma:** Thinking só aparecia se o backend enviasse explicitamente o campo `thinking` no message — mas o backend só o fazia em casos raros.

**Fix:** Adicionado case `"thinking"` em `foldEvents` (ChatPanel.tsx) que acumula `e.content` no campo `message.thinking`. Agora qualquer SSE event `thinking` é capturado e mostrado no `ThinkingBlock`.

## Novas funcionalidades adicionadas

### Backend

| Endpoint | Função |
|---|---|
| `GET /api/sessions?limit=100&project_id=` | Listar sessões com message_count |
| `GET /api/sessions/{id}` | Obter uma sessão |
| `POST /api/sessions` | Criar (JSON body, validação) |
| `PATCH /api/sessions/{id}` | Renomear / mudar mode |
| `DELETE /api/sessions/{id}` | Apagar (cascade messages) |
| `GET /api/sessions/{id}/messages?limit=500` | Histórico de mensagens |

### Frontend

| Componente | Função |
|---|---|
| `SessionList` | Sidebar com lista de sessões, search, rename, delete, online indicator |
| `Toast` + `useToast` | Notificações globais (error/warning/info/success) com botão de copiar detalhes |
| `useChatSessions` | Hook para gestão completa de sessões (create/list/rename/delete + persist localStorage) |
| `ThinkingBlock` (já existia) | Visualização de thinking — agora garantido que aparece |
| `ChatPanel` (atualizado) | Sidebar integrada, toasts em erros, retry button |

## Testes

| Suite | Testes | Status |
|---|---|---|
| `tests/orchestrator/test_sessions_api.py` (NOVO) | 10 | ✅ |
| `tests/swarm/` (53 unit) | 53/53 | ✅ |
| `e2e/swarm_e2e_test.py` | 13/13 | ✅ |
| `e2e/api_audit.py` | All checks | ✅ |

## Estrutura final

```
backend/
├── orchestrator/
│   ├── routes/
│   │   ├── sessions.py          # NOVO - CRUD completo
│   │   ├── modes.py             # LIMPO - removidos duplicados
│   │   └── chat.py              # ATUALIZADO - erros persistidos
│   └── main.py                  # ATUALIZADO - regista sessions_router
├── persistence/
│   └── db.py                    # ATUALIZADO - update_session, delete_session, list_sessions_with_counts
└── tests/
    └── orchestrator/
        └── test_sessions_api.py  # NOVO - 10 testes

frontend/
├── components/chat/
│   ├── ChatPanel.tsx             # ATUALIZADO - sidebar + toast + retry
│   ├── SessionList.tsx           # NOVO
│   ├── Toast.tsx                 # NOVO
│   ├── ThinkingBlock.tsx         # JÁ EXISTIA
│   ├── MessageBubble.tsx         # JÁ EXISTIA
│   ├── ToolCallCard.tsx          # JÁ EXISTIA
│   ├── ToolCallTimeline.tsx      # JÁ EXISTIA
│   └── VirtualMessageList.tsx    # JÁ EXISTIA
└── hooks/
    ├── useAgentStream.ts         # JÁ EXISTIA
    └── useChatSessions.ts         # NOVO
```

## Como o chat funciona agora

```
User envia mensagem
    ↓
useAgentStream.postChat() → POST /api/chat (SSE)
    ↓
chat.py processa:
  - sanitiza
  - roteia
  - chama agente
    ↓
Em caso de SUCESSO:
  - add_message(user)
  - add_message(assistant)   ← persiste na DB
  - SSE: agent_started, tokens, agent_finished, done
    ↓
Em caso de ERRO:
  - SSE: error + done
  - add_message(user)              ← persistido
  - add_message(⚠ error_text)     ← persistido
  - chat history loads via /api/sessions/{id}/messages
    ↓
Frontend:
  - foldEvents() → message bubbles
  - Se error event → bubble com retry
  - SessionList mostra todas as sessões
  - Toast sticky para erros persistentes
  - lastUserMessageRef → retry button funciona
    ↓
Ao REFRESH:
  - useChatSessions.currentId persiste em localStorage
  - historyMessages carrega do DB
  - error bubble reaparece (persiste)
```

## Próximas melhorias (não-críticas)

1. **Migração para WebSocket** — SSE funciona mas WS seria melhor para cancelamento gracioso
2. **Search no histórico** — full-text search nas mensagens
3. **Branching de sessões** — fork de uma sessão a partir de uma mensagem
4. **Tags/labels** — organizar sessões por projeto
5. **Streaming RAG em tempo real** — mostrar evidência sendo carregada
6. **Undo/redo** — desfazer última mensagem
7. **Exportar conversa** — markdown / json / pdf
