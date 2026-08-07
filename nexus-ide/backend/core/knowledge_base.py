"""Knowledge Base — persistent cross-cycle learning store.

Extends existing CrossSessionMemory and AdvancedMemory with improvement-specific
tiers: knowledge_patterns, knowledge_signatures, knowledge_metrics.
Projects are isolated by project_id namespace.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ImprovementPattern:
    pattern_id: str
    project_id: str
    trigger_conditions: dict[str, Any]
    solution_steps: list[str]
    success_rate: float = 0.0
    confidence: float = 0.0
    times_applied: int = 0
    last_applied: datetime = field(default_factory=lambda: datetime.now(UTC))
    projects_applied_to: list[str] = field(default_factory=list)


@dataclass
class FailureSignature:
    signature_hash: str
    project_id: str
    normalized_error: str
    error_type: str
    file_path: str = ""
    function_name: str = ""
    stack_frames: list[str] = field(default_factory=list)
    root_cause: str = ""
    remediation_skill_id: str | None = None
    occurrence_count: int = 1
    first_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_count: int = 0


@dataclass
class AgentPerformanceHistory:
    agent_type: str
    project_id: str
    task_category: str
    success_rate: float = 0.0
    avg_duration_seconds: float = 0.0
    token_efficiency: float = 0.0
    best_prompt_version: str = ""
    total_runs: int = 0


@dataclass
class SwarmStrategyEffectiveness:
    strategy: str
    project_id: str
    objective_category: str
    success_rate: float = 0.0
    quality_score: float = 0.0
    avg_duration_seconds: float = 0.0
    total_executions: int = 0


@dataclass
class QualityGateBaseline:
    project_id: str
    test_coverage_percent: float = 0.0
    perf_baseline_ms: dict[str, float] = field(default_factory=dict)
    security_baseline: dict[str, Any] = field(default_factory=dict)
    lint_baseline: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class KnowledgeBase:
    """Persistent cross-cycle learning store built on existing memory infrastructure.

    Projects are isolated by project_id. Survives restarts via SQLite backend.
    """

    _instance: KnowledgeBase | None = None

    def __init__(self) -> None:
        self._patterns: dict[str, ImprovementPattern] = {}
        self._signatures: dict[str, FailureSignature] = {}
        self._agent_perf: dict[str, AgentPerformanceHistory] = {}
        self._swarm_eff: dict[str, SwarmStrategyEffectiveness] = {}
        self._quality_baselines: dict[str, QualityGateBaseline] = {}

        self._db_path = Path(__file__).resolve().parent.parent.parent / "data" / "knowledge_base.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_from_db()

    @classmethod
    def get_instance(cls) -> KnowledgeBase:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _init_db(self) -> None:
        import sqlite3
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS improvement_patterns (
                        pattern_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        trigger_conditions TEXT NOT NULL,
                        solution_steps TEXT NOT NULL,
                        success_rate REAL DEFAULT 0.0,
                        confidence REAL DEFAULT 0.0,
                        times_applied INTEGER DEFAULT 0,
                        last_applied TEXT,
                        projects_applied_to TEXT DEFAULT '[]'
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS failure_signatures (
                        signature_hash TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        normalized_error TEXT NOT NULL,
                        error_type TEXT NOT NULL,
                        file_path TEXT DEFAULT '',
                        function_name TEXT DEFAULT '',
                        stack_frames TEXT DEFAULT '[]',
                        root_cause TEXT DEFAULT '',
                        remediation_skill_id TEXT,
                        occurrence_count INTEGER DEFAULT 1,
                        first_seen TEXT,
                        last_seen TEXT,
                        resolved_count INTEGER DEFAULT 0
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_patterns_project ON improvement_patterns(project_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sigs_project ON failure_signatures(project_id)")
                conn.commit()
        except Exception:
            logger.exception("KnowledgeBase DB init failed")

    def _load_from_db(self) -> None:
        import sqlite3
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM improvement_patterns").fetchall()
                for row in rows:
                    p = ImprovementPattern(
                        pattern_id=row["pattern_id"],
                        project_id=row["project_id"],
                        trigger_conditions=json.loads(row["trigger_conditions"]),
                        solution_steps=json.loads(row["solution_steps"]),
                        success_rate=row["success_rate"],
                        confidence=row["confidence"],
                        times_applied=row["times_applied"],
                        last_applied=datetime.fromisoformat(row["last_applied"]) if row["last_applied"] else datetime.now(UTC),
                        projects_applied_to=json.loads(row["projects_applied_to"]),
                    )
                    self._patterns[p.pattern_id] = p

                rows = conn.execute("SELECT * FROM failure_signatures").fetchall()
                for row in rows:
                    s = FailureSignature(
                        signature_hash=row["signature_hash"],
                        project_id=row["project_id"],
                        normalized_error=row["normalized_error"],
                        error_type=row["error_type"],
                        file_path=row["file_path"],
                        function_name=row["function_name"],
                        stack_frames=json.loads(row["stack_frames"]),
                        root_cause=row["root_cause"],
                        remediation_skill_id=row["remediation_skill_id"],
                        occurrence_count=row["occurrence_count"],
                        first_seen=datetime.fromisoformat(row["first_seen"]) if row["first_seen"] else datetime.now(UTC),
                        last_seen=datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else datetime.now(UTC),
                        resolved_count=row["resolved_count"],
                    )
                    self._signatures[s.signature_hash] = s
        except Exception:
            logger.exception("KnowledgeBase load from DB failed")

    def _save_pattern(self, pattern: ImprovementPattern) -> None:
        import sqlite3
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO improvement_patterns
                    (pattern_id, project_id, trigger_conditions, solution_steps, success_rate, confidence, times_applied, last_applied, projects_applied_to)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pattern.pattern_id,
                        pattern.project_id,
                        json.dumps(pattern.trigger_conditions),
                        json.dumps(pattern.solution_steps),
                        pattern.success_rate,
                        pattern.confidence,
                        pattern.times_applied,
                        pattern.last_applied.isoformat(),
                        json.dumps(pattern.projects_applied_to),
                    ),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to save pattern %s", pattern.pattern_id)

    def _save_signature(self, sig: FailureSignature) -> None:
        import sqlite3
        try:
            with sqlite3.connect(str(self._db_path), check_same_thread=False) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO failure_signatures
                    (signature_hash, project_id, normalized_error, error_type, file_path, function_name, stack_frames, root_cause, remediation_skill_id, occurrence_count, first_seen, last_seen, resolved_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sig.signature_hash,
                        sig.project_id,
                        sig.normalized_error,
                        sig.error_type,
                        sig.file_path,
                        sig.function_name,
                        json.dumps(sig.stack_frames),
                        sig.root_cause,
                        sig.remediation_skill_id,
                        sig.occurrence_count,
                        sig.first_seen.isoformat(),
                        sig.last_seen.isoformat(),
                        sig.resolved_count,
                    ),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to save signature %s", sig.signature_hash)

    def store_pattern(self, pattern_id: str, project_id: str, trigger_conditions: dict[str, Any], solution_steps: list[str], confidence: float = 0.0) -> ImprovementPattern:
        pattern = ImprovementPattern(
            pattern_id=pattern_id,
            project_id=project_id,
            trigger_conditions=trigger_conditions,
            solution_steps=solution_steps,
            confidence=confidence,
        )
        self._patterns[pattern_id] = pattern
        self._save_pattern(pattern)
        return pattern

    def record_signature(self, signature_hash: str, project_id: str, normalized_error: str, error_type: str, file_path: str = "", function_name: str = "", stack_frames: list[str] | None = None, root_cause: str = "") -> FailureSignature:
        if signature_hash in self._signatures:
            sig = self._signatures[signature_hash]
            sig.occurrence_count += 1
            sig.last_seen = datetime.now(UTC)
            self._save_signature(sig)
            return sig
        sig = FailureSignature(
            signature_hash=signature_hash,
            project_id=project_id,
            normalized_error=normalized_error,
            error_type=error_type,
            file_path=file_path,
            function_name=function_name,
            stack_frames=stack_frames or [],
            root_cause=root_cause,
        )
        self._signatures[signature_hash] = sig
        self._save_signature(sig)
        return sig

    def find_matching_pattern(self, project_id: str, context: dict[str, Any]) -> ImprovementPattern | None:
        best: ImprovementPattern | None = None
        best_score = 0.0
        for pattern in self._patterns.values():
            if pattern.project_id != project_id and pattern.project_id != "*":
                continue
            score = self._match_score(pattern.trigger_conditions, context)
            if score > best_score and pattern.confidence > 0.5:
                best_score = score
                best = pattern
        return best

    def find_matching_signature(self, project_id: str, normalized_error: str, error_type: str) -> FailureSignature | None:
        for sig in self._signatures.values():
            if sig.project_id != project_id and sig.project_id != "*":
                continue
            if sig.error_type == error_type and self._fuzzy_match(sig.normalized_error, normalized_error, 0.85):
                return sig
        return None

    def record_agent_performance(self, agent_type: str, project_id: str, task_category: str, success: bool, duration_seconds: float, tokens_used: int) -> None:
        key = f"{agent_type}:{project_id}:{task_category}"
        if key not in self._agent_perf:
            self._agent_perf[key] = AgentPerformanceHistory(
                agent_type=agent_type,
                project_id=project_id,
                task_category=task_category,
            )
        perf = self._agent_perf[key]
        perf.total_runs += 1
        if perf.total_runs > 0:
            prev_rate = perf.success_rate
            perf.success_rate = ((perf.success_rate * (perf.total_runs - 1)) + (1.0 if success else 0.0)) / perf.total_runs
            perf.avg_duration_seconds = ((perf.avg_duration_seconds * (perf.total_runs - 1)) + duration_seconds) / perf.total_runs
            if tokens_used > 0:
                perf.token_efficiency = ((perf.token_efficiency * (perf.total_runs - 1)) + (tokens_used / max(1, duration_seconds))) / perf.total_runs

    def record_swarm_execution(self, strategy: str, project_id: str, objective_category: str, success: bool, quality_score: float, duration_seconds: float) -> None:
        key = f"{strategy}:{project_id}:{objective_category}"
        if key not in self._swarm_eff:
            self._swarm_eff[key] = SwarmStrategyEffectiveness(
                strategy=strategy,
                project_id=project_id,
                objective_category=objective_category,
            )
        eff = self._swarm_eff[key]
        eff.total_executions += 1
        if eff.total_executions > 0:
            eff.success_rate = ((eff.success_rate * (eff.total_executions - 1)) + (1.0 if success else 0.0)) / eff.total_executions
            eff.quality_score = ((eff.quality_score * (eff.total_executions - 1)) + quality_score) / eff.total_executions
            eff.avg_duration_seconds = ((eff.avg_duration_seconds * (eff.total_executions - 1)) + duration_seconds) / eff.total_executions

    def update_quality_baseline(self, project_id: str, **kwargs: Any) -> None:
        if project_id not in self._quality_baselines:
            self._quality_baselines[project_id] = QualityGateBaseline(project_id=project_id)
        baseline = self._quality_baselines[project_id]
        for key, value in kwargs.items():
            if hasattr(baseline, key):
                setattr(baseline, key, value)
        baseline.updated_at = datetime.now(UTC)

    def get_quality_baseline(self, project_id: str) -> QualityGateBaseline | None:
        return self._quality_baselines.get(project_id)

    def stats(self) -> dict[str, Any]:
        return {
            "total_patterns": len(self._patterns),
            "total_signatures": len(self._signatures),
            "total_agent_perf": len(self._agent_perf),
            "total_swarm_eff": len(self._swarm_eff),
            "total_quality_baselines": len(self._quality_baselines),
        }

    @staticmethod
    def _match_score(trigger: dict[str, Any], context: dict[str, Any]) -> float:
        if not trigger or not context:
            return 0.0
        matches = 0
        total = 0
        for key, value in trigger.items():
            total += 1
            if key in context and str(context[key]).lower() == str(value).lower():
                matches += 1
        return matches / total if total > 0 else 0.0

    @staticmethod
    def _fuzzy_match(a: str, b: str, threshold: float) -> bool:
        if not a or not b:
            return a == b
        a_lower = a.lower()
        b_lower = b.lower()
        if a_lower in b_lower or b_lower in a_lower:
            return True
        words_a = set(a_lower.split())
        words_b = set(b_lower.split())
        if not words_a or not words_b:
            return False
        overlap = len(words_a & words_b) / max(1, len(words_a | words_b))
        return overlap >= threshold


class SkillEvolutionEngine:
    """Evolves skills based on usage outcomes.

    - Promotes high-success skills to auto_apply
    - Deprecates failing skills
    - Merges similar skills
    - Generates composite skills from sequences
    """

    _instance: SkillEvolutionEngine | None = None

    def __init__(self) -> None:
        self._evolution_log: list[dict[str, Any]] = []

    @classmethod
    def get_instance(cls) -> SkillEvolutionEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def evolve_skills(self, cycle_results: list[ImprovementProposal]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        try:
            from backend.core.skills_store import SkillsStore
            store = SkillsStore.get_instance()
            skills = store.list_skills(limit=200)

            for skill in skills:
                if skill.confidence >= 0.7 and skill.times_used >= 20 and not skill.auto_apply:
                    skill.auto_apply = True
                    store.record_use(skill.id, success=True)
                    changes.append({"type": "promote", "skill_id": skill.id, "reason": "high_success"})

                if skill.times_used >= 20 and skill.confidence <= 0.1:
                    store.delete_skill(skill.id)
                    changes.append({"type": "deprecate", "skill_id": skill.id, "reason": "low_success"})

            similar_pairs = self._find_similar_skills(skills)
            for skill_a, skill_b, score in similar_pairs:
                merged = self._merge_skills(store, skill_a, skill_b)
                if merged:
                    changes.append({"type": "merge", "skill_a": skill_a.id, "skill_b": skill_b.id, "merged_into": merged.id})

        except Exception:
            logger.exception("Skill evolution failed")
        return changes

    def _find_similar_skills(self, skills: list[Any]) -> list[tuple[Any, Any, float]]:
        from difflib import SequenceMatcher
        pairs: list[tuple[Any, Any, float]] = []
        for i in range(len(skills)):
            for j in range(i + 1, len(skills)):
                score = SequenceMatcher(None, skills[i].name, skills[j].name).ratio()
                if score >= 0.85:
                    pairs.append((skills[i], skills[j], score))
        return pairs

    def _merge_skills(self, store: Any, skill_a: Any, skill_b: Any) -> Any | None:
        try:
            merged_name = f"{skill_a.name}+{skill_b.name}"
            merged_steps = list(dict.fromkeys(skill_a.steps + skill_b.steps))
            merged = store.create_skill(
                name=merged_name,
                skill_type=skill_a.skill_type,
                description=f"Merged: {skill_a.description} + {skill_b.description}",
                trigger_pattern=f"{skill_a.trigger_pattern},{skill_b.trigger_pattern}",
                steps=merged_steps,
                verification=skill_a.verification or skill_b.verification,
                tags=list(set(skill_a.tags + skill_b.tags)),
                source="evolution",
                auto_apply=False,
            )
            store.delete_skill(skill_a.id)
            store.delete_skill(skill_b.id)
            return merged
        except Exception:
            logger.exception("Skill merge failed")
            return None

    def stats(self) -> dict[str, Any]:
        return {"evolution_events": len(self._evolution_log)}
