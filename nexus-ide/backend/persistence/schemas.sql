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

-- Refresh exchanges are single-use, but the same idempotency key must be able
-- to recover the exact response if a client loses the first HTTP response.
-- Token pairs are encrypted with the application's SECRET_KEY before storage.
CREATE TABLE IF NOT EXISTS auth_refresh_exchanges (
    refresh_jti           TEXT PRIMARY KEY,
    idempotency_key_hash  TEXT NOT NULL,
    response_ciphertext   TEXT NOT NULL,
    expires_at            REAL NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_exchanges_expiry
    ON auth_refresh_exchanges(expires_at);

-- Store only one-way hashes for revoked credentials. These records must
-- survive a backend restart while never storing bearer tokens or session IDs.
CREATE TABLE IF NOT EXISTS auth_revocations (
    revocation_type  TEXT NOT NULL CHECK (revocation_type IN ('token', 'session')),
    credential_hash TEXT NOT NULL,
    expires_at      REAL NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (revocation_type, credential_hash)
);

CREATE INDEX IF NOT EXISTS idx_auth_revocations_expiry
    ON auth_revocations(expires_at);

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
    user_id       TEXT,
    project_id    TEXT,
    title         TEXT,
    mode          TEXT DEFAULT 'auto',
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_active_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    context_json  TEXT,
    -- Soft-delete marker written by the session garbage collector. A session
    -- with status='expired' is not listed any more; expired_at records when
    -- the collector expired it.
    status        TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'idle', 'expired')),
    expired_at    TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_mode ON sessions(mode);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(last_active_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_user_active ON sessions(user_id, last_active_at DESC);

-- A bot owns a normal chat session; messages and runs remain in the existing
-- session store. Profiles carry no credentials or tool permissions.
CREATE TABLE IF NOT EXISTS bot_profiles (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    session_id      TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    instructions    TEXT NOT NULL DEFAULT '',
    provider        TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    deleted         INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_bot_profiles_owner
    ON bot_profiles(user_id, deleted, archived, updated_at DESC);

-- Group conversations are isolated from ordinary tool-capable chat sessions.
CREATE TABLE IF NOT EXISTS bot_groups (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_bot_groups_owner ON bot_groups(user_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS bot_group_members (
    group_id TEXT NOT NULL REFERENCES bot_groups(id) ON DELETE CASCADE,
    bot_id TEXT NOT NULL REFERENCES bot_profiles(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    PRIMARY KEY (group_id, bot_id),
    UNIQUE (group_id, position)
);
CREATE TABLE IF NOT EXISTS bot_group_messages (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES bot_groups(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'error')),
    content TEXT NOT NULL,
    bot_id TEXT,
    bot_name TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_bot_group_messages ON bot_group_messages(group_id, created_at);

CREATE TABLE IF NOT EXISTS bot_group_runs (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES bot_groups(id),
    user_id TEXT NOT NULL,
    request TEXT NOT NULL,
    project_root TEXT NOT NULL,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_bot_group_runs_owner ON bot_group_runs(user_id, group_id, created_at);
CREATE TABLE IF NOT EXISTS bot_group_run_tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES bot_group_runs(id),
    position INTEGER NOT NULL,
    bot_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    UNIQUE(run_id, position)
);
CREATE TABLE IF NOT EXISTS bot_group_run_records (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES bot_group_runs(id),
    task_id TEXT NOT NULL REFERENCES bot_group_run_tasks(id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL
);

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
    goal_id         TEXT,
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
CREATE INDEX IF NOT EXISTS idx_session_runs_goal_updated ON session_runs(goal_id, updated_at);

-- A child has its own session and run. Its detailed events remain in the
-- parent's ordered journal and are selected by task_id when replayed.
CREATE TABLE IF NOT EXISTS subagent_executions (
    parent_session_id TEXT NOT NULL,
    parent_run_id     TEXT NOT NULL,
    task_id           TEXT NOT NULL,
    child_session_id  TEXT NOT NULL UNIQUE,
    child_run_id      TEXT NOT NULL UNIQUE,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (parent_run_id, task_id),
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_run_id) REFERENCES session_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (child_session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (child_run_id) REFERENCES session_runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_subagent_executions_parent ON subagent_executions(parent_session_id, parent_run_id);

-- run_id links a persisted message to the durable execution that produced it.
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
    run_id        TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_session_only ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS idx_messages_model ON messages(model_used);
CREATE INDEX IF NOT EXISTS idx_messages_tier ON messages(tier_used);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_run_id ON messages(run_id);

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
    user_id          TEXT NOT NULL DEFAULT '',
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
CREATE INDEX IF NOT EXISTS idx_wb_user_timestamp ON whiteboard_entries(user_id, timestamp);

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

-- ---------------------------------------------------------------------------
-- TODOS — persistent per-session task list
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS todos (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    content         TEXT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low', 'normal', 'high')),
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_todos_session ON todos(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_todos_session_status ON todos(session_id, status);

-- ---------------------------------------------------------------------------
-- SCHEDULED TASKS — persistent autonomous task queue
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    task_type       TEXT NOT NULL DEFAULT 'monitoring',
    priority        TEXT NOT NULL DEFAULT 'normal',
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','scheduled','running','completed',
                          'failed','cancelled','retrying','waiting')),
    handler         TEXT,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    dependencies_json TEXT NOT NULL DEFAULT '[]',
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    timeout         INTEGER DEFAULT 300,
    interval        INTEGER,
    auto_retry      INTEGER DEFAULT 1,
    result_json     TEXT,
    error           TEXT,
    execution_time  REAL DEFAULT 0.0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    scheduled_at    TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    source          TEXT NOT NULL DEFAULT 'custom',
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status ON scheduled_tasks(status);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_source ON scheduled_tasks(source);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_handler ON scheduled_tasks(handler);

-- ---------------------------------------------------------------------------
-- RUN STATE — durable core of the run coordinator (Fase 1a).
-- One row per run: goal, requirements, constraints, definition of done, the
-- state-machine position, the plan, budget limits and accumulated usage.
-- The four tables below are the persistence contract of
-- backend/runtime/run_coordinator.py; keep them byte-identical to the copies in
-- backend/migrations/versions/008_run_state.py so schema parity holds.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS run_state (
    run_id                 TEXT PRIMARY KEY,
    project_id             TEXT NOT NULL DEFAULT '',
    user_id                TEXT NOT NULL DEFAULT '',
    session_id             TEXT NOT NULL DEFAULT '',
    goal                   TEXT NOT NULL DEFAULT '',
    requirements_json      TEXT NOT NULL DEFAULT '[]',
    constraints_json       TEXT NOT NULL DEFAULT '[]',
    definition_of_done_json TEXT NOT NULL DEFAULT '[]',
    state                  TEXT NOT NULL DEFAULT 'created'
        CHECK (state IN ('created','planning','running','waiting_tool','waiting_approval',
                         'verifying','recovering','paused','completed','failed','cancelled','expired')),
    plan_json              TEXT,
    current_task_id        TEXT,
    retry_count            INTEGER NOT NULL DEFAULT 0,
    budget_json            TEXT NOT NULL DEFAULT '{}',
    provider_json          TEXT NOT NULL DEFAULT '{}',
    memory_refs_json       TEXT NOT NULL DEFAULT '[]',
    artifacts_json         TEXT NOT NULL DEFAULT '[]',
    changed_files_json     TEXT NOT NULL DEFAULT '[]',
    dod_results_json       TEXT,
    usage_tokens           INTEGER NOT NULL DEFAULT 0,
    usage_cost_usd         REAL NOT NULL DEFAULT 0.0,
    usage_tool_calls       INTEGER NOT NULL DEFAULT 0,
    usage_retries          INTEGER NOT NULL DEFAULT 0,
    usage_browser_actions  INTEGER NOT NULL DEFAULT 0,
    usage_subagents        INTEGER NOT NULL DEFAULT 0,
    usage_runtime_seconds  REAL NOT NULL DEFAULT 0.0,
    usage_provider_calls   INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    heartbeat_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    stop_reason            TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_run_state_session ON run_state(session_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_state_project ON run_state(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_state_user ON run_state(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_state_state ON run_state(state, updated_at DESC);

-- ---------------------------------------------------------------------------
-- RUN CHECKPOINTS — one row per phase boundary, so a run can be restored.
-- Ties on created_at are resolved by checkpoint_id (latest_checkpoint).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS run_checkpoints (
    checkpoint_id  TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    phase          TEXT NOT NULL
        CHECK (phase IN ('after_planning','before_side_effect','after_side_effect','after_task',
                         'before_verification','after_verification','pause','provider_failover','heartbeat')),
    payload_json   TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (run_id) REFERENCES run_state(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run_created ON run_checkpoints(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run_phase ON run_checkpoints(run_id, phase, created_at DESC);

-- ---------------------------------------------------------------------------
-- RUN SIDE EFFECTS — idempotency ledger. UNIQUE(run_id, idempotency_key) makes
-- a replayed side effect a no-op instead of a second real-world action.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS run_side_effects (
    id              INTEGER PRIMARY KEY,
    run_id          TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT '',
    result_digest   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (run_id, idempotency_key),
    FOREIGN KEY (run_id) REFERENCES run_state(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_side_effects_run ON run_side_effects(run_id, idempotency_key);

-- ---------------------------------------------------------------------------
-- RUN DEAD LETTERS — failed units parked for a human or a later retry.
-- run_id carries no foreign key on purpose: a DLQ entry outlives its run and
-- pruned runs must not make the failure evidence unreadable.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS run_dead_letters (
    id                   TEXT PRIMARY KEY,
    run_id               TEXT NOT NULL DEFAULT '',
    task_id              TEXT NOT NULL DEFAULT '',
    error_class          TEXT NOT NULL DEFAULT '',
    sanitized_traceback  TEXT NOT NULL DEFAULT '',
    attempts             INTEGER NOT NULL DEFAULT 0,
    last_tool            TEXT,
    last_provider        TEXT,
    last_evidence_json   TEXT NOT NULL DEFAULT '{}',
    recoverability       TEXT NOT NULL DEFAULT 'unknown',
    retry_after          TEXT,
    state                TEXT NOT NULL DEFAULT 'open'
        CHECK (state IN ('open','retrying','requeued','replanned','abandoned','escalated')),
    note                 TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_run_dead_letters_run ON run_dead_letters(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_dead_letters_state ON run_dead_letters(state, created_at DESC);

-- ---------------------------------------------------------------------------
-- STRUCTURED LOGS — durable observability log written by the log store.
-- The table used to exist only in the live database (created on demand by
-- backend/observability/log_store.py) and was missing here, so a database
-- built from this file and a live database had a different shape.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS structured_logs (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    level       TEXT NOT NULL,
    message     TEXT NOT NULL,
    agent       TEXT,
    session_id  TEXT,
    task_id     TEXT,
    extra_json  TEXT,
    correlation_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_logs_session ON structured_logs(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_agent ON structured_logs(agent, timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_level ON structured_logs(level, timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_time ON structured_logs(timestamp DESC);

-- ---------------------------------------------------------------------------
-- USAGE LEDGER — durable per-call LLM spend record (the cost governor's
-- financial ledger). Like structured_logs it used to exist only in the live
-- database.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS usage_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    session_id TEXT DEFAULT '',
    run_id TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_usage_ledger_day ON usage_ledger(day);
CREATE INDEX IF NOT EXISTS idx_usage_ledger_run ON usage_ledger(run_id);
