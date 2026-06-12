"""Git Auto-Commit for NEXUS IDE.

Provides automatic git commit functionality triggered after file writes:
- Detects code file modifications after write_file operations
- Generates descriptive commit messages using LLM analysis of diffs
- Supports conventional commits format (feat:, fix:, docs:, refactor:, etc.)
- Configurable strategies: always | review | disabled
- Stores commit history in the database for audit trail

Configuration via environment variables:
    AUTO_COMMIT_ENABLED=true|false
    AUTO_COMMIT_STRATEGY=always|review|disabled
    AUTO_COMMIT_MODEL=auto (uses configured LLM provider)

Usage:
    from backend.tools.git_auto_commit import auto_commit_after_write, get_commit_history
    
    # Hook after file write
    result = await auto_commit_after_write(
        file_path="backend/api.py",
        project_path="/path/to/project",
        session_id="sess_123",
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from backend.tools.git_tools import git_commit_safe, git_operation
from backend.tools.registry import ToolSpec, register_tool

try:
    from backend.persistence.db import get_db, _new_id, _now_iso
except ImportError:
    get_db = None
    _new_id = None
    _now_iso = None

# LLM integration
try:
    from backend.tools.ollama_client import OllamaClient
except ImportError:
    OllamaClient = None

try:
    from backend.config.settings import get_settings
except ImportError:
    get_settings = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class CommitStrategy(str, Enum):
    """Auto-commit strategy modes."""
    ALWAYS = "always"      # Commit every change automatically
    REVIEW = "review"      # Generate commit message but require review
    DISABLED = "disabled"  # No automatic commits


class ConventionalCommitType(str, Enum):
    """Conventional commit types per specification."""
    FEAT = "feat"           # New feature
    FIX = "fix"             # Bug fix
    DOCS = "docs"           # Documentation only
    STYLE = "style"         # Formatting, no code change
    REFACTOR = "refactor"   # Code refactoring
    PERF = "perf"           # Performance improvement
    TEST = "test"           # Adding tests
    CHORE = "chore"         # Build/process/tooling changes
    CI = "ci"               # CI/CD changes
    BUILD = "build"         # Build system changes


def _get_config() -> dict[str, Any]:
    """Load auto-commit configuration from environment/settings."""
    enabled = os.environ.get("AUTO_COMMIT_ENABLED", "false").lower() in ("true", "1", "yes", "on")
    strategy = os.environ.get("AUTO_COMMIT_STRATEGY", "disabled").lower()
    
    # Validate strategy
    if strategy not in {s.value for s in CommitStrategy}:
        logger.warning("Invalid AUTO_COMMIT_STRATEGY=%s, defaulting to disabled", strategy)
        strategy = CommitStrategy.DISABLED.value
    
    model = os.environ.get("AUTO_COMMIT_MODEL", "auto")
    
    # Try to get from pydantic settings if available
    if get_settings:
        try:
            settings = get_settings()
            # Check if settings has auto-commit attributes (custom extension)
            if hasattr(settings, "auto_commit_enabled"):
                enabled = settings.auto_commit_enabled
            if hasattr(settings, "auto_commit_strategy"):
                strategy = settings.auto_commit_strategy
            if hasattr(settings, "auto_commit_model"):
                model = settings.auto_commit_model
        except Exception:
            pass
    
    return {
        "enabled": enabled,
        "strategy": strategy,
        "model": model,
        "ollama_host": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
    }


# ---------------------------------------------------------------------------
# Commit Message Generation
# ---------------------------------------------------------------------------

@dataclass
class CommitAnalysis:
    """Result of LLM analysis of a git diff."""
    commit_type: str
    scope: str
    description: str
    body: str
    breaking: bool


PROMPT_GENERATE_COMMIT = """You are an expert at writing conventional commit messages for Git.

Analyze the following git diff and produce a commit message in Conventional Commits format.

Rules:
1. Type MUST be one of: feat, fix, docs, style, refactor, perf, test, chore, ci, build
2. Scope (optional) should identify the module/component affected
3. Description MUST be a concise summary in Portuguese (max 72 chars)
4. Body (optional) can explain motivation and contrast with previous behavior
5. Mark breaking changes with "!" after the type/scope

Examples:
- "feat(auth): adiciona middleware de autenticação JWT"
- "fix(api): corrige race condition no endpoint de login"
- "refactor(core): reestrutura gerenciamento de estado"
- "perf(db): otimiza queries de indexação"
- "docs(readme): atualiza instruções de instalação"
- "test(auth): adiciona testes para refresh token"

Git diff:
```diff
{diff}
```

Respond ONLY with the commit message in this format:
TYPE[(scope)][!]: description

[body]

Do NOT include markdown formatting, explanations, or quotes. Just the raw commit message."""


async def _call_llm(prompt: str, model: str = "auto") -> str:
    """Call LLM to generate commit message."""
    
    # Try Ollama first if available
    if OllamaClient is not None:
        try:
            client = OllamaClient()
            # Use a small/fast model for commit messages
            preferred_model = "qwen2.5:1.5b" if model == "auto" else model
            
            response = await client.generate(
                model=preferred_model,
                prompt=prompt,
                options={"temperature": 0.3, "max_tokens": 256},
            )
            return response.get("response", "").strip()
        except Exception as e:
            logger.warning("Ollama commit message generation failed: %s", e)
    
    # Fallback: try settings-based provider
    if get_settings:
        try:
            settings = get_settings()
            provider = settings.llm_provider.lower()
            
            if provider == "openai":
                return await _call_openai(prompt, settings)
            elif provider == "anthropic":
                return await _call_anthropic(prompt, settings)
            elif provider == "kimi":
                return await _call_kimi(prompt, settings)
            elif provider == "groq":
                return await _call_groq(prompt, settings)
        except Exception as e:
            logger.warning("Provider %s commit generation failed: %s", provider, e)
    
    # Final fallback: heuristic-based commit message
    return ""


async def _call_openai(prompt: str, settings: Any) -> str:
    """Call OpenAI API for commit message."""
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a commit message generator."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 256,
            },
        )
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


async def _call_anthropic(prompt: str, settings: Any) -> str:
    """Call Anthropic API for commit message."""
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Authorization": f"Bearer {settings.anthropic_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-3-haiku-20240307",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 256,
            },
        )
        data = response.json()
        return data["content"][0]["text"].strip()


async def _call_kimi(prompt: str, settings: Any) -> str:
    """Call Kimi API for commit message."""
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.kimi_api_key}"},
            json={
                "model": "moonshot-v1-8k",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 256,
            },
        )
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


async def _call_groq(prompt: str, settings: Any) -> str:
    """Call Groq API for commit message."""
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 256,
            },
        )
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


def _parse_commit_message(raw: str) -> CommitAnalysis:
    """Parse raw LLM output into structured commit analysis."""
    lines = raw.strip().split("\n")
    if not lines:
        return CommitAnalysis(
            commit_type="chore",
            scope="",
            description="update: mudanças automáticas do agente",
            body="",
            breaking=False,
        )
    
    # Parse header line: type[(scope)][!]: description
    header = lines[0].strip()
    
    # Remove common markdown artifacts
    header = re.sub(r'^["\']+|["\']+$', '', header)
    header = re.sub(r'^`+|`+$', '', header)
    
    # Match conventional commit pattern
    pattern = r'^(\w+)(?:\(([^)]+)\))?(!)?\s*:\s*(.+)$'
    match = re.match(pattern, header)
    
    if match:
        commit_type = match.group(1).lower()
        scope = match.group(2) or ""
        breaking = match.group(3) == "!"
        description = match.group(4).strip()
    else:
        # Fallback: try to infer type from keywords
        commit_type = _infer_commit_type(header)
        scope = ""
        breaking = False
        description = header[:72]
    
    # Validate type
    valid_types = {t.value for t in ConventionalCommitType}
    if commit_type not in valid_types:
        commit_type = "chore"
    
    # Body is everything after header
    body_lines = []
    for line in lines[1:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("```"):
            body_lines.append(stripped)
    body = "\n".join(body_lines) if body_lines else ""
    
    return CommitAnalysis(
        commit_type=commit_type,
        scope=scope,
        description=description,
        body=body,
        breaking=breaking,
    )


def _infer_commit_type(text: str) -> str:
    """Infer commit type from keywords in the text."""
    text_lower = text.lower()
    
    keywords = {
        "fix": ["fix", "corrige", "bug", "erro", "repair", "patch"],
        "feat": ["feat", "feature", "adiciona", "add", "novo", "new", "implementa"],
        "docs": ["docs", "documentação", "readme", "documentation", "comment"],
        "refactor": ["refactor", "refatora", "reestrutura", "simplify", "clean"],
        "perf": ["perf", "performance", "optimiza", "speed", "fast", "slow"],
        "test": ["test", "tests", "spec", "coverage", "assert"],
        "ci": ["ci", "pipeline", "github", "actions", "workflow"],
        "build": ["build", "compile", "package", "dependency", "deps"],
        "style": ["style", "format", "lint", "prettier", "black"],
    }
    
    for commit_type, words in keywords.items():
        if any(word in text_lower for word in words):
            return commit_type
    
    return "chore"


def _format_commit_message(analysis: CommitAnalysis) -> str:
    """Format a CommitAnalysis into a conventional commit string."""
    scope_part = f"({analysis.scope})" if analysis.scope else ""
    breaking_part = "!" if analysis.breaking else ""
    header = f"{analysis.commit_type}{scope_part}{breaking_part}: {analysis.description}"
    
    if analysis.body:
        return f"{header}\n\n{analysis.body}"
    return header


async def generate_commit_message(
    diff: str,
    file_path: str | None = None,
    model: str = "auto",
) -> CommitAnalysis:
    """Generate a conventional commit message from a git diff.

    Args:
        diff: The git diff to analyze.
        file_path: Optional path to the modified file for context.
        model: Model to use for generation (auto uses default provider).

    Returns:
        CommitAnalysis with structured commit information.
    """
    # Truncate very large diffs
    max_diff_len = 8000
    if len(diff) > max_diff_len:
        diff = diff[:max_diff_len] + "\n... [diff truncated]"
    
    # Add file context if available
    if file_path:
        scope_hint = f"\n\nFile modified: {file_path}"
        diff = diff + scope_hint
    
    prompt = PROMPT_GENERATE_COMMIT.format(diff=diff)
    
    raw_message = await _call_llm(prompt, model=model)
    
    if not raw_message:
        # Fallback: heuristic-based message
        commit_type = _infer_commit_type(diff)
        file_name = Path(file_path).name if file_path else "ficheiros"
        description = f"atualiza {file_name}"
        return CommitAnalysis(
            commit_type=commit_type,
            scope=Path(file_path).parent.name if file_path else "",
            description=description,
            body="",
            breaking=False,
        )
    
    return _parse_commit_message(raw_message)


# ---------------------------------------------------------------------------
# Core Auto-Commit Logic
# ---------------------------------------------------------------------------

async def auto_commit_after_write(
    file_path: str,
    project_path: str = ".",
    session_id: str | None = None,
    project_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Hook called after a file write operation.

    Detects git changes, generates a commit message, and optionally commits.

    Args:
        file_path: Path to the file that was written.
        project_path: Root of the git project.
        session_id: Optional session ID for audit trail.
        project_id: Optional project ID for audit trail.
        force: Force commit even if strategy is review.

    Returns:
        Dict with commit result and metadata.
    """
    config = _get_config()
    result = {
        "committed": False,
        "message": "",
        "hash": None,
        "strategy": config["strategy"],
        "enabled": config["enabled"],
        "file_path": file_path,
        "error": None,
    }
    
    # Check if auto-commit is enabled
    if not config["enabled"] or config["strategy"] == CommitStrategy.DISABLED.value:
        result["message"] = "Auto-commit disabled"
        return result
    
    # Check if inside a git repo
    git_check = await git_operation("git rev-parse --git-dir", project_path)
    if "error" in git_check:
        result["error"] = "Not a git repository"
        return result
    
    # Get the diff for the specific file
    diff_result = await git_operation(
        f'git diff -- "{file_path}"',
        project_path,
    )
    diff = diff_result.get("output", "")
    
    if not diff.strip():
        # Check if file is newly staged
        staged_result = await git_operation(
            f'git diff --cached -- "{file_path}"',
            project_path,
        )
        diff = staged_result.get("output", "")
        
        if not diff.strip():
            result["message"] = "No changes to commit"
            return result
    
    # Generate commit message
    try:
        analysis = await generate_commit_message(
            diff=diff,
            file_path=file_path,
            model=config["model"],
        )
        commit_message = _format_commit_message(analysis)
        result["message"] = commit_message
        result["analysis"] = {
            "type": analysis.commit_type,
            "scope": analysis.scope,
            "description": analysis.description,
            "breaking": analysis.breaking,
        }
    except Exception as e:
        logger.error("Failed to generate commit message: %s", e)
        # Fallback message
        file_name = Path(file_path).name
        commit_message = f"chore: atualiza {file_name}"
        result["message"] = commit_message
        result["error"] = f"LLM generation failed: {e}"
    
    # Determine if we should commit
    strategy = config["strategy"]
    should_commit = (
        strategy == CommitStrategy.ALWAYS.value
        or (force and strategy == CommitStrategy.REVIEW.value)
    )
    
    if not should_commit:
        result["status"] = "pending_review"
        result["message"] = f"[PENDING REVIEW] {commit_message}"
        # Still record the pending commit
        _record_commit(
            session_id=session_id,
            project_id=project_id,
            file_path=file_path,
            commit_message=commit_message,
            commit_hash=None,
            strategy=strategy,
            status="pending_review",
            diff_preview=diff[:500] if diff else "",
        )
        return result
    
    # Stage the file and commit
    try:
        # Stage specific file
        stage_result = await git_operation(
            f'git add -- "{file_path}"',
            project_path,
        )
        if "error" in stage_result and stage_result.get("exit_code", 0) != 0:
            result["error"] = f"Failed to stage: {stage_result.get('error')}"
            return result
        
        # Commit
        commit_result = await git_commit_safe(
            message=commit_message,
            project_path=project_path,
            add_all=False,  # Already staged specific file
        )
        
        commit_output = commit_result.get("commit", {}).get("output", "")
        commit_exit = commit_result.get("commit", {}).get("exit_code", 0)
        
        if commit_exit != 0 and "nothing to commit" not in commit_output.lower():
            result["error"] = f"Commit failed: {commit_result.get('commit', {}).get('error', 'unknown')}"
            result["status"] = "failed"
            _record_commit(
                session_id=session_id,
                project_id=project_id,
                file_path=file_path,
                commit_message=commit_message,
                commit_hash=None,
                strategy=strategy,
                status="failed",
                diff_preview=diff[:500] if diff else "",
                error=result["error"],
            )
            return result
        
        # Extract commit hash
        hash_result = await git_operation("git rev-parse HEAD", project_path)
        commit_hash = hash_result.get("output", "").strip()
        
        result["committed"] = True
        result["hash"] = commit_hash
        result["status"] = "committed"
        
        # Record in database
        _record_commit(
            session_id=session_id,
            project_id=project_id,
            file_path=file_path,
            commit_message=commit_message,
            commit_hash=commit_hash,
            strategy=strategy,
            status="committed",
            diff_preview=diff[:500] if diff else "",
        )
        
        logger.info(
            "Auto-committed %s: %s (hash: %s)",
            file_path,
            commit_message.split("\n")[0],
            commit_hash[:8] if commit_hash else "n/a",
        )
        
    except Exception as e:
        result["error"] = f"Auto-commit failed: {e}"
        result["status"] = "failed"
        logger.error("Auto-commit failed for %s: %s", file_path, e)
    
    return result


# ---------------------------------------------------------------------------
# Database Persistence
# ---------------------------------------------------------------------------

GIT_COMMIT_SCHEMA = """
-- Auto-commit history tracking
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
"""


def _ensure_git_commits_table() -> None:
    """Ensure the git_commits table exists in the database."""
    if get_db is None:
        return
    try:
        with get_db() as conn:
            conn.executescript(GIT_COMMIT_SCHEMA)
    except Exception as e:
        logger.warning("Failed to ensure git_commits table: %s", e)


def _record_commit(
    session_id: str | None,
    project_id: str | None,
    file_path: str,
    commit_message: str,
    commit_hash: str | None,
    strategy: str,
    status: str,
    diff_preview: str = "",
    error: str | None = None,
) -> dict | None:
    """Record a commit in the database history.

    Args:
        session_id: Optional session ID.
        project_id: Optional project ID.
        file_path: Modified file path.
        commit_message: Full commit message.
        commit_hash: Git commit hash (None if pending/failed).
        strategy: Commit strategy used.
        status: Commit status (committed, pending_review, failed, rejected).
        diff_preview: Preview of the diff.
        error: Error message if failed.

    Returns:
        The recorded commit dict or None.
    """
    if get_db is None or _new_id is None:
        return None
    
    _ensure_git_commits_table()
    
    # Parse commit type from message
    commit_type = "chore"
    scope = ""
    match = re.match(r'^(\w+)(?:\(([^)]+)\))?(!)?\s*:', commit_message)
    if match:
        commit_type = match.group(1)
        scope = match.group(2) or ""
    
    cid = _new_id()
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO git_commits
                   (id, session_id, project_id, file_path, commit_message, commit_hash,
                    commit_type, scope, strategy, status, diff_preview, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cid,
                    session_id,
                    project_id,
                    file_path,
                    commit_message,
                    commit_hash,
                    commit_type,
                    scope,
                    strategy,
                    status,
                    diff_preview[:1000],  # Limit preview size
                    error,
                ),
            )
            row = conn.execute("SELECT * FROM git_commits WHERE id = ?", (cid,)).fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to record commit in database: %s", e)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_commit_history(
    session_id: str | None = None,
    project_id: str | None = None,
    limit: int = 50,
    status: str | None = None,
) -> list[dict]:
    """Retrieve commit history from the database.

    Args:
        session_id: Filter by session ID.
        project_id: Filter by project ID.
        limit: Maximum number of results.
        status: Filter by status (committed, pending_review, failed, rejected).

    Returns:
        List of commit records.
    """
    if get_db is None:
        return []
    
    _ensure_git_commits_table()
    
    conditions = []
    params: list[Any] = []
    
    if session_id:
        conditions.append("session_id = ?")
        params.append(session_id)
    if project_id:
        conditions.append("project_id = ?")
        params.append(project_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    try:
        with get_db() as conn:
            rows = conn.execute(
                f"""SELECT * FROM git_commits
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT ?""",
                (*params, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Failed to retrieve commit history: %s", e)
        return []


async def approve_pending_commit(commit_id: str) -> dict[str, Any]:
    """Approve a pending commit and execute it.

    Args:
        commit_id: The ID of the pending commit record.

    Returns:
        Result of the commit operation.
    """
    if get_db is None:
        return {"error": "Database not available"}
    
    _ensure_git_commits_table()
    
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM git_commits WHERE id = ? AND status = 'pending_review'",
                (commit_id,),
            ).fetchone()
            
            if not row:
                return {"error": "Pending commit not found"}
            
            commit_data = dict(row)
    except Exception as e:
        return {"error": f"Database error: {e}"}
    
    # Execute the commit
    project_path = "."  # Default; could be enhanced with project path lookup
    if commit_data.get("project_id"):
        # Try to get project path from database
        try:
            with get_db() as conn:
                proj = conn.execute(
                    "SELECT path FROM projects WHERE id = ?",
                    (commit_data["project_id"],),
                ).fetchone()
                if proj:
                    project_path = proj["path"]
        except Exception:
            pass
    
    # Stage and commit
    stage_result = await git_operation(
        f'git add -- "{commit_data["file_path"]}"',
        project_path,
    )
    if "error" in stage_result and stage_result.get("exit_code", 0) != 0:
        return {"error": f"Stage failed: {stage_result.get('error')}"}
    
    commit_result = await git_commit_safe(
        message=commit_data["commit_message"],
        project_path=project_path,
        add_all=False,
    )
    
    commit_output = commit_result.get("commit", {}).get("output", "")
    if "nothing to commit" in commit_output.lower():
        return {"error": "Nothing to commit"}
    
    # Get hash
    hash_result = await git_operation("git rev-parse HEAD", project_path)
    commit_hash = hash_result.get("output", "").strip()
    
    # Update record
    try:
        with get_db() as conn:
            conn.execute(
                """UPDATE git_commits
                   SET status = 'committed', commit_hash = ?, created_at = ?
                   WHERE id = ?""",
                (commit_hash, datetime.now(UTC).isoformat(), commit_id),
            )
    except Exception as e:
        logger.warning("Failed to update commit record: %s", e)
    
    return {
        "committed": True,
        "hash": commit_hash,
        "message": commit_data["commit_message"],
        "file_path": commit_data["file_path"],
    }


async def reject_pending_commit(commit_id: str, reason: str = "") -> dict[str, Any]:
    """Reject a pending commit.

    Args:
        commit_id: The ID of the pending commit record.
        reason: Optional rejection reason.

    Returns:
        Updated commit record.
    """
    if get_db is None:
        return {"error": "Database not available"}
    
    _ensure_git_commits_table()
    
    try:
        with get_db() as conn:
            conn.execute(
                """UPDATE git_commits
                   SET status = 'rejected', error = ?
                   WHERE id = ? AND status = 'pending_review'""",
                (reason or "Rejected by user", commit_id),
            )
            row = conn.execute("SELECT * FROM git_commits WHERE id = ?", (commit_id,)).fetchone()
            return dict(row) if row else {"error": "Commit not found"}
    except Exception as e:
        return {"error": f"Database error: {e}"}


async def get_commit_statistics(
    project_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Get statistics about auto-commits.

    Returns:
        Dict with commit counts by type, status, and period.
    """
    if get_db is None:
        return {}
    
    _ensure_git_commits_table()
    
    conditions = []
    params: list[Any] = []
    
    if project_id:
        conditions.append("project_id = ?")
        params.append(project_id)
    if session_id:
        conditions.append("session_id = ?")
        params.append(session_id)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    try:
        with get_db() as conn:
            # Total counts by status
            status_rows = conn.execute(
                f"""SELECT status, COUNT(*) as count
                    FROM git_commits
                    WHERE {where_clause}
                    GROUP BY status""",
                params,
            ).fetchall()
            
            # Total counts by type
            type_rows = conn.execute(
                f"""SELECT commit_type, COUNT(*) as count
                    FROM git_commits
                    WHERE {where_clause} AND status = 'committed'
                    GROUP BY commit_type""",
                params,
            ).fetchall()
            
            # Recent activity (last 24h)
            recent_row = conn.execute(
                f"""SELECT COUNT(*) as count
                    FROM git_commits
                    WHERE {where_clause}
                    AND created_at > datetime('now', '-1 day')""",
                params,
            ).fetchone()
            
            total_row = conn.execute(
                f"""SELECT COUNT(*) as count
                    FROM git_commits
                    WHERE {where_clause}""",
                params,
            ).fetchone()
            
            return {
                "total": total_row["count"] if total_row else 0,
                "last_24h": recent_row["count"] if recent_row else 0,
                "by_status": {r["status"]: r["count"] for r in status_rows},
                "by_type": {r["commit_type"]: r["count"] for r in type_rows},
            }
    except Exception as e:
        logger.error("Failed to get commit statistics: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

register_tool(
    ToolSpec(
        name="auto_commit_after_write",
        description=(
            "Automatically commit a file change after writing. "
            "Generates a conventional commit message using LLM analysis of the diff. "
            "Respects AUTO_COMMIT_ENABLED and AUTO_COMMIT_STRATEGY environment settings."
        ),
        schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file that was modified",
                },
                "project_path": {
                    "type": "string",
                    "description": "Root path of the git project",
                    "default": ".",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional session ID for audit trail",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional project ID for audit trail",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force commit even in review mode",
                    "default": False,
                },
            },
            "required": ["file_path"],
        },
        handler=auto_commit_after_write,
    )
)

register_tool(
    ToolSpec(
        name="get_commit_history",
        description="Retrieve auto-commit history from the database.",
        schema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "project_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "status": {
                    "type": "string",
                    "enum": ["committed", "pending_review", "failed", "rejected"],
                },
            },
        },
        handler=get_commit_history,
    )
)

register_tool(
    ToolSpec(
        name="approve_pending_commit",
        description="Approve a pending commit and execute it in git.",
        schema={
            "type": "object",
            "properties": {
                "commit_id": {
                    "type": "string",
                    "description": "ID of the pending commit to approve",
                },
            },
            "required": ["commit_id"],
        },
        handler=approve_pending_commit,
    )
)

register_tool(
    ToolSpec(
        name="reject_pending_commit",
        description="Reject a pending commit.",
        schema={
            "type": "object",
            "properties": {
                "commit_id": {
                    "type": "string",
                    "description": "ID of the pending commit to reject",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional rejection reason",
                },
            },
            "required": ["commit_id"],
        },
        handler=reject_pending_commit,
    )
)

register_tool(
    ToolSpec(
        name="get_commit_statistics",
        description="Get statistics about auto-commits.",
        schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "session_id": {"type": "string"},
            },
        },
        handler=get_commit_statistics,
    )
)
