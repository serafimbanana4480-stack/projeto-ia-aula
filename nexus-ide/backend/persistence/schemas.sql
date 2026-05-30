-- NEXUS IDE — SQLite schema
-- Designed for projects, sessions, messages, tool executions, and routing decisions audit.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT,
    is_active     INTEGER DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    path          TEXT NOT NULL,
    description   TEXT,
    mode          TEXT DEFAULT 'auto',
    preferred_model TEXT,
    trust         INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_path ON projects(path);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    project_id    TEXT,
    title         TEXT,
    mode          TEXT DEFAULT 'auto',
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_active_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    context_json  TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(last_active_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool','thinking')),
    content       TEXT NOT NULL,
    tier_used     TEXT,
    model_used    TEXT,
    tools_used_json TEXT,
    tokens_in     INTEGER DEFAULT 0,
    tokens_out    INTEGER DEFAULT 0,
    latency_ms    INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);

CREATE TABLE IF NOT EXISTS tool_executions (
    id            TEXT PRIMARY KEY,
    session_id    TEXT,
    tool_name     TEXT NOT NULL,
    args_json     TEXT,
    result_json   TEXT,
    success       INTEGER DEFAULT 1,
    error         TEXT,
    duration_ms   INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tool_session ON tool_executions(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_executions(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_success ON tool_executions(success);

CREATE TABLE IF NOT EXISTS routing_decisions (
    id            TEXT PRIMARY KEY,
    session_id    TEXT,
    user_input    TEXT NOT NULL,
    tier_chosen   TEXT NOT NULL,
    reason        TEXT,
    confidence    REAL,
    word_count    INTEGER,
    decision_ms   INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_routing_session ON routing_decisions(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_routing_tier ON routing_decisions(tier_chosen);
CREATE INDEX IF NOT EXISTS idx_routing_created ON routing_decisions(created_at DESC);

CREATE TABLE IF NOT EXISTS proposed_changes (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    project_id    TEXT,
    file_path     TEXT NOT NULL,
    operation     TEXT NOT NULL CHECK (operation IN ('create','modify','delete')),
    diff          TEXT,
    new_content   TEXT,
    applied       INTEGER DEFAULT 0,
    applied_at    TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_changes_session ON proposed_changes(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_changes_pending ON proposed_changes(applied) WHERE applied = 0;
CREATE INDEX IF NOT EXISTS idx_changes_project ON proposed_changes(project_id);
CREATE INDEX IF NOT EXISTS idx_changes_operation ON proposed_changes(operation);

-- ---------------------------------------------------------------------------
-- AGENT STATES — persistent memory for agents (short / medium / long term)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_states (
    id              TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    project_path    TEXT NOT NULL DEFAULT '',
    memory_tier     TEXT NOT NULL CHECK (memory_tier IN ('short_term', 'medium_term', 'long_term')),
    key             TEXT NOT NULL,
    value           TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    access_count    INTEGER DEFAULT 0,
    importance_score REAL DEFAULT 0.5 CHECK (importance_score >= 0.0 AND importance_score <= 1.0),
    UNIQUE(agent_name, session_id, project_path, memory_tier, key)
);

CREATE INDEX IF NOT EXISTS idx_agent_states_lookup
    ON agent_states(agent_name, session_id, project_path, memory_tier, key);
CREATE INDEX IF NOT EXISTS idx_agent_states_agent
    ON agent_states(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_states_tier
    ON agent_states(memory_tier);
CREATE INDEX IF NOT EXISTS idx_agent_states_project
    ON agent_states(project_path);
CREATE INDEX IF NOT EXISTS idx_agent_states_importance
    ON agent_states(importance_score DESC);
