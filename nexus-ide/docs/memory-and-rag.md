# NEXUS IDE — Memory, RAG & Code Intelligence

NEXUS IDE has three complementary layers that help agents remember context,
retrieve relevant information, and understand the codebase:

1. **Semantic Memory** — embedding-based long-term memory for conversations,
   facts, code snippets, and documentation.
2. **Codebase RAG** — dense retrieval over indexed source files using local
   embeddings.
3. **Code Intelligence** — lightweight AST-based symbol index for fast,
   exact lookup of functions, classes, and imports.

---

## 1. Semantic Memory

### What is stored

Memories are stored as typed records:

| Type | Use case |
|------|----------|
| `session` | Scoped to the current chat session |
| `project` | Scoped to the active project |
| `global` | Available across all sessions and projects |
| `code_snippet` | Small pieces of code with metadata |
| `file_content` | Indexed file contents |
| `conversation` | User / assistant turns |
| `tool_result` | Cached results from tool executions |
| `documentation` | Generated or imported docs |

Each memory has an embedding, importance score, tags, source agent, and
optional file path / language.

### Automatic memory usage

- At the start of every agent turn, relevant memories are retrieved using the
  user query and injected into the system prompt.
- After an agent finishes, a summary of the exchange is stored automatically
  (unless `enable_memory` is disabled for that agent).
- Agents can explicitly call `recall_context` and `store_memory` during the
  ReAct loop.

### REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/memories` | POST | Store a new memory |
| `/api/memories/search` | POST | Semantic search over memories |
| `/api/memories` | GET | List recent memories (filter by session/project/type) |
| `/api/memories/{id}` | DELETE | Delete a memory |
| `/api/memories/stats` | GET | Memory store statistics |

Example — store a project convention:

```bash
curl -X POST http://localhost:8000/api/memories \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "All Python modules must use pathlib instead of os.path.",
    "memory_type": "project",
    "project_id": "proj_abc",
    "tags": ["convention", "python"],
    "source": "ANALYZER",
    "importance": 0.8
  }'
```

Example — recall relevant memories:

```bash
curl -X POST http://localhost:8000/api/memories/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pathlib convention",
    "project_id": "proj_abc",
    "top_k": 5
  }'
```

### Persistence

By default the semantic memory store is backed by SQLite
(`data/nexus.db` table `persistent_memories`). Memories survive process
restarts and are loaded into memory on first access.

---

## 2. Codebase RAG

The embedding index turns the project source code into searchable chunks:

- Python files are split by top-level functions/classes (syntax-aware).
- Other languages use overlapping line-based chunks.
- Each chunk is embedded with the configured local embedding model
  (`nomic-embed-text` by default).
- The index is persisted to `data/embeddings_index.json` and supports
  incremental updates via content hash + file mtime.

### REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/embeddings/index` | POST | Index / re-index a project directory |
| `/api/embeddings/search` | POST | Semantic search over indexed chunks |
| `/api/embeddings/stats` | GET | Index statistics |

Example:

```bash
curl -X POST http://localhost:8000/api/embeddings/index \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_path": "/home/user/my-project"}'

curl -X POST http://localhost:8000/api/embeddings/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "how is routing implemented", "k": 8}'
```

Agents can also call the `search_codebase` and `index_codebase` tools directly.

---

## 3. Code Intelligence (AST Symbols)

In addition to dense semantic search, NEXUS IDE keeps a lightweight AST-based
symbol index. This is useful when you need exact definitions rather than
semantic similarity.

### Available tools

- `search_symbols` — find functions, classes, variables, or imports by name.
- `index_symbols` — build or refresh the AST index for a project.

Example agent tool call:

```tool
{"name": "search_symbols", "arguments": {"query": "get_memory_store", "kind": "function"}}
```

The symbol index is built on demand and lives in memory. It is faster than
semantic search for precise lookups and complements the embedding index.

---

## 4. For Agent Developers

### Enabling memory in an agent

All agents inherit from `AgentBase` and have `enable_memory = True` by
default. Relevant memories are injected automatically before the LLM call.

To let an agent use memory tools, include them in `supported_actions`:

```python
supported_actions = {
    AgentAction.RECALL_CONTEXT,
    AgentAction.STORE_MEMORY,
    AgentAction.SEARCH_CODEBASE,
    AgentAction.SEARCH_SYMBOLS,
}
```

### Best practices

- Store high-importance facts (`importance >= 0.7`) for project conventions,
  design decisions, and recurring bug fixes.
- Use tags consistently (e.g. `convention`, `bugfix`, `api`, `dependency`) to
  improve recall precision.
- Index the codebase when opening a project so that `search_codebase` and
  `search_symbols` return useful results.
- Combine `search_symbols` for exact lookups with `search_codebase` for
  semantic exploration.

---

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `No relevant memories found` | No memories stored yet, or query too specific | Store memories explicitly or lower `top_k` / similarity |
| `Codebase not indexed yet` | Embedding index is empty | Call `/api/embeddings/index` |
| Empty `search_symbols` results | Symbol index not built | Call `index_symbols` first |
| High memory usage | Too many memories loaded | Reduce `max_memories` in `MemoryStore` or lower importance of old entries |

---

**Last updated**: 2026-06-12
