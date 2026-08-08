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
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);

-- ---------------------------------------------------------------------------
-- USER PROFILE — preferences, routines, and personal memories
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id                 TEXT PRIMARY KEY,
    preferences_json        TEXT NOT NULL DEFAULT '{}',
    routines_json           TEXT NOT NULL DEFAULT '[]',
    favorite_projects_json  TEXT NOT NULL DEFAULT '[]',
    learned_facts_json      TEXT NOT NULL DEFAULT '[]',
    evolution_summary       TEXT NOT NULL DEFAULT '',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_routines (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    schedule_cron   TEXT,
    last_executed   TEXT,
    execution_count INTEGER DEFAULT 0,
    success_count   INTEGER DEFAULT 0,
    active          INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_memories (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    content         TEXT NOT NULL,
    memory_type     TEXT NOT NULL CHECK (memory_type IN ('preference','fact','routine','insight')),
    importance      REAL DEFAULT 0.5,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    access_count    INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_routines_user ON user_routines(user_id);
CREATE INDEX IF NOT EXISTS idx_user_memories_user ON user_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_user_memories_type ON user_memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_user_memories_importance ON user_memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_user_memories_created ON user_memories(created_at DESC);

CREATE TABLE IF NOT EXISTS email_accounts (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    label              TEXT NOT NULL DEFAULT 'Email',
    host               TEXT NOT NULL,
    port               INTEGER NOT NULL DEFAULT 993,
    username           TEXT NOT NULL,
    password_encrypted TEXT NOT NULL,
    use_ssl            INTEGER DEFAULT 1,
    active             INTEGER DEFAULT 1,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_email_accounts_user ON email_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_email_accounts_active ON email_accounts(active);

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
CREATE INDEX IF NOT EXISTS idx_sessions_mode ON sessions(mode);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(last_active_at DESC);

-- ---------------------------------------------------------------------------
-- SESSION RUNS / CHECKPOINTS — durable progress for long-running streams
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS session_runs (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled', 'interrupted')),
    agent           TEXT,
    phase           TEXT NOT NULL DEFAULT 'starting',
    prompt          TEXT NOT NULL DEFAULT '',
    partial_output  TEXT NOT NULL DEFAULT '',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    usage_json      TEXT NOT NULL DEFAULT '{}',
    error           TEXT,
    mission_id      TEXT,
    correlation_id  TEXT,
    mode            TEXT,
    execution_state TEXT,
    provider        TEXT,
    model           TEXT,
    error_category  TEXT,
    retry_after     INTEGER,
    evidence_json   TEXT,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at     TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
 
CREATE INDEX IF NOT EXISTS idx_session_runs_session ON session_runs(session_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_runs_active ON session_runs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_runs_session_updated ON session_runs(session_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_session_runs_correlation_updated ON session_runs(correlation_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_session_runs_mission_updated ON session_runs(mission_id, updated_at);

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
    cost_usd      REAL DEFAULT 0.0,
    latency_ms    INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_session_only ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS idx_messages_model ON messages(model_used);
CREATE INDEX IF NOT EXISTS idx_messages_tier ON messages(tier_used);
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
CREATE INDEX IF NOT EXISTS idx_tool_executions_session_timestamp ON tool_executions(session_id, created_at);
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
CREATE INDEX IF NOT EXISTS idx_changes_file ON proposed_changes(file_path);
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
CREATE INDEX IF NOT EXISTS idx_agent_states_agent_tier_updated
    ON agent_states(agent_name, memory_tier, updated_at);

-- ---------------------------------------------------------------------------
-- WHITEBOARD — shared memory space for agent discoveries
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS whiteboard_entries (
    entry_id         TEXT PRIMARY KEY,
    topic            TEXT NOT NULL,
    author_agent     TEXT NOT NULL,
    content          TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    importance       REAL NOT NULL DEFAULT 0.5
        CHECK (importance >= 0.0 AND importance <= 1.0),
    tags             TEXT NOT NULL DEFAULT '[]',
    related_entries  TEXT NOT NULL DEFAULT '[]',
    archived         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_wb_topic ON whiteboard_entries(topic);
CREATE INDEX IF NOT EXISTS idx_wb_author ON whiteboard_entries(author_agent);
CREATE INDEX IF NOT EXISTS idx_wb_timestamp ON whiteboard_entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_wb_archived ON whiteboard_entries(archived);

CREATE TABLE IF NOT EXISTS whiteboard_entry_links (
    id              TEXT PRIMARY KEY,
    entry_id_1      TEXT NOT NULL,
    entry_id_2      TEXT NOT NULL,
    relation_type   TEXT NOT NULL DEFAULT 'related',
    created_at      TEXT NOT NULL,
    UNIQUE(entry_id_1, entry_id_2, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_wb_links_1 ON whiteboard_entry_links(entry_id_1);
CREATE INDEX IF NOT EXISTS idx_wb_links_2 ON whiteboard_entry_links(entry_id_2);

-- ---------------------------------------------------------------------------
-- PEER REVIEW — automatic code/design review pipeline
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS peer_review_requests (
    review_id      TEXT PRIMARY KEY,
    artifact_id    TEXT NOT NULL,
    artifact_type  TEXT NOT NULL
        CHECK (artifact_type IN ('code', 'design', 'test', 'config')),
    author_agent   TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_review', 'approved',
                          'changes_requested', 'rejected')),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pr_artifact ON peer_review_requests(artifact_id);
CREATE INDEX IF NOT EXISTS idx_pr_status ON peer_review_requests(status);

CREATE TABLE IF NOT EXISTS peer_review_results (
    result_id       TEXT PRIMARY KEY,
    review_id       TEXT NOT NULL,
    reviewer_agent  TEXT NOT NULL,
    status          TEXT NOT NULL
        CHECK (status IN ('approved', 'changes_requested', 'rejected')),
    comments        TEXT NOT NULL DEFAULT '[]',
    criteria_scores TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    FOREIGN KEY (review_id)
        REFERENCES peer_review_requests(review_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pr_results_review ON peer_review_results(review_id);

-- ---------------------------------------------------------------------------
-- GIT AUTO-COMMIT HISTORY — automatic commit tracking for audit trail
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS git_commits (
    id              TEXT PRIMARY KEY,
    session_id      TEXT,
    project_id      TEXT,
    file_path       TEXT NOT NULL,
    commit_message  TEXT NOT NULL,
    commit_hash     TEXT,
    commit_type     TEXT,
    scope           TEXT,
    strategy        TEXT NOT NULL DEFAULT 'always',
    status          TEXT NOT NULL DEFAULT 'committed'
        CHECK (status IN ('committed', 'pending_review', 'failed', 'rejected')),
    diff_preview    TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_git_commits_session ON git_commits(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_git_commits_project ON git_commits(project_id);
CREATE INDEX IF NOT EXISTS idx_git_commits_status ON git_commits(status);
CREATE INDEX IF NOT EXISTS idx_git_commits_hash ON git_commits(commit_hash);
CREATE INDEX IF NOT EXISTS idx_git_commits_created ON git_commits(created_at DESC);

CREATE TABLE IF NOT EXISTS persistent_memories (
    id              TEXT PRIMARY KEY,
    user_id         TEXT,
    session_id      TEXT,
    project_id      TEXT,
    content         TEXT NOT NULL,
    summary         TEXT,
    embedding_json  TEXT,
    memory_type     TEXT,
    tags            TEXT,
    source          TEXT,
    file_path       TEXT,
    language        TEXT,
    kind            TEXT DEFAULT 'semantic',
    related_memory_ids TEXT,
    importance      REAL,
    created_at      REAL,
    last_accessed_at REAL,
    access_count    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pm_user ON persistent_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_pm_session ON persistent_memories(session_id);
CREATE INDEX IF NOT EXISTS idx_pm_project ON persistent_memories(project_id);
CREATE INDEX IF NOT EXISTS idx_pm_type ON persistent_memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_pm_source ON persistent_memories(source);
CREATE INDEX IF NOT EXISTS idx_pm_accessed ON persistent_memories(last_accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_pm_created ON persistent_memories(created_at DESC);

-- ---------------------------------------------------------------------------
-- RBAC — roles, permissions, assignments
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS roles (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS permissions (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT DEFAULT '',
    resource      TEXT NOT NULL,
    action        TEXT NOT NULL,
    UNIQUE(resource, action)
);

CREATE TABLE IF NOT EXISTS user_roles (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    role_id       TEXT NOT NULL,
    assigned_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS role_permissions (
    id            TEXT PRIMARY KEY,
    role_id       TEXT NOT NULL,
    permission_id TEXT NOT NULL,
    UNIQUE(role_id, permission_id),
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_id);
