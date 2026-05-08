-- NEXUS IDE — SQLite schema
-- Designed for projects, sessions, messages, tool executions, and routing decisions audit.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

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
