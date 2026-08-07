# Autonomous Continuous Improvement System — Implementation Plan

## Executive Summary

Build a **self-hosted, generalizable autonomous continuous improvement system** that:
1. **Dogfoods on NEXUS IDE** — continuously improves its own codebase
2. **Exports as a reusable framework** — applicable to any project via configuration
3. **Unifies existing loops** — auto-correction, self-healing, continuous improvement, swarm orchestration into a single meta-loop
4. **Learns across cycles** — persistent knowledge transfer, skill evolution, predictive failure prevention
5. **Diagnoses swarm/auto-swarm failures** — root-cause analysis with automated remediation patterns

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS IMPROVEMENT META-LOOP                  │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  │
│  │   ANALYZE   │─▶│   PLAN      │─▶│   EXECUTE   │─▶│   VERIFY   │  │
│  │  (Metrics,  │  │  (Proposals,│  │  (Swarm,    │  │  (Tests,   │  │
│  │   Logs,     │  │   Skills,   │  │   Agents,   │  │   Quality, │  │
│  │   History)  │  │   Budget)   │  │   Tools)    │  │   Gates)   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘  │
│        ▲                                                     │       │
│        │              ┌─────────────────────────────────────┘       │
│        │              ▼                                             │
│        │  ┌─────────────────┐                                      │
│        └──│  LEARN & EVOLVE │◀─────────────────────────────────────┘
│           │  (Skills,       │
│           │   Patterns,     │
│           │   Meta-Learning)│
│           └─────────────────┘
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Unified Meta-Loop Coordinator (Week 1-2)

### 1.1 Create `AutonomousImprovementOrchestrator` 
**File:** `backend/orchestrator/autonomous_improvement_orchestrator.py`

```python
class AutonomousImprovementOrchestrator:
    """
    Single coordinator that unifies:
    - AutoCorrectionLoop (reactive: test failures, critical errors)
    - ContinuousImprovementLoop (proactive: periodic analysis)
    - SelfHealingEngine (active: applies improvements with quality gates)
    - SwarmOrchestrator (parallel execution for complex improvements)
    - SelfImprovementLoop (metrics-driven optimization)
    """
    
    def __init__(self, config: AutonomousImprovementConfig):
        self.config = config
        self.correction_loop = get_auto_correction_loop()
        self.continuous_loop = get_continuous_improvement_loop()
        self.healing_engine = SelfHealingEngine(...)
        self.swarm = SwarmOrchestrator(...)
        self.metrics_loop = SelfImprovementLoop(...)
        self.knowledge_base = KnowledgeBase()  # extends existing memory system
        self.failure_analyzer = SwarmFailureAnalyzer()  # structured hash + fuzzy match
        self.recovery_strategies = SwarmRecoveryStrategies()
        # Budget enforcement: NONE at orchestrator level
        # Relies on AgentLifecycleManager per-agent limits (MAX_CONCURRENT_AGENTS_GLOBAL=20, token_budget=100k)
```

**Key responsibilities:**
- Single entry point for all improvement cycles
- Prioritizes work: critical fixes > performance > refactoring > exploration
- Emits unified events to Agent Bus for dashboard visibility
- **No cross-system budget enforcement** — relies on AgentLifecycleManager limits

### 1.2 Configuration System (12-factor: Env > YAML > Code)
**File:** `backend/config/autonomous_improvement.yaml` + `backend/config/settings.py` extension

```yaml
# Core settings (all overridable via NEXUS_AI_* env vars)
enabled: true
mode: "dogfood"  # dogfood | framework | ci_cd | production
target_projects:
  - path: "."
    name: "nexus-ide"
    priority: 1

# Cycle configuration
cycle_interval_minutes: 30
max_concurrent_improvements: 3
# Budget limits NOT enforced at orchestrator level
# Per-agent limits via AgentLifecycleManager:
#   MAX_CONCURRENT_AGENTS_GLOBAL = 20
#   MAX_CONCURRENT_AGENTS_PER_TYPE = 5
#   DEFAULT_TOKEN_BUDGET = 100_000
#   DEFAULT_TIME_BUDGET_SECONDS = 600

# Safety rails
auto_apply_threshold: 0.85
require_meta_approval: true
circuit_breaker:
  max_failures_per_hour: 5
  cooldown_minutes: 30

# Learning
skill_retention_days: 30
cross_project_learning: true
failure_pattern_min_occurrences: 3
```

**Precedence (implemented in `get_autonomous_improvement_config()`):**
1. Environment variables: `NEXUS_AI_ENABLED`, `NEXUS_AI_MODE`, `NEXUS_AI_CYCLE_INTERVAL_MINUTES`, etc.
2. YAML config file: `backend/config/autonomous_improvement.yaml`
3. Code defaults in `AutonomousImprovementConfig` dataclass

### 1.3 Quality Gates Implementation

**Decision:** Extend `SelfHealingEngine._run_quality_gate()` as the single unified quality gate.

```python
# In backend/core/self_healing_engine.py

async def _run_quality_gate(self, project_path: str = ".") -> QualityGateResult:
    """Unified quality gate: pytest + ruff + bandit + custom perf checks."""
    results = {}
    
    # 1. Tests (existing)
    test_result = await self._run_tests(project_path)
    results["tests"] = test_result
    
    # 2. Lint (ruff)
    lint_result = await self._run_lint(project_path)
    results["lint"] = lint_result
    
    # 3. Security (bandit)
    security_result = await self._run_security_scan(project_path)
    results["security"] = security_result
    
    # 4. Performance (custom benchmarks if exist)
    perf_result = await self._run_perf_benchmarks(project_path)
    results["performance"] = perf_result
    
    # 5. Type check (mypy/pyright if configured)
    type_result = await self._run_type_check(project_path)
    results["types"] = type_result
    
    # Aggregate verdict
    passed = all(r.passed for r in results.values())
    return QualityGateResult(passed=passed, details=results)
```

**Integration points:**
- `SelfHealingEngine` uses this for pre/post apply verification
- `AutonomousImprovementOrchestrator` calls this after any improvement execution
- `META_ANALYZER` receives results for final approval
- `SwarmRecoveryStrategies` uses test results to verify recovery

---

## Phase 2: Cross-Cycle Knowledge Base (Week 2-3)

### 2.1 Persistent Knowledge Base (extends existing memory system)
**File:** `backend/core/knowledge_base.py`

**Decision:** Extend `backend/memory/cross_session_memory.py` and `backend/memory/advanced_memory.py` rather than create separate storage. Projects isolated via `project_id` namespace.

```python
class KnowledgeBase:
    """
    Persistent cross-cycle learning store built on existing memory infrastructure.
    Projects isolated by project_id. Survives restarts via SQLite backend.
    """
    
    # Uses existing CrossSessionMemory + AdvancedMemory as backing store
    # New memory tiers: 'knowledge_patterns', 'knowledge_signatures', 'knowledge_metrics'
    
    SCHEMAS = {
        "improvement_patterns": {
            "pattern_id": "str",
            "project_id": "str",  # namespace isolation
            "trigger_conditions": "dict",  # {error_types: [], file_patterns: [], metrics: {}}
            "solution_steps": "list[str]",  # validated, executable steps
            "success_rate": "float",
            "confidence": "float",
            "times_applied": "int",
            "last_applied": "datetime",
            "projects_applied_to": "list[str]",
        },
        "failure_signatures": {
            "signature_hash": "str",  # SHA256(error_type + file + function + top3_frames)
            "project_id": "str",
            "normalized_error": "str",  # error msg with paths/line-nums stripped
            "root_cause": "str",
            "remediation_skill_id": "str | None",
            "occurrence_count": "int",
            "first_seen": "datetime",
            "last_seen": "datetime",
            "resolved_count": "int",
        },
        "agent_performance_history": {
            "agent_type": "str",
            "project_id": "str",
            "task_category": "str",  # implementation, review, debug, research, etc.
            "success_rate": "float",
            "avg_duration_seconds": "float",
            "token_efficiency": "float",  # output_tokens / input_tokens
            "best_prompt_version": "str",  # git commit hash of prompt
            "total_runs": "int",
        },
        "swarm_strategy_effectiveness": {
            "strategy": "str",  # divide|ensemble|pipeline|debate
            "project_id": "str",
            "objective_category": "str",  # feature, bugfix, refactor, research
            "success_rate": "float",
            "quality_score": "float",  # post-verification quality
            "avg_duration_seconds": "float",
            "total_executions": "int",
        },
        "quality_gate_baselines": {
            "project_id": "str",
            "test_coverage_percent": "float",
            "perf_baseline_ms": "dict[str, float]",  # endpoint -> p95 latency
            "security_baseline": "dict",  # bandit/safety counts
            "lint_baseline": "int",  # ruff error count
            "updated_at": "datetime",
        },
    }
```

**Integration with existing memory:**
- `CrossSessionMemory.store()` / `recall()` with `memory_tier="knowledge_*"`
- `AdvancedMemory` for semantic search over patterns/signatures
- `project_id` derived from `project_path` (hash of absolute path)

### 2.2 Skill Evolution Engine
**File:** `backend/core/skill_evolution.py`

```python
class SkillEvolutionEngine:
    """
    Evolves skills based on usage outcomes:
    - Promotes high-success skills to auto_apply
    - Deprecates failing skills
    - Merges similar skills
    - Generates composite skills from sequences
    """
    
    async def evolve_skills(self, cycle_results: CycleResults) -> list[SkillChange]:
        # 1. Update skill confidence from results
        # 2. Detect skill combinations that frequently co-occur
        # 3. Propose merged/composite skills
        # 4. Archive skills with < 10% success after 20 uses
        # 5. Export skill pack for other projects
```

---

## Phase 3: Swarm & Auto-Swarm Failure Diagnostics (Week 3-4)

### 3.1 Swarm Failure Analyzer
**File:** `backend/orchestrator/swarm_failure_analyzer.py`

**Decision:** Failure signatures use **structured hash + normalized fuzzy match**.
- Hash = SHA256(error_type + file_path + function_name + top_3_stack_frames)
- Normalized error = strip file paths, line numbers, variable values from message
- Match: exact hash first → fallback to fuzzy match (levenshtein > 0.85) on normalized error

```python
class SwarmFailureAnalyzer:
    """
    Diagnoses WHY swarm/auto-swarm executions fail.
    Produces structured root-cause reports with remediation.
    """
    
    FAILURE_CATEGORIES = {
        "agent_timeout": "Agent exceeded time budget",
        "tool_execution_failed": "Tool returned error",
        "context_overflow": "Token budget exceeded",
        "contradiction_detected": "Agents produced conflicting outputs",
        "synthesis_failed": "LLM merge failed",
        "quality_gate_failed": "Post-execution tests failed",
        "resource_exhaustion": "Global limits hit",
        "cascading_failure": "One agent failure blocked others",
    }
    
    def _compute_signature(self, failure: SwarmFailure) -> FailureSignature:
        # 1. Extract primary error from failed agent output
        error_type = self._classify_error(failure.error_output)
        file_path, function_name = self._extract_location(failure.error_output)
        stack_frames = self._extract_stack_frames(failure.error_output, top_n=3)
        
        # 2. Structured hash for exact matching
        hash_input = f"{error_type}|{file_path}|{function_name}|{'|'.join(stack_frames)}"
        signature_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        
        # 3. Normalized error for fuzzy matching
        normalized = self._normalize_error(failure.error_output)
        
        return FailureSignature(
            signature_hash=signature_hash,
            normalized_error=normalized,
            error_type=error_type,
            file_path=file_path,
            function_name=function_name,
            stack_frames=stack_frames,
        )
    
    async def analyze_failure(
        self, 
        swarm_result: SwarmResult, 
        objective: str,
        session_id: str
    ) -> FailureDiagnosis:
        # 1. Classify failure category
        # 2. Compute signature
        # 3. Query KnowledgeBase: exact hash match → fuzzy match → no match
        # 4. If matched → return existing remediation skill
        # 5. If novel → generate new remediation proposal via META_ANALYZER
        # 6. Store new signature in KnowledgeBase
```

### 3.2 Auto-Swarm Recovery Strategies
**File:** `backend/orchestrator/swarm_recovery.py`

```python
class SwarmRecoveryStrategies:
    """
    Pre-defined recovery patterns for each failure category.
    Applied automatically when signature matches known pattern.
    """
    
    RECOVERY_PLAYBOOKS = {
        "agent_timeout": [
            {"action": "retry_with_larger_budget", "params": {"token_multiplier": 2, "time_multiplier": 1.5}},
            {"action": "split_into_smaller_subtasks", "params": {"max_subtask_tokens": 8000}},
            {"action": "use_faster_model", "params": {"model_key": "fast"}},
        ],
        "tool_execution_failed": [
            {"action": "retry_with_debugger_first", "params": {}},
            {"action": "fallback_to_alternative_tool", "params": {}},
        ],
        "context_overflow": [
            {"action": "enable_context_compression", "params": {}},
            {"action": "split_into_smaller_subtasks", "params": {}},
        ],
        "contradiction_detected": [
            {"action": "run_debate_strategy_with_moderator", "params": {"moderator": "ANALYZER"}},
            {"action": "escalate_to_meta_analyzer", "params": {}},
        ],
        "synthesis_failed": [
            {"action": "retry_with_structured_output", "params": {}},
            {"action": "fallback_to_concatenation", "params": {}},
        ],
        "quality_gate_failed": [
            {"action": "run_fix_cycle", "params": {"max_iterations": 3}},
            {"action": "rollback_and_escalate", "params": {}},
        ],
        "cascading_failure": [
            {"action": "isolate_failing_agent", "params": {}},
            {"action": "retry_with_ensemble_for_redundancy", "params": {}},
            {"action": "fallback_to_single_agent", "params": {"agent": "CODER"}},
        ],
    }
    
    async def execute_recovery(self, diagnosis: FailureDiagnosis, context: RecoveryContext) -> RecoveryResult:
        playbook = self.RECOVERY_PLAYBOOKS.get(diagnosis.category, [])
        for step in playbook:
            result = await self._execute_step(step, context)
            if result.success:
                return RecoveryResult(recovered=True, steps_executed=[step])
        return RecoveryResult(recovered=False, steps_executed=[s["action"] for s in playbook])
```

---

## Phase 4: Predictive Failure Prevention (Week 4-5)

### 4.1 Predictive Failure Detector
**File:** `backend/core/predictive_failure_detector.py`

```python
class PredictiveFailureDetector:
    """
    Uses historical patterns to PREDICT failures before they happen.
    Runs before each improvement cycle.
    """
    
    async def predict_risk(self, proposed_improvement: ImprovementProposal) -> RiskAssessment:
        # 1. Match proposal against failure_signatures
        # 2. Simulate using agent_performance_history
        # 3. Check quality_gate_baselines for regression risk
        # 4. Return risk score + mitigation recommendations
        
    async def should_proceed(self, proposal: ImprovementProposal) -> Decision:
        risk = await self.predict_risk(proposal)
        if risk.score > 0.7:
            return Decision.BLOCK_WITH_REASON(risk.mitigations)
        elif risk.score > 0.4:
            return Decision.REQUIRE_META_APPROVAL(risk.mitigations)
        return Decision.PROCEED
```

### 4.2 Pre-Flight Validation Agent (integrates with META_ANALYZER)
**File:** `backend/agents/preflight_validator.py`

```python
class PreFlightValidatorAgent(AgentBase):
    """
    Runs BEFORE any improvement execution.
    Called by META_ANALYZER as part of approval workflow.
    Validates: feasibility, dependencies, risk, resource availability.
    """
    name = "PREFLIGHT_VALIDATOR"
    model_key = "reasoning"
    prompt_file = "preflight_validator"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.SEARCH_SYMBOLS,
        AgentAction.ANALYZE_DATA,
    }

    async def validate(self, proposal: ImprovementProposal) -> PreFlightReport:
        # 1. Static analysis of target files (imports, complexity, test coverage)
        # 2. Dependency graph impact (what else might break)
        # 3. Test coverage in affected areas (from KnowledgeBase.quality_gate_baselines)
        # 4. Historical success rate for similar changes (from KnowledgeBase.improvement_patterns)
        # 5. Resource budget check (AgentLifecycleManager limits)
        # 6. Risk score from PredictiveFailureDetector
        
        return PreFlightReport(
            feasible=bool,
            risk_score=float,  # 0-1
            blocked_by=list[str],  # missing tests, circular deps, etc.
            recommendations=list[str],
            estimated_effort="low|medium|high",
        )
```

**Integration with META_ANALYZER:**
- `META_ANALYZER.build_approval_report()` calls `PreFlightValidatorAgent.validate()`
- Pre-flight report included in approval decision
- If `risk_score > 0.7` → auto-reject with reason
- If `risk_score > 0.4` → require human review

---

## Phase 5: Meta-Learning Optimization Loop (Week 5-6)

### 5.1 Meta-Learning Optimizer (Thompson Sampling for bandit optimization)
**File:** `backend/core/meta_learning_optimizer.py`

```python
class MetaLearningOptimizer:
    """
    Optimizes the improvement process ITSELF using Thompson Sampling.
    Learns: optimal cycle intervals, agent assignments, strategy selection,
    budget allocation, confidence thresholds.
    """
    
    # Bandit arms = hyperparameter configurations to try
    HYPERPARAMETER_SPACE = {
        "cycle_interval_minutes": [15, 30, 60, 120],
        "auto_apply_threshold": [0.7, 0.8, 0.85, 0.9],
        "max_parallel": [2, 3, 5, 8],
        "strategy_preference": ["divide", "ensemble", "pipeline", "debate", "adaptive"],
    }
    
    # Thompson Sampling: Beta(alpha=successes+1, beta=failures+1) per arm
    # Reward = composite: 0.4*success_rate + 0.3*cycle_efficiency + 0.2*time_to_value + 0.1*(1-regression_rate)
    
    async def optimize_hyperparameters(self, history: list[CycleResult]) -> HyperparameterUpdate:
        # 1. Compute reward for each historical cycle
        # 2. Update Beta posteriors for each hyperparameter value
        # 3. Sample from posteriors → select next configuration
        # 4. Persist optimized config to YAML (with version)
        # 5. Log decision for audit trail
        
        return HyperparameterUpdate(
            cycle_interval_minutes=sampled_value,
            auto_apply_threshold=sampled_value,
            max_parallel=sampled_value,
            strategy_preference=sampled_value,
            confidence=posterior_mean,
            reasoning="Thompson Sampling: arm X had highest sampled reward",
        )
```

**Persistence:** Optimized config written to `backend/config/autonomous_improvement.yaml` with git commit for rollback.

### 5.2 Adaptive Strategy Selector
**File:** `backend/orchestrator/adaptive_strategy_selector.py`

```python
class AdaptiveStrategySelector:
    """
    Replaces hardcoded strategy selection with learned policy.
    """
    
    async def select_strategy(self, objective: str, context: dict) -> StrategyDecision:
        # 1. Embed objective + context
        # 2. Query KnowledgeBase for similar past objectives
        # 3. Return strategy with highest historical success_rate
        # 4. Exploration: occasionally try sub-optimal to discover better
```

---

## Phase 6: Framework Generalization & Export (Week 6-7)

### 6.1 Project-Agnostic Adapter
**File:** `backend/core/project_adapter.py`

```python
class ProjectAdapter:
    """
    Adapts the improvement system to ANY codebase.
    """
    
    def __init__(self, project_root: Path, config: ProjectConfig):
        self.project_root = project_root
        self.config = config
        self.language = self._detect_language()
        self.test_command = self._detect_test_command()
        self.build_command = self._detect_build_command()
        self.lint_command = self._detect_lint_command()
    
    def get_quality_gates(self) -> list[QualityGate]:
        # Returns project-specific gates
    
    def get_agent_registry(self) -> dict[str, AgentBase]:
        # Returns agents relevant to this project's stack
```

### 6.2 Framework Entry Point
**File:** `backend/cli/autonomous_improvement.py`

```bash
# Usage as framework
nexus-improve init                    # Initialize in any project
nexus-improve config --project .      # Configure for current project
nexus-improve run --once              # Single improvement cycle
nexus-improve run --daemon            # Continuous daemon mode
nexus-improve status                  # Show cycle status
nexus-improve export-skills --out ./skills_pack.json
nexus-improve import-skills --in ./skills_pack.json
```

---

## Phase 7: Observability & Dashboarding (Week 7-8)

### 7.1 Unified Improvement Dashboard
**File:** `backend/orchestrator/routes/improvement_dashboard.py`

Real-time dashboard showing:
- Current cycle status & progress
- Improvement pipeline (proposed → approved → executing → verified)
- Swarm execution visualization
- Failure diagnosis timeline
- Skill evolution graph
- Meta-learning parameter trends
- Cross-project comparison (when enabled)

### 7.2 Structured Event Emission
All components emit to Agent Bus under topics:
- `improvement.cycle.started`
- `improvement.proposal.generated`
- `improvement.execution.started|completed|failed`
- `improvement.verification.passed|failed`
- `improvement.skill.evolved`
- `improvement.failure.diagnosed`
- `improvement.meta_learning.updated`

---

## Data Models

### CycleResult (persisted per cycle)
```python
@dataclass
class CycleResult:
    cycle_id: str
    started_at: datetime
    completed_at: datetime
    proposals_generated: int
    proposals_approved: int
    proposals_applied: int
    proposals_verified: int
    proposals_rejected: int
    regressions_introduced: int
    skills_created: int
    skills_evolved: int
    failures_diagnosed: int
    total_tokens: int
    wall_time_seconds: float
    meta_learning_updates: dict
```

### FailureDiagnosis (persisted for learning)
```python
@dataclass
class FailureDiagnosis:
    diagnosis_id: str
    failure_category: str
    root_cause: str
    causal_chain: list[CausalLink]
    matched_signature: str | None  # Links to KnowledgeBase
    remediation_skill_id: str | None
    proposed_remediation: str
    confidence: float
    created_at: datetime
```

---

## Integration Points (Existing Code)

| Existing Component | Integration Method |
|---|---|
| `AutoCorrectionLoop` | Subscribe to `auto_correction.status` events; feed failure diagnoses into KnowledgeBase.failure_signatures |
| `ContinuousImprovementLoop` | Replace `SelfImprovementAnalyzer` with KnowledgeBase-enhanced version that queries patterns/signatures |
| `SelfHealingEngine` | Use as execution backend for approved proposals; extend `_run_quality_gate()` with lint/security/perf/type checks |
| `SwarmOrchestrator` | Wrap `execute_swarm()` with `SwarmFailureAnalyzer`; on failure, invoke `SwarmRecoveryStrategies` |
| `SelfImprovementLoop` | Feed its metrics into `PredictiveFailureDetector` for pre-execution risk assessment |
| `META_ANALYZER` | Final gatekeeper for auto-applied improvements; runs pre-flight validation via `PreFlightValidatorAgent` |
| `SkillsStore` | Extend with `SkillEvolutionEngine` (promotion, deprecation, merging); export/import skill packs |
| `AgentLifecycleManager` | Spawn all improvement agents; enforces per-agent limits (global=20, per-type=5, token=100k, time=600s) |
| `CrossSessionMemory` / `AdvancedMemory` | KnowledgeBase uses these as backing store with `memory_tier="knowledge_*"` and `project_id` isolation |

---

## Acceptance Criteria

### Core Functionality
- [ ] Single `AutonomousImprovementOrchestrator` coordinates all improvement activities
- [ ] Runs continuous cycles every N minutes (configurable)
- [ ] Generates proposals from multiple sources (metrics, failures, patterns, exploration)
- [ ] Applies improvements with quality gates (tests, lint, security, performance)
- [ ] Rolls back on regression detection
- [ ] Persists all cycle results, learns from them

### Learning & Evolution
- [ ] KnowledgeBase survives restarts and accumulates patterns
- [ ] Skills evolve: confidence updates, auto_apply promotion, deprecation
- [ ] Failure signatures captured and matched for instant remediation
- [ ] Meta-learning optimizes hyperparameters over time
- [ ] Cross-project skill transfer works (when enabled)

### Swarm Diagnostics
- [ ] Every swarm failure produces structured `FailureDiagnosis`
- [ ] Known failures resolved via existing skills in < 30 seconds
- [ ] Novel failures generate new remediation proposals
- [ ] Recovery playbooks cover all failure categories

### Framework Generalization
- [ ] `nexus-improve init` works in a fresh Python/JS/Go/Rust project
- [ ] Auto-detects test/lint/build commands
- [ ] Provides relevant agent registry for project's tech stack
- [ ] Exports/imports skill packs

### Observability
- [ ] Real-time dashboard shows cycle status, pipeline, failures, skills
- [ ] All events emitted to Agent Bus for external consumption
- [ ] Evolution log human-readable and queryable

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| Infinite improvement loops | Circuit breaker, max cycles per hour, budget limits |
| Regressions from auto-apply | Quality gates (tests + lint + security + perf), git snapshots, rollback |
| Skill pollution | Confidence thresholds, success rate tracking, auto-deprecation |
| Resource exhaustion | Global agent limits, token budgets, time budgets, priority queue |
| Knowledge base corruption | Schema validation, backup on each cycle, versioned migrations |
| Swarm cascade failures | Isolation, timeouts, fallback strategies, circuit breakers |

---

## Implementation Order

1. **Week 1-2**: AutonomousImprovementOrchestrator + Config + Integration wiring
2. **Week 2-3**: KnowledgeBase + SkillEvolutionEngine + Persistence
3. **Week 3-4**: SwarmFailureAnalyzer + RecoveryStrategies + Integration
4. **Week 4-5**: PredictiveFailureDetector + PreFlightValidator
5. **Week 5-6**: MetaLearningOptimizer + AdaptiveStrategySelector
6. **Week 6-7**: ProjectAdapter + CLI Framework Entry Point
7. **Week 7-8**: Dashboard + Observability + Documentation

---

## Files to Create/Modify

### New Files
```
backend/orchestrator/autonomous_improvement_orchestrator.py
backend/orchestrator/swarm_failure_analyzer.py
backend/orchestrator/swarm_recovery.py
backend/orchestrator/adaptive_strategy_selector.py
backend/core/knowledge_base.py
backend/core/skill_evolution.py
backend/core/predictive_failure_detector.py
backend/core/meta_learning_optimizer.py
backend/core/project_adapter.py
backend/agents/preflight_validator.py
backend/cli/autonomous_improvement.py
backend/config/autonomous_improvement.yaml
```

### Modified Files
```
backend/orchestrator/main.py                      # Wire orchestrator in lifespan
backend/core/auto_correction.py                   # Subscribe to events → KnowledgeBase.failure_signatures
backend/core/continuous_improvement.py            # Use KnowledgeBase-enhanced analyzer
backend/core/self_healing_engine.py               # Extend _run_quality_gate() with lint/security/perf/type checks
backend/orchestrator/swarm.py                     # Wrap execute_swarm with SwarmFailureAnalyzer + RecoveryStrategies
backend/agents/meta_analyzer.py                   # Add pre-flight validation hook; receive quality gate results
backend/core/skills_store.py                      # Add evolution methods (promote, deprecate, merge, export/import)
backend/memory/cross_session_memory.py            # Add knowledge_* memory tiers; project_id isolation
backend/memory/advanced_memory.py                 # Add semantic search for patterns/signatures
backend/config/settings.py                        # Add AutonomousImprovementConfig with 12-factor precedence
backend/observability/routes/improvement_dashboard.py  # New dashboard routes
```

---

## Success Metrics (Dogfooding on NEXUS IDE)

| Metric | Target |
|---|---|
| Cycle time (median) | < 5 minutes |
| Proposal-to-verified ratio | > 60% |
| Regression rate | < 2% |
| Swarm failure diagnosis accuracy | > 90% |
| Skill auto-apply promotion rate | > 30% of created skills |
| Cross-cycle knowledge reuse | > 40% of proposals use existing patterns |
| Meta-learning parameter convergence | Stable within 20 cycles |

---

## Out of Scope (Future Phases)

- Distributed multi-node improvement coordination
- Natural language objective input (vs structured proposals)
- Automatic PR creation for external repositories
- Integration with external CI/CD (GitHub Actions, GitLab CI)
- Multi-project fleet management UI
- LLM-based code modification (vs tool-based)