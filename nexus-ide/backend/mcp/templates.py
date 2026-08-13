"""Catalog of ready-to-use MCP server templates.

Each template describes how to launch a well-known MCP server (command +
args) and which environment variables it needs. The MCP Connection Wizard
(frontend `/mcp`) renders this catalog as a gallery; picking a card only
prompts the user for the handful of fields the server actually needs instead
of hand-writing a `command`/`args`/`env` JSON block.

Field reference for each template:
    id            stable slug, used as ``template_id`` when creating a connector
    name          display name
    description   one-line description shown on the card
    category      grouping used by the wizard UI (filesystem, dev, data, web, custom)
    icon          emoji shown on the card
    transport     "stdio" (spawned process) or "http" (remote server)
    command       executable to run for stdio transport (e.g. "npx")
    args          argv list; ``{placeholder}`` tokens are filled from the
                  wizard's "params" answers (e.g. project path)
    params        user-supplied positional inputs (become {placeholder} in args)
    env           required/optional environment variables (API keys, tokens)
    docs_url      link to upstream documentation
"""

from __future__ import annotations

from typing import Any

MCP_TEMPLATES: dict[str, dict[str, Any]] = {
    "filesystem": {
        "id": "filesystem",
        "name": "Filesystem",
        "description": "Dá a um agente acesso de leitura/escrita a uma pasta local específica.",
        "category": "filesystem",
        "icon": "📁",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{root_path}"],
        "params": [
            {"key": "root_path", "label": "Pasta raiz", "placeholder": "/home/user/projeto", "required": True},
        ],
        "env": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
    },
    "github": {
        "id": "github",
        "name": "GitHub",
        "description": "Repositórios, issues, PRs e código via API do GitHub.",
        "category": "dev",
        "icon": "🐙",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "params": [],
        "env": [
            {"key": "GITHUB_PERSONAL_ACCESS_TOKEN", "label": "Personal Access Token", "secret": True, "required": True},
        ],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/github",
    },
    "gitlab": {
        "id": "gitlab",
        "name": "GitLab",
        "description": "Repositórios, merge requests e pipelines via API do GitLab.",
        "category": "dev",
        "icon": "🦊",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gitlab"],
        "params": [],
        "env": [
            {"key": "GITLAB_PERSONAL_ACCESS_TOKEN", "label": "Personal Access Token", "secret": True, "required": True},
            {"key": "GITLAB_API_URL", "label": "URL da API (self-hosted)", "required": False, "placeholder": "https://gitlab.com/api/v4"},
        ],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/gitlab",
    },
    "postgres": {
        "id": "postgres",
        "name": "PostgreSQL",
        "description": "Consulta esquemas e dados de uma base de dados PostgreSQL (read-only).",
        "category": "data",
        "icon": "🐘",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres", "{connection_string}"],
        "params": [
            {"key": "connection_string", "label": "Connection string", "placeholder": "postgresql://user:pass@host:5432/db", "required": True, "secret": True},
        ],
        "env": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/postgres",
    },
    "sqlite": {
        "id": "sqlite",
        "name": "SQLite",
        "description": "Consulta e inspeciona uma base de dados SQLite local.",
        "category": "data",
        "icon": "🗄️",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite", "{db_path}"],
        "params": [
            {"key": "db_path", "label": "Caminho do ficheiro .db", "placeholder": "./data/nexus.db", "required": True},
        ],
        "env": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
    },
    "brave-search": {
        "id": "brave-search",
        "name": "Brave Search",
        "description": "Pesquisa web em tempo real via API da Brave.",
        "category": "web",
        "icon": "🔎",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "params": [],
        "env": [
            {"key": "BRAVE_API_KEY", "label": "Brave API Key", "secret": True, "required": True},
        ],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search",
    },
    "puppeteer": {
        "id": "puppeteer",
        "name": "Puppeteer",
        "description": "Automação e scraping de browser (navegar, clicar, screenshot).",
        "category": "web",
        "icon": "🎭",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "params": [],
        "env": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer",
    },
    "playwright": {
        "id": "playwright",
        "name": "Playwright MCP",
        "description": "Automação de browser moderna para testes E2E e validação visual, com hosts e ficheiros limitados.",
        "category": "web",
        "icon": "PW",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest", "--headless", "--isolated"],
        "params": [],
        "env": [],
        "docs_url": "https://github.com/microsoft/playwright-mcp",
    },
    "slack": {
        "id": "slack",
        "name": "Slack",
        "description": "Ler e enviar mensagens em canais do Slack.",
        "category": "collab",
        "icon": "💬",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "params": [],
        "env": [
            {"key": "SLACK_BOT_TOKEN", "label": "Bot Token", "secret": True, "required": True},
            {"key": "SLACK_TEAM_ID", "label": "Team ID", "required": True},
        ],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/slack",
    },
    "memory": {
        "id": "memory",
        "name": "Memory (Knowledge Graph)",
        "description": "Memória persistente em grafo de conhecimento entre sessões.",
        "category": "data",
        "icon": "🧠",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "params": [],
        "env": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
    },
    "serena": {
        "id": "serena",
        "name": "Serena",
        "description": "Pesquisa e edita simbolos do codigo atraves de LSP, com contexto muito mais eficiente.",
        "category": "dev",
        "icon": "S",
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server", "--context", "ide-assistant", "--project", "{root_path}"],
        "params": [
            {"key": "root_path", "label": "Projeto alvo", "placeholder": "C:\\Users\\rodri\\Desktop\\nexus", "required": True},
        ],
        "env": [],
        "docs_url": "https://github.com/oraios/serena",
    },
    "context7": {
        "id": "context7",
        "name": "Context7",
        "description": "Documentacao atual e especifica da versao para frameworks e bibliotecas.",
        "category": "dev",
        "icon": "7",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
        "params": [],
        "env": [
            {"key": "CONTEXT7_API_KEY", "label": "API key (opcional)", "secret": True, "required": False},
        ],
        "docs_url": "https://context7.com/docs/resources/developer",
    },
    "qdrant": {
        "id": "qdrant",
        "name": "Qdrant Memory",
        "description": "Memoria semantica com pesquisa vetorial sobre codigo, docs, logs e decisoes.",
        "category": "data",
        "icon": "Q",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-qdrant"],
        "params": [
            {"key": "collection_name", "label": "Collection", "placeholder": "nexus-memory", "required": True},
        ],
        "env": [
            {"key": "QDRANT_URL", "label": "Qdrant URL", "placeholder": "http://localhost:6333", "required": True},
            {"key": "QDRANT_API_KEY", "label": "Qdrant API key (opcional)", "secret": True, "required": False},
            {"key": "EMBEDDING_MODEL", "label": "Embedding model", "placeholder": "sentence-transformers/all-MiniLM-L6-v2", "required": False},
        ],
        "docs_url": "https://qdrant.tech/documentation/qdrant-mcp-server/",
    },
    "sequential-thinking": {
        "id": "sequential-thinking",
        "name": "Sequential Thinking",
        "description": "Decomposicao, hipoteses e verificacao para tarefas complexas, ativado por politica.",
        "category": "dev",
        "icon": "ST",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "params": [],
        "env": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking",
    },
    "projectmind": {
        "id": "projectmind",
        "name": "ProjectMind (local)",
        "description": "Servidor MCP local do Nexus para grafo arquitetural, memoria, retrieval e reasoning.",
        "category": "dev",
        "icon": "PM",
        "transport": "stdio",
        "command": "",
        "args": ["-m", "projectmind.cli.main", "serve", "--root", "{root_path}", "--transport", "stdio"],
        "params": [
            {"key": "root_path", "label": "Pasta do ProjectMind", "placeholder": "C:\\Users\\rodri\\Desktop\\mcp", "required": True},
        ],
        "env": [],
        "docs_url": "https://github.com/projectmind/projectmind-mcp",
    },
    "fetch": {
        "id": "fetch",
        "name": "Fetch",
        "description": "Obtém e converte páginas web para markdown para o agente ler.",
        "category": "web",
        "icon": "🌐",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "params": [],
        "env": [],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
    },
    "http-remote": {
        "id": "http-remote",
        "name": "Servidor remoto (HTTP/SSE)",
        "description": "Liga a um servidor MCP remoto já em execução via URL HTTP/SSE.",
        "category": "custom",
        "icon": "🛰️",
        "transport": "http",
        "command": "",
        "args": [],
        "params": [
            {"key": "url", "label": "URL do servidor", "placeholder": "https://meu-servidor.com/mcp", "required": True},
        ],
        "env": [
            {"key": "AUTH_TOKEN", "label": "Token de autenticação (opcional)", "secret": True, "required": False},
        ],
        "docs_url": "https://modelcontextprotocol.io/docs/concepts/transports",
    },
    "custom": {
        "id": "custom",
        "name": "Comando personalizado",
        "description": "Define o teu próprio comando stdio (qualquer servidor MCP).",
        "category": "custom",
        "icon": "🛠️",
        "transport": "stdio",
        "command": "",
        "args": [],
        "params": [
            {"key": "command", "label": "Comando", "placeholder": "python", "required": True},
            {"key": "args", "label": "Argumentos (separados por espaço)", "placeholder": "-m my_mcp_server", "required": False},
        ],
        "env": [],
        "docs_url": "https://modelcontextprotocol.io/docs/develop/build-server",
    },
}


def list_templates() -> list[dict[str, Any]]:
    """Return a lightweight summary of every template (for the gallery view)."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "category": t["category"],
            "icon": t["icon"],
            "transport": t["transport"],
            "requires_env": [e["key"] for e in t.get("env", []) if e.get("required")],
        }
        for t in MCP_TEMPLATES.values()
    ]


def get_template(template_id: str) -> dict[str, Any] | None:
    return MCP_TEMPLATES.get(template_id)
