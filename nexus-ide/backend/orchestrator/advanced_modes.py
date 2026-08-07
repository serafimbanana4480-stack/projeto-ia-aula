"""NEXUS IDE — Advanced Modes Engine (Infinity Suite v2.0)

Core engine that loads, validates, and orchestrates the 11 advanced cognitive
modes: Vibe Infinity, Advisor Infinity, Forge, Swarm Foundry, Multiverse,
Proof, Reality Lab, Archaeologist, Evolve, Sentinel, and Autonomous.

Each mode is a self-contained orchestration strategy that can:
- Toggle on/off via /command in chat
- Run alongside or replace the base cognitive mode
- Maintain persistent state across sessions
- Enforce quality gates, risk controls, and evidence requirements
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
ADVANCED_MODES_YAML = CONFIG_DIR / "modes-advanced.yaml"
ADVANCED_MODES_STATE_DIR = REPO_ROOT / ".nexus" / "advanced-modes"
EVIDENCE_DIR = REPO_ROOT / ".nexus" / "evidence"
TRAJECTORY_DIR = REPO_ROOT / ".nexus" / "trajectories"
CHECKPOINT_DIR = REPO_ROOT / ".nexus" / "checkpoints"

# Ensure directories exist
for _dir in [ADVANCED_MODES_STATE_DIR, EVIDENCE_DIR, TRAJECTORY_DIR, CHECKPOINT_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# Data Types
# ═══════════════════════════════════════════════════════════════════════════

class ModeState(Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class RiskLevel(Enum):
    READ = 0
    LOCAL_REVERSIBLE = 1
    INSTALL_MIGRATION = 2
    DESTRUCTIVE = 3
    PRODUCTION = 4


# Single source of truth: the AdvisorAgent owns the intervention taxonomy.
# This module previously declared its own identical-but-divergent copy; the
# mode now consumes the agent's enum so the two advisors can never drift.
from backend.agents.advisor import InterventionLevel  # noqa: F401


class EvidenceStatus(Enum):
    UNPROVEN = "unproven"
    PROVEN = "proven"
    CONTESTED = "contested"
    REJECTED = "rejected"


class GoalNodeState(Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    REJECTED = "rejected"
    VERIFIED = "verified"


@dataclass
class GoalNode:
    """A node in the living goal tree."""
    id: str
    title: str
    description: str = ""
    state: GoalNodeState = GoalNodeState.NOT_STARTED
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    assigned_agent: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    quality_score: Optional[float] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ModeSession:
    """Persistent state for an active advanced mode session."""
    mode_id: str
    session_id: str
    state: ModeState = ModeState.INACTIVE
    goal_tree: Dict[str, GoalNode] = field(default_factory=dict)
    goal_root: Optional[str] = None
    interventions: List[Dict[str, Any]] = field(default_factory=list)
    evidence_book: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    trajectory: List[Dict[str, Any]] = field(default_factory=list)
    quality_gates: Dict[str, bool] = field(default_factory=dict)
    checkpoints: List[str] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    start_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metrics: Dict[str, Any] = field(default_factory=dict)


# The advanced-mode catalog is intentionally honest about its current runtime
# contract.  A mode can have a rich prompt and state model without yet being a
# standalone executor.  These labels are exposed to the UI so "active" never
# implies that a specialised worker is currently running.
MODE_RUNTIME_STATUS: Dict[str, Dict[str, str]] = {
    "vibe-infinity": {
        "status": "composed",
        "role": "director",
        "summary": "Maintains the goal tree, replanning and verification contract.",
    },
    "advisor-infinity": {
        "status": "integrated",
        "role": "governor",
        "summary": "Challenges completion claims and can route to the ADVISOR agent.",
    },
    "forge": {
        "status": "composed",
        "role": "builder",
        "summary": "Applies the project-factory delivery checklist to implementation work.",
    },
    "swarm-foundry": {
        "status": "composed",
        "role": "specialists",
        "summary": "Provides the specialist-generation contract; specialist spawning remains delegated to SWARM.",
    },
    "multiverse": {
        "status": "integrated",
        "role": "tournament",
        "summary": "Evaluates submitted alternatives through the tournament endpoint.",
    },
    "proof": {
        "status": "composed",
        "role": "evidence",
        "summary": "Applies evidence requirements; evidence is only proven when recorded by a real check.",
    },
    "reality-lab": {
        "status": "composed",
        "role": "reality",
        "summary": "Adds adversarial and clean-install scenarios to the verification plan.",
    },
    "archaeologist": {
        "status": "composed",
        "role": "mapping",
        "summary": "Requests a live architecture map and doc-versus-code comparison.",
    },
    "evolve": {
        "status": "composed",
        "role": "learning",
        "summary": "Records trajectories and requires repeated evidence before proposing rules.",
    },
    "sentinel": {
        "status": "integrated",
        "role": "safety",
        "summary": "Applies risk checks and exposes the security-gate endpoint.",
    },
    "autonomous": {
        "status": "integrated",
        "role": "composite",
        "summary": "Uses the Plan -> Execute -> Verify engine for complex requests and composes the suite policies.",
    },
}

MODE_PRIORITY = [
    "vibe-infinity",
    "forge",
    "swarm-foundry",
    "multiverse",
    "reality-lab",
    "archaeologist",
    "advisor-infinity",
    "proof",
    "sentinel",
    "evolve",
]

# Explicit commands select the most appropriate existing agent.  Passive
# activation remains policy-oriented and does not silently replace the user's
# normal router choice.
MODE_PREFERRED_AGENTS = {
    "advisor-infinity": "ADVISOR",
    "forge": "CODER",
    "multiverse": "ARCHITECT",
    "proof": "ADVISOR",
    "reality-lab": "TEST_RUNNER_E2E",
    "archaeologist": "ANALYZER",
    "evolve": "ANALYZER",
    "sentinel": "GUARDIAN",
}

COMPOSITE_MODES = {"vibe-infinity", "autonomous"}


@dataclass
class TournamentEntry:
    """A single solution in a multiverse tournament."""
    id: str
    name: str
    approach_description: str
    files: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    total_score: float = 0.0
    is_winner: bool = False
    merged_from: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# Configuration Cache
# ═══════════════════════════════════════════════════════════════════════════

_config_cache: Optional[Dict[str, Any]] = None


def _load_config() -> Dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    try:
        with open(ADVANCED_MODES_YAML, "r", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f) or {}
        logger.info(f"Loaded {len(_config_cache.get('modes', {}))} advanced modes from config")
        return _config_cache
    except FileNotFoundError:
        logger.warning(f"Advanced modes config not found at {ADVANCED_MODES_YAML}")
        _config_cache = {"modes": {}, "groups": {}, "commands": {}}
        return _config_cache
    except Exception as e:
        logger.error(f"Failed to load advanced modes config: {e}")
        _config_cache = {"modes": {}, "groups": {}, "commands": {}}
        return _config_cache


def _invalidate_cache() -> None:
    global _config_cache
    _config_cache = None


def get_advanced_modes() -> Dict[str, Any]:
    """Return all advanced mode definitions."""
    return _load_config().get("modes", {})


def get_advanced_mode(mode_id: str) -> Optional[Dict[str, Any]]:
    """Return a single advanced mode definition."""
    return _load_config().get("modes", {}).get(mode_id)


def get_mode_groups() -> Dict[str, Any]:
    """Return the mode grouping configuration."""
    return _load_config().get("groups", {})


def get_command_aliases() -> Dict[str, Any]:
    """Return command alias mappings."""
    return _load_config().get("commands", {})


def resolve_command(command: str) -> Optional[Dict[str, Any]]:
    """Resolve a /command to its mode configuration."""
    commands = get_command_aliases()
    # Strip leading / and normalise
    raw = command.lstrip("/").lower()
    for name, config in commands.items():
        aliases = [a.lstrip("/").lower() for a in config.get("aliases", [])]
        if raw == name or raw in aliases:
            return {"mode": config.get("mode", name), "command": config}
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Mode State Manager
# ═══════════════════════════════════════════════════════════════════════════

class ModeStateManager:
    """Manages persistent state for active mode sessions."""

    def __init__(self) -> None:
        self._sessions: Dict[str, ModeSession] = {}
        self._active_modes: Set[str] = set()
        self._load_sessions()

    def _session_path(self, mode_id: str, session_id: str) -> Path:
        return ADVANCED_MODES_STATE_DIR / f"{mode_id}__{session_id}.json"

    def _load_sessions(self) -> None:
        """Load all persisted sessions from disk."""
        if not ADVANCED_MODES_STATE_DIR.exists():
            return
        for f in ADVANCED_MODES_STATE_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sid = data.get("session_id", f.stem)
                mid = data.get("mode_id", "unknown")
                key = f"{mid}__{sid}"

                # Reconstruct GoalNodes from dict
                goal_tree = {}
                for gid, gdata in data.get("goal_tree", {}).items():
                    raw_goal_state = gdata.get("state", GoalNodeState.NOT_STARTED.value)
                    # Older sessions were serialised with ``default=str`` and
                    # therefore contain values such as
                    # ``GoalNodeState.IN_PROGRESS``.  Accept both formats so a
                    # restart never silently discards the goal tree.
                    if isinstance(raw_goal_state, str) and raw_goal_state.startswith("GoalNodeState."):
                        raw_goal_state = raw_goal_state.split(".", 1)[1].lower()
                    try:
                        gdata["state"] = GoalNodeState(raw_goal_state)
                    except (TypeError, ValueError):
                        logger.warning(
                            "Unknown goal state %r in %s; restoring as not_started",
                            raw_goal_state,
                            f.name,
                        )
                        gdata["state"] = GoalNodeState.NOT_STARTED
                    goal_tree[gid] = GoalNode(**gdata)

                # Reconstruct state enum
                state = ModeState(data.get("state", "inactive")) if "state" in data else ModeState.INACTIVE

                session = ModeSession(
                    mode_id=mid,
                    session_id=sid,
                    state=state,
                    goal_tree=goal_tree,
                    goal_root=data.get("goal_root"),
                    interventions=data.get("interventions", []),
                    evidence_book=data.get("evidence_book", {}),
                    trajectory=data.get("trajectory", []),
                    quality_gates=data.get("quality_gates", {}),
                    checkpoints=data.get("checkpoints", []),
                    decisions=data.get("decisions", []),
                    start_time=data.get("start_time", ""),
                    updated_time=data.get("updated_time", ""),
                    metrics=data.get("metrics", {}),
                )
                self._sessions[key] = session
                if state == ModeState.ACTIVE or state == ModeState.RUNNING:
                    self._active_modes.add(mid)
            except Exception as e:
                logger.warning(f"Failed to load session {f.name}: {e}")

    def _save_session(self, session: ModeSession) -> None:
        """Persist a session to disk."""
        path = self._session_path(session.mode_id, session.session_id)
        goal_tree = {}
        for gid, goal in session.goal_tree.items():
            goal_data = asdict(goal)
            goal_data["state"] = goal.state.value
            goal_tree[gid] = goal_data
        data = {
            "mode_id": session.mode_id,
            "session_id": session.session_id,
            "state": session.state.value,
            "goal_tree": goal_tree,
            "goal_root": session.goal_root,
            "interventions": session.interventions,
            "evidence_book": session.evidence_book,
            "trajectory": session.trajectory,
            "quality_gates": session.quality_gates,
            "checkpoints": session.checkpoints,
            "decisions": session.decisions,
            "start_time": session.start_time,
            "updated_time": datetime.now(timezone.utc).isoformat(),
            "metrics": session.metrics,
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def create_session(self, mode_id: str) -> ModeSession:
        """Create a new session for a mode."""
        import uuid
        session_id = str(uuid.uuid4())[:8]
        session = ModeSession(
            mode_id=mode_id,
            session_id=session_id,
            state=ModeState.ACTIVE,
        )
        key = f"{mode_id}__{session_id}"
        self._sessions[key] = session
        self._active_modes.add(mode_id)
        self._save_session(session)
        logger.info(f"Created advanced mode session: {mode_id}/{session_id}")
        return session

    def get_session(self, mode_id: str, session_id: Optional[str] = None) -> Optional[ModeSession]:
        """Get an active session for a mode."""
        if session_id:
            return self._sessions.get(f"{mode_id}__{session_id}")
        # Return most recent active session
        candidates = [
            s for k, s in self._sessions.items()
            if k.startswith(f"{mode_id}__") and s.state in (ModeState.ACTIVE, ModeState.RUNNING)
        ]
        if candidates:
            return max(candidates, key=lambda s: s.updated_time)
        return None

    def get_or_create_session(self, mode_id: str) -> ModeSession:
        """Get existing or create new session."""
        session = self.get_session(mode_id)
        if session is None:
            session = self.create_session(mode_id)
        return session

    def update_session(self, session: ModeSession) -> None:
        """Save session state to disk."""
        session.updated_time = datetime.now(timezone.utc).isoformat()
        key = f"{session.mode_id}__{session.session_id}"
        self._sessions[key] = session
        if session.state in (ModeState.ACTIVE, ModeState.RUNNING):
            self._active_modes.add(session.mode_id)
        else:
            self._active_modes.discard(session.mode_id)
        self._save_session(session)

    def _recompute_active_modes(self) -> None:
        """Rebuild the mode index from session state after a bulk change."""
        self._active_modes = {
            session.mode_id
            for session in self._sessions.values()
            if session.state in (ModeState.ACTIVE, ModeState.RUNNING)
        }

    def is_mode_active(self, mode_id: str) -> bool:
        """Check if a mode is currently active."""
        return mode_id in self._active_modes

    def list_active_modes(self) -> List[str]:
        """List all currently active mode IDs."""
        return list(self._active_modes)

    def list_sessions(self, mode_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all sessions, optionally filtered by mode."""
        result = []
        for key, session in self._sessions.items():
            if mode_id and not key.startswith(f"{mode_id}__"):
                continue
            result.append({
                "mode_id": session.mode_id,
                "session_id": session.session_id,
                "state": session.state.value,
                "active": session.state in (ModeState.ACTIVE, ModeState.RUNNING),
                "start_time": session.start_time,
                "updated_time": session.updated_time,
                "goal_count": len(session.goal_tree),
                "intervention_count": len(session.interventions),
                "checkpoint_count": len(session.checkpoints),
                "evidence_count": len(session.evidence_book),
            })
        return sorted(result, key=lambda x: x["updated_time"], reverse=True)

    def deactivate_mode(self, mode_id: str) -> bool:
        """Deactivate a mode and all its sessions."""
        changed = False
        for key, session in list(self._sessions.items()):
            if key.startswith(f"{mode_id}__"):
                session.state = ModeState.INACTIVE
                self._save_session(session)
                changed = True
        self._recompute_active_modes()
        return changed


# Global singleton
_state_manager: Optional[ModeStateManager] = None


def get_state_manager() -> ModeStateManager:
    global _state_manager
    if _state_manager is None:
        _state_manager = ModeStateManager()
    return _state_manager


# ═══════════════════════════════════════════════════════════════════════════
# Goal Tree Operations
# ═══════════════════════════════════════════════════════════════════════════

def _make_node_id() -> str:
    import uuid
    return f"G-{uuid.uuid4().hex[:6]}"


def create_goal_tree(description: str, parent_id: Optional[str] = None) -> Tuple[str, GoalNode]:
    """Create a new goal node and return (id, node)."""
    gid = _make_node_id()
    node = GoalNode(
        id=gid,
        title=description[:80],
        description=description,
        parent_id=parent_id,
    )
    return gid, node


def add_goal_to_session(session: ModeSession, description: str, parent_id: Optional[str] = None) -> str:
    """Add a goal node to a session's tree."""
    gid, node = create_goal_tree(description, parent_id)
    session.goal_tree[gid] = node
    if parent_id and parent_id in session.goal_tree:
        session.goal_tree[parent_id].children.append(gid)
    if session.goal_root is None:
        session.goal_root = gid
    return gid


def update_goal_state(
    session: ModeSession,
    goal_id: str,
    state: GoalNodeState,
    rejection_reason: Optional[str] = None,
    quality_score: Optional[float] = None,
) -> bool:
    """Update the state of a goal node."""
    if goal_id not in session.goal_tree:
        return False
    node = session.goal_tree[goal_id]
    node.state = state
    node.updated_at = datetime.now(timezone.utc).isoformat()
    if rejection_reason:
        node.rejection_reason = rejection_reason
    if quality_score is not None:
        node.quality_score = quality_score
    return True


# ═══════════════════════════════════════════════════════════════════════════
# Evidence Book
# ═══════════════════════════════════════════════════════════════════════════

def add_evidence(
    session: ModeSession,
    requirement: str,
    implementation_files: List[str],
    test_files: List[str],
    evidence_paths: List[str],
    confidence: float = 0.85,
) -> str:
    """Add an evidence entry to the evidence book."""
    import uuid
    eid = f"EV-{uuid.uuid4().hex[:6]}"
    session.evidence_book[eid] = {
        "id": eid,
        "requirement": requirement,
        "implementation": implementation_files,
        "tests": test_files,
        "evidence": evidence_paths,
        "status": EvidenceStatus.PROVEN.value if confidence >= 0.85 else EvidenceStatus.CONTESTED.value,
        "confidence": confidence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # Persist evidence to disk
    ev_file = EVIDENCE_DIR / f"{session.mode_id}__{session.session_id}__{eid}.json"
    ev_file.write_text(json.dumps(session.evidence_book[eid], indent=2), encoding="utf-8")
    return eid


# ═══════════════════════════════════════════════════════════════════════════
# Trajectory Tracking
# ═══════════════════════════════════════════════════════════════════════════

def record_trajectory_entry(
    session: ModeSession,
    event_type: str,
    description: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a trajectory event."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "description": description,
        "metadata": metadata or {},
    }
    session.trajectory.append(entry)
    # Persist trajectory
    traj_file = TRAJECTORY_DIR / f"{session.mode_id}__{session.session_id}.jsonl"
    with open(traj_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# Checkpoint System
# ═══════════════════════════════════════════════════════════════════════════

def create_checkpoint(session: ModeSession) -> str:
    """Create a recovery checkpoint."""
    import uuid
    cpid = f"CP-{uuid.uuid4().hex[:8]}"
    checkpoint = {
        "id": cpid,
        "mode_id": session.mode_id,
        "session_id": session.session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": session.state.value,
        "goal_tree_size": len(session.goal_tree),
        "trajectory_size": len(session.trajectory),
    }
    cp_file = CHECKPOINT_DIR / f"{cpid}.json"
    cp_file.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    session.checkpoints.append(cpid)
    return cpid


# ═══════════════════════════════════════════════════════════════════════════
# Mode Orchestrator
# ═══════════════════════════════════════════════════════════════════════════

class AdvancedModeOrchestrator:
    """Orchestrates the execution of advanced modes.

    Each mode maps to a specific execution strategy that can:
    - Parse the user's request
    - Spawn sub-agents with specific configurations
    - Enforce quality gates
    - Track progress via the goal tree
    - Store evidence and trajectories
    """

    def __init__(self) -> None:
        self.state_manager = get_state_manager()
        self._mode_handlers: Dict[str, str] = {
            # Maps mode_id to a strategy description
            "vibe-infinity": "autonomous_director",
            "advisor-infinity": "intelligent_governor",
            "forge": "project_factory",
            "swarm-foundry": "dynamic_specialist_factory",
            "multiverse": "solution_tournament",
            "proof": "evidence_system",
            "reality-lab": "reality_simulation",
            "archaeologist": "deep_project_understanding",
            "evolve": "learning_system",
            "sentinel": "security_supervisor",
            "autonomous": "full_autonomous",
        }

    def activate_mode(self, mode_id: str) -> Dict[str, Any]:
        """Activate an advanced mode, returning session info."""
        mode_def = get_advanced_mode(mode_id)
        if not mode_def:
            return {"error": f"Unknown advanced mode: {mode_id}", "success": False}

        session = self.state_manager.get_or_create_session(mode_id)
        session.state = ModeState.ACTIVE
        self.state_manager.update_session(session)

        record_trajectory_entry(session, "mode_activated", f"Mode {mode_id} activated")
        # The trajectory append is intentionally separate from the session
        # snapshot, so persist once more after recording it.  Otherwise the
        # JSONL file and the status endpoint disagree after activation.
        self.state_manager.update_session(session)

        return {
            "success": True,
            "mode_id": mode_id,
            "session_id": session.session_id,
            "state": session.state.value,
            "display_name": mode_def.get("display_name", mode_id),
            "description": mode_def.get("description", ""),
            "config": mode_def.get("config", {}),
            "message": f"✨ **{mode_def.get('display_name', mode_id)}** ativado. {mode_def.get('description', '')}",
        }

    def deactivate_mode(self, mode_id: str) -> Dict[str, Any]:
        """Deactivate an advanced mode."""
        self.state_manager.deactivate_mode(mode_id)
        return {
            "success": True,
            "mode_id": mode_id,
            "message": f"Modo **{mode_id}** desativado.",
        }

    def get_mode_status(self, mode_id: str) -> Dict[str, Any]:
        """Get the status of a mode and its sessions."""
        mode_def = get_advanced_mode(mode_id)
        sessions = self.state_manager.list_sessions(mode_id)
        is_active = self.state_manager.is_mode_active(mode_id)
        active_sessions = [s for s in sessions if s.get("active")]
        runtime = MODE_RUNTIME_STATUS.get(
            mode_id,
            {"status": "unknown", "role": "unknown", "summary": "No runtime contract is registered."},
        )

        return {
            "mode_id": mode_id,
            "display_name": mode_def.get("display_name", mode_id) if mode_def else mode_id,
            "description": mode_def.get("description", "") if mode_def else "",
            "group": mode_def.get("group", "") if mode_def else "",
            "icon": mode_def.get("icon", "bot") if mode_def else "bot",
            "color": mode_def.get("color", "#888888") if mode_def else "#888888",
            "active": is_active,
            # ``session_count`` is kept as the active count for compatibility
            # with the existing UI.  Historical sessions remain available
            # separately instead of being presented as live work.
            "session_count": len(active_sessions),
            "active_session_count": len(active_sessions),
            "total_session_count": len(sessions),
            "sessions": sessions[:5],  # Last 5
            "available": mode_def is not None,
            "config": mode_def.get("config", {}) if mode_def else {},
            "runtime_status": runtime["status"],
            "runtime_role": runtime["role"],
            "runtime_summary": runtime["summary"],
            "handler": self._mode_handlers.get(mode_id),
        }

    def get_all_statuses(self) -> Dict[str, Any]:
        """Get status of all advanced modes."""
        modes = get_advanced_modes()
        groups = get_mode_groups()
        result = {}
        for mode_id in modes:
            result[mode_id] = self.get_mode_status(mode_id)
        return {
            "modes": result,
            "groups": groups,
            "active_count": len(self.state_manager.list_active_modes()),
            "total_count": len(modes),
        }

    def prepare_mode_context(self, mode_id: str, user_request: str) -> Dict[str, Any]:
        """Prepare the augmented system prompt and configuration for a mode.

        This is called by the chat pipeline to inject mode-specific
        instructions and constraints into the agent's context.
        """
        mode_def = get_advanced_mode(mode_id)
        if not mode_def:
            return {"addon": "", "config": {}}

        session = self.state_manager.get_or_create_session(mode_id)

        # Add goal to tree
        goal_id = add_goal_to_session(session, user_request)
        update_goal_state(session, goal_id, GoalNodeState.IN_PROGRESS)

        # Create checkpoint
        create_checkpoint(session)

        # Record trajectory
        record_trajectory_entry(session, "request_received", user_request, {
            "goal_id": goal_id,
            "mode_config": mode_def.get("config", {}),
        })

        self.state_manager.update_session(session)

        # Build system prompt addon with session context
        base_prompt = self._render_mode_prompt(mode_def)
        session_context = f"""
SESSION CONTEXT:
- Mode: {mode_id} (v{mode_def.get('version', '1.0')})
- Session: {session.session_id}
- Goal Tree Root: {goal_id}
- Active Checkpoints: {len(session.checkpoints)}
- Evidence Entries: {len(session.evidence_book)}
- Trajectory Events: {len(session.trajectory)}
"""

        return {
            "addon": base_prompt + session_context,
            "config": mode_def.get("config", {}),
            "session_id": session.session_id,
            "goal_id": goal_id,
        }

    @staticmethod
    def _render_mode_prompt(mode_def: Dict[str, Any]) -> str:
        """Render known catalog placeholders without interpreting literal JSON braces."""
        prompt = str(mode_def.get("system_prompt_addon", ""))
        config = mode_def.get("config", {}) or {}
        replacements: Dict[str, Any] = {
            key: value for key, value in config.items()
            if isinstance(key, str)
        }
        replacements.update({
            "max_debate_rounds": config.get("max_debate_rounds"),
            "max_specialists": config.get("max_specialists"),
            "confidence_threshold": (config.get("evidence_book") or {}).get("confidence_threshold"),
            "personas": config.get("personas"),
            "map_includes": config.get("map_includes"),
            "memory_types": config.get("memory_types"),
            "min_evidence_count": (config.get("rule_proposal") or {}).get("min_evidence_count"),
            "risk_levels": config.get("risk_levels"),
            "evaluation_criteria": config.get("evaluation_criteria"),
            "hybrid_max_complexity_delta": config.get("hybrid_max_complexity_delta"),
        })
        for key, value in replacements.items():
            if value is None:
                continue
            rendered = (
                json.dumps(value, ensure_ascii=False, indent=2, default=str)
                if isinstance(value, (dict, list, tuple))
                else str(value)
            )
            prompt = prompt.replace("{" + key + "}", rendered)
        return prompt

    def build_active_execution_profile(self, user_request: str = "") -> Dict[str, Any]:
        """Compose persistent modes into one bounded, inspectable execution profile.

        Active modes are policy switches, not independent workers.  A composite
        mode wins over its children, while non-composite modes contribute a
        compact contract to the prompt.  This prevents eleven full prompts from
        fighting for control or overflowing the context window.
        """
        active_ids = [mid for mid in self.state_manager.list_active_modes() if get_advanced_mode(mid)]
        active_ids.sort(key=lambda mid: (MODE_PRIORITY.index(mid) if mid in MODE_PRIORITY else 999, mid))
        if not active_ids:
            return {
                "active_mode_ids": [],
                "applied_mode_ids": [],
                "policy_mode_ids": [],
                "primary_mode": None,
                "preferred_agent": None,
                "force_autonomous": False,
                "addon": "",
                "summary": "No advanced mode is armed.",
            }

        if "autonomous" in active_ids:
            primary_mode = "autonomous"
            applied_ids = ["autonomous"]
            # Autonomous is the explicit bundle: its policy layer includes the
            # whole suite even when the individual cards are not separately
            # armed.  They are compact contracts, not claims that ten workers
            # have been spawned.
            policy_ids = list(MODE_PRIORITY)
        elif "vibe-infinity" in active_ids:
            primary_mode = "vibe-infinity"
            applied_ids = ["vibe-infinity"]
            policy_ids = [mid for mid in active_ids if mid != "vibe-infinity"]
        else:
            primary_mode = active_ids[0]
            applied_ids = [primary_mode]
            policy_ids = [mid for mid in active_ids if mid != primary_mode]

        lines = [
            "[ACTIVE ADVANCED EXECUTION PROFILE]",
            f"Primary strategy: {primary_mode}",
            f"Armed modes: {', '.join(active_ids)}",
            "Active means this contract is applied to the request; it does not prove that a specialist has run.",
            "Do not report a worker, test, gate, or evidence item as executed unless an observable event or artifact proves it.",
        ]
        profile_mode_ids = [primary_mode, *policy_ids] if primary_mode == "autonomous" else active_ids
        for mode_id in dict.fromkeys(profile_mode_ids):
            runtime = MODE_RUNTIME_STATUS.get(mode_id)
            if runtime:
                lines.append(f"- {mode_id} ({runtime['role']}): {runtime['summary']}")

        if user_request:
            lines.append(f"Request scope: {user_request[:240]}")

        return {
            "active_mode_ids": active_ids,
            "applied_mode_ids": applied_ids,
            "policy_mode_ids": policy_ids,
            "primary_mode": primary_mode,
            "preferred_agent": MODE_PREFERRED_AGENTS.get(primary_mode),
            "force_autonomous": primary_mode in COMPOSITE_MODES,
            "addon": "\n".join(lines),
            "summary": f"{primary_mode} with {len(policy_ids)} policy mode(s).",
        }

    def prepare_active_execution_profile(self, user_request: str = "") -> Dict[str, Any]:
        """Build the active profile and persist one resumable request marker."""
        profile = self.build_active_execution_profile(user_request)
        primary_mode = profile.get("primary_mode")
        if not primary_mode:
            return profile

        session = self.state_manager.get_or_create_session(primary_mode)
        goal_id = add_goal_to_session(session, user_request or "Advanced execution request")
        update_goal_state(session, goal_id, GoalNodeState.IN_PROGRESS)
        checkpoint_id = create_checkpoint(session)
        record_trajectory_entry(
            session,
            "active_profile_applied",
            user_request or "Advanced execution request",
            {
                "goal_id": goal_id,
                "checkpoint_id": checkpoint_id,
                "active_mode_ids": profile["active_mode_ids"],
                "applied_mode_ids": profile["applied_mode_ids"],
            },
        )
        self.state_manager.update_session(session)
        profile.update({
            "session_id": session.session_id,
            "goal_id": goal_id,
            "checkpoint_id": checkpoint_id,
        })
        return profile

    def get_preferred_agent(self, mode_id: str) -> Optional[str]:
        """Return the safe existing agent selected by an explicit command."""
        return MODE_PREFERRED_AGENTS.get(mode_id)

    def _analyze_claim(
        self,
        claim: str,
        evidence_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Analyse a completion claim across multiple dimensions."""
        claim_lower = claim.lower()
        findings: List[str] = []
        missing_categories: List[str] = []
        debate_questions: List[str] = []

        REQUIRED_EVIDENCE = [
            ("tests_passed", ["test", "spec", "coverage", "passing"]),
            ("edge_cases_covered", ["edge case", "corner case", "boundary", "invalid input"]),
            ("security_reviewed", ["security", "vulnerability", "cve", "audit", "threat"]),
            ("documentation_complete", ["doc", "readme", "documentation", "api spec", "guide"]),
            ("regression_free", ["regression", "existing test", "still pass", "broke nothing"]),
        ]

        VAGUE_PATTERNS = [
            "it works", "should be fine", "trust me", "i think",
            "probably", "seems to work", "looks good", "as expected",
            "i believe", "in my opinion", "roughly",
        ]

        SPECIFIC_INDICATORS = [
            "file", "function", "class", "method", "line",
            "commit", "pr", "merge", "branch",
        ]

        VERIFICATION_INDICATORS = [
            "test", "verify", "check", "confirm", "prove",
            "validate", "assert", "ensure", "guarantee",
        ]

        # Check evidence categories
        for category, indicators in REQUIRED_EVIDENCE:
            category_present = False
            if evidence_summary and category in evidence_summary:
                category_present = bool(evidence_summary[category])
            if not category_present:
                found_in_claim = any(ind in claim_lower for ind in indicators)
                if not found_in_claim:
                    missing_categories.append(category)
                    findings.append(f"Missing evidence category: {category}")

        # Check for vague claims
        for pattern in VAGUE_PATTERNS:
            if pattern in claim_lower:
                findings.append(f"Vague claim: '{pattern}' — needs concrete evidence")

        # Check for missing specifics
        has_specifics = any(ind in claim_lower for ind in SPECIFIC_INDICATORS)
        if not has_specifics and claim_lower.strip():
            findings.append("No specific files, functions, or code references")

        # Check for missing verification method
        has_verification = any(ind in claim_lower for ind in VERIFICATION_INDICATORS)
        if not has_verification:
            findings.append("No verification method mentioned — how was this validated?")

        # Count evidence provided
        evidence_count = len(evidence_summary) if evidence_summary else 0
        if evidence_count < 3:
            findings.append(f"Only {evidence_count} evidence categories provided (minimum: 3)")

        # Determine intervention level
        if missing_categories or evidence_count < 2:
            intervention = InterventionLevel.COMPLETION_BLOCK
            debate_questions = [
                "What was actually implemented and how?",
                "What proof exists that it works correctly?",
                "What failure modes were considered?",
                "How were edge cases handled?",
                "What tests verify this change?",
                "Is this truly complete and production-ready?",
            ]
        elif len(findings) >= 3:
            intervention = InterventionLevel.MANDATORY_FIX
        elif evidence_count < 4:
            intervention = InterventionLevel.SUGGESTION
        else:
            intervention = InterventionLevel.SUGGESTION

        return {
            "intervention_level": intervention.value,
            "intervention_name": intervention.name,
            "findings": findings,
            "missing_categories": missing_categories,
            "debate_questions": debate_questions,
            "evidence_count": evidence_count,
            "verdict": "BLOCKED" if intervention == InterventionLevel.COMPLETION_BLOCK else "PENDING",
            "confidence": max(0, min(100, (evidence_count / 5) * 100 - len(findings) * 10)),
        }

    def record_completion_attempt(
        self,
        mode_id: str,
        session_id: str,
        claim: str,
        evidence_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record a completion attempt. For advisor-infinity mode, this triggers
        the full debate protocol with multi-dimensional claim analysis."""
        session = self.state_manager.get_session(mode_id, session_id)
        if not session:
            return {"blocked": False, "error": "Session not found"}

        record_trajectory_entry(session, "completion_claimed", claim, {
            "evidence": evidence_summary,
        })

        # For advisor mode, run the full analysis pipeline
        if mode_id == "advisor-infinity":
            analysis = self._analyze_claim(claim, evidence_summary)
            intervention_level = analysis["intervention_level"]

            # Store intervention
            intervention = {
                "level": intervention_level,
                "name": analysis["intervention_name"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": "; ".join(analysis["findings"]) if analysis["findings"] else "No specific findings",
                "missing_categories": analysis["missing_categories"],
                "debate_questions": analysis["debate_questions"],
                "confidence": analysis["confidence"],
            }
            session.interventions.append(intervention)
            self.state_manager.update_session(session)

            is_blocked = intervention_level >= InterventionLevel.COMPLETION_BLOCK.value

            return {
                "blocked": is_blocked,
                "intervention_level": analysis["intervention_name"].lower(),
                "intervention_value": intervention_level,
                "reason": intervention["reason"],
                "findings": analysis["findings"],
                "missing": analysis["missing_categories"],
                "debate_questions": analysis["debate_questions"],
                "confidence": analysis["confidence"],
                "verdict": analysis["verdict"],
                "total_interventions": len(session.interventions),
            }

        self.state_manager.update_session(session)
        return {"blocked": False, "message": "Completion claim recorded."}

    def evaluate_tournament(
        self,
        entries: List[TournamentEntry],
        criteria_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Evaluate tournament entries and select the winner."""
        if not entries:
            return {"winner": None, "entries": []}

        default_weights = {
            "security": 25,
            "complexity": 15,
            "performance": 20,
            "maintainability": 15,
            "compatibility": 10,
            "test_coverage": 10,
            "dependency_count": 5,
        }
        weights = criteria_weights or default_weights

        # Normalize scores per criterion
        for criterion in weights:
            scores = [e.scores.get(criterion, 0) for e in entries]
            max_score = max(scores) if scores else 1
            if max_score > 0:
                for e in entries:
                    e.scores[criterion] = (e.scores.get(criterion, 0) / max_score) * 100

        # Calculate total weighted score
        for e in entries:
            total = 0.0
            for criterion, weight in weights.items():
                total += e.scores.get(criterion, 0) * (weight / 100)
            e.total_score = round(total, 2)

        # Sort and pick winner
        entries.sort(key=lambda e: e.total_score, reverse=True)
        if entries:
            entries[0].is_winner = True

        return {
            "winner": entries[0].id if entries else None,
            "winner_name": entries[0].name if entries else None,
            "winner_score": entries[0].total_score if entries else 0,
            "entries": [
                {
                    "id": e.id,
                    "name": e.name,
                    "total_score": e.total_score,
                    "scores": e.scores,
                    "is_winner": e.is_winner,
                }
                for e in entries
            ],
        }

    def check_security_gate(
        self,
        action_description: str,
        risk_level: int = 0,
        files_affected: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Check if an action passes the sentinel security gate."""
        findings = []

        # Check risk level
        if risk_level >= 3:
            findings.append(f"⚠️ Risk Level {risk_level}: requires explicit approval")

        # Check dangerous patterns
        dangerous_patterns = [
            ("rm -rf", "Destructive file operation"),
            ("> /dev/", "System device write"),
            ("DROP TABLE", "Destructive database operation"),
            ("format(", "Disk format operation"),
            ("sudo ", "Privileged operation"),
        ]
        for pattern, desc in dangerous_patterns:
            if pattern.lower() in action_description.lower():
                findings.append(f"🔴 {desc} detected: '{pattern}'")

        # Check if production files are affected
        production_indicators = ["prod", "production", "live", "deploy", "release"]
        if files_affected:
            for f in files_affected:
                for indicator in production_indicators:
                    if indicator in f.lower():
                        findings.append(f"🔴 Production file affected: {f}")
                        break

        gate_passed = len(findings) == 0 and risk_level < 3
        return {
            "gate_passed": gate_passed,
            "risk_level": risk_level,
            "findings": findings,
            "requires_approval": risk_level >= 3 or len(findings) > 0,
            "auto_approve": risk_level <= 1 and len(findings) == 0,
        }


# Global orchestrator singleton
_orchestrator: Optional[AdvancedModeOrchestrator] = None


def get_orchestrator() -> AdvancedModeOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AdvancedModeOrchestrator()
    return _orchestrator
