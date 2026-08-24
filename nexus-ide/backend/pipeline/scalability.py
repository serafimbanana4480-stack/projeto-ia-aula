"""Scalability — multi-tenancy, budget optimization, GPU scaling, NOC 3D.

Phase 11: Escalabilidade e NOC
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# 11-01: Multi-tenancy
# ============================================================================

class TenantIsolationLevel(Enum):
    SHARED = "shared"
    ISOLATED = "isolated"
    DEDICATED = "dedicated"


@dataclass
class TenantConfig:
    tenant_id: str
    name: str
    isolation: TenantIsolationLevel = TenantIsolationLevel.ISOLATED
    rate_limit_per_minute: int = 100
    max_concurrent_workflows: int = 5
    allowed_stacks: list[str] = field(default_factory=lambda: ["python", "typescript", "go"])
    budget_limit_monthly: float = 1000.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "isolation": self.isolation.value,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "max_concurrent_workflows": self.max_concurrent_workflows,
            "allowed_stacks": self.allowed_stacks,
            "budget_limit_monthly": self.budget_limit_monthly,
            "active": self.active,
        }


class TenantManager:
    """Manages multi-tenant isolation and resource allocation."""

    def __init__(self) -> None:
        self._tenants: dict[str, TenantConfig] = {}
        self._rate_limiters: dict[str, list[float]] = {}
        self._active_workflows: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def register(self, config: TenantConfig) -> None:
        with self._lock:
            self._tenants[config.tenant_id] = config
            self._rate_limiters[config.tenant_id] = []
        logger.info("Tenant registered: %s", config.tenant_id)

    def get(self, tenant_id: str) -> TenantConfig | None:
        return self._tenants.get(tenant_id)

    def check_rate_limit(self, tenant_id: str) -> bool:
        """True quando o tenant ativo esta dentro do limite por minuto.

        Tenants inexistentes ou inativos ficam sempre bloqueados.
        """
        tenant = self._tenants.get(tenant_id)
        if not tenant or not tenant.active:
            return False

        now = time.time()
        with self._lock:
            window = [
                ts for ts in self._rate_limiters.get(tenant_id, [])
                if now - ts < 60.0
            ]
            if len(window) >= tenant.rate_limit_per_minute:
                self._rate_limiters[tenant_id] = window
                return False
            window.append(now)
            self._rate_limiters[tenant_id] = window
        return True

    def can_start_workflow(self, tenant_id: str) -> bool:
        """Check if tenant can start a new workflow."""
        tenant = self._tenants.get(tenant_id)
        if not tenant or not tenant.active:
            return False

        with self._lock:
            return self._active_workflows[tenant_id] < tenant.max_concurrent_workflows

    def workflow_started(self, tenant_id: str) -> None:
        with self._lock:
            self._active_workflows[tenant_id] += 1

    def workflow_completed(self, tenant_id: str) -> None:
        with self._lock:
            self._active_workflows[tenant_id] = max(0, self._active_workflows[tenant_id] - 1)

    def namespace_key(self, tenant_id: str, key: str) -> str:
        """Create a tenant-isolated key for storage."""
        return f"tenant:{tenant_id}:{key}"

    def list_tenants(self) -> list[TenantConfig]:
        return list(self._tenants.values())

    def get_usage_stats(self, tenant_id: str) -> dict[str, Any]:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return {}

        with self._lock:
            return {
                "tenant_id": tenant_id,
                "active_workflows": self._active_workflows[tenant_id],
                "rate_limit_used": len(self._rate_limiters.get(tenant_id, [])),
                "rate_limit_max": tenant.rate_limit_per_minute,
                "concurrent_max": tenant.max_concurrent_workflows,
            }


# ============================================================================
# 11-02: Budget Optimizer
# ============================================================================

class ModelTier(Enum):
    MINI = "mini"      # Cheapest, fastest
    BALANCED = "balanced"
    OPUS = "opus"      # Most capable, most expensive

    @property
    def cost_per_1k_tokens(self) -> float:
        costs = {
            "mini": 0.00015,
            "balanced": 0.003,
            "opus": 0.015,
        }
        return costs[self.value]


@dataclass
class CostEstimate:
    estimated_tokens: int
    estimated_cost: float
    recommended_tier: ModelTier
    alternative_tiers: list[tuple[ModelTier, float]]


@dataclass
class UsageRecord:
    timestamp: str
    tenant_id: str
    agent_id: str
    model_tier: str
    tokens_used: int
    cost: float
    task_type: str
    success: bool


class BudgetOptimizer:
    """Optimizes model selection based on task complexity and budget."""

    TASK_COMPLEXITY_TIER: dict[str, ModelTier] = {
        "simple_crud": ModelTier.MINI,
        "code_review": ModelTier.MINI,
        "documentation": ModelTier.MINI,
        "code_generation": ModelTier.BALANCED,
        "refactoring": ModelTier.BALANCED,
        "test_generation": ModelTier.BALANCED,
        "architecture_design": ModelTier.OPUS,
        "security_audit": ModelTier.OPUS,
        "debugging_complex": ModelTier.OPUS,
    }

    def __init__(self) -> None:
        self._usage_history: list[UsageRecord] = []
        self._budgets: dict[str, float] = {}  # tenant_id -> remaining budget

    def set_budget(self, tenant_id: str, amount: float) -> None:
        self._budgets[tenant_id] = amount

    def get_budget(self, tenant_id: str) -> float:
        return self._budgets.get(tenant_id, 0.0)

    def select_tier(self, task_type: str, tenant_id: str = "",
                    priority: str = "balanced") -> tuple[ModelTier, float]:
        """Select the best model tier for a task.

        Args:
            task_type: Type of task.
            tenant_id: Tenant for budget consideration.
            priority: balanced, cost_saving, or quality.

        Returns:
            (ModelTier, estimated_cost) tuple.
        """
        default_tier = self.TASK_COMPLEXITY_TIER.get(task_type, ModelTier.BALANCED)

        if priority == "cost_saving":
            default_tier = ModelTier.MINI
        elif priority == "quality":
            default_tier = ModelTier.OPUS

        # Check budget
        if tenant_id and tenant_id in self._budgets:
            remaining = self._budgets[tenant_id]
            if remaining <= 0:
                return ModelTier.MINI, 0.0

        # Estimate cost
        token_estimate = self._estimate_tokens(task_type, default_tier)
        cost = (token_estimate / 1000) * default_tier.cost_per_1k_tokens

        return default_tier, cost

    def estimate_cost(self, task_type: str, tier: ModelTier | None = None) -> CostEstimate:
        """Estimate cost for a task with alternatives."""
        if tier is None:
            tier = self.TASK_COMPLEXITY_TIER.get(task_type, ModelTier.BALANCED)

        tokens = self._estimate_tokens(task_type, tier)
        cost = (tokens / 1000) * tier.cost_per_1k_tokens

        alternatives: list[tuple[ModelTier, float]] = []
        for alt_tier in ModelTier:
            if alt_tier != tier:
                alt_tokens = self._estimate_tokens(task_type, alt_tier)
                alt_cost = (alt_tokens / 1000) * alt_tier.cost_per_1k_tokens
                alternatives.append((alt_tier, alt_cost))

        return CostEstimate(
            estimated_tokens=tokens,
            estimated_cost=cost,
            recommended_tier=tier,
            alternative_tiers=alternatives,
        )

    def record_usage(self, tenant_id: str, agent_id: str, model_tier: str,
                     tokens_used: int, task_type: str, success: bool) -> None:
        """Record actual usage for budget tracking and predictions."""
        tier = ModelTier(model_tier)
        cost = (tokens_used / 1000) * tier.cost_per_1k_tokens

        record = UsageRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            model_tier=model_tier,
            tokens_used=tokens_used,
            cost=cost,
            task_type=task_type,
            success=success,
        )
        self._usage_history.append(record)

        # Deduct from budget
        if tenant_id in self._budgets:
            self._budgets[tenant_id] = max(0, self._budgets[tenant_id] - cost)

    def predict_monthly_cost(self, tenant_id: str) -> float:
        """Predict monthly cost based on usage history."""
        tenant_usage = [r for r in self._usage_history if r.tenant_id == tenant_id]
        if not tenant_usage:
            return 0.0

        # Average daily cost * 30
        daily_costs: dict[str, float] = {}
        for r in tenant_usage:
            day = r.timestamp[:10]
            daily_costs[day] = daily_costs.get(day, 0) + r.cost

        avg_daily = sum(daily_costs.values()) / max(len(daily_costs), 1)
        return avg_daily * 30

    def get_usage_report(self, tenant_id: str) -> dict[str, Any]:
        """Generate usage report for a tenant."""
        tenant_usage = [r for r in self._usage_history if r.tenant_id == tenant_id]
        total_cost = sum(r.cost for r in tenant_usage)
        total_tokens = sum(r.tokens_used for r in tenant_usage)

        tier_usage: dict[str, float] = {}
        for r in tenant_usage:
            tier_usage[r.model_tier] = tier_usage.get(r.model_tier, 0) + r.cost

        success_rate = sum(1 for r in tenant_usage if r.success) / max(len(tenant_usage), 1)

        return {
            "tenant_id": tenant_id,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "tier_breakdown": tier_usage,
            "success_rate": success_rate,
            "predicted_monthly": self.predict_monthly_cost(tenant_id),
            "budget_remaining": self._budgets.get(tenant_id, 0),
        }

    def _estimate_tokens(self, task_type: str, tier: ModelTier) -> int:
        """Estimate token usage for a task."""
        base = {
            "simple_crud": 500,
            "code_review": 800,
            "documentation": 600,
            "code_generation": 2000,
            "refactoring": 1500,
            "test_generation": 1000,
            "architecture_design": 3000,
            "security_audit": 2500,
            "debugging_complex": 2000,
        }
        estimate = base.get(task_type, 1500)

        # Higher tiers tend to use more tokens (verbose)
        if tier == ModelTier.OPUS:
            estimate = int(estimate * 1.3)
        elif tier == ModelTier.MINI:
            estimate = int(estimate * 0.8)

        return estimate


# ============================================================================
# 11-03: GPU Scaling & Intelligent Cache
# ============================================================================

@dataclass
class CacheEntry:
    key: str
    result: Any
    timestamp: str
    ttl_seconds: int = 3600
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        ts = datetime.fromisoformat(self.timestamp)
        return (datetime.now(timezone.utc) - ts).total_seconds() > self.ttl_seconds


class IntelligentCache:
    """LRU cache with TTL and hit-count-based retention."""

    def __init__(self, max_size: int = 1000) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._cache[key]
                return None
            entry.hit_count += 1
            return entry.result

    def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        with self._lock:
            if len(self._cache) >= self._max_size:
                self._evict()
            self._cache[key] = CacheEntry(
                key=key,
                result=value,
                timestamp=datetime.now(timezone.utc).isoformat(),
                ttl_seconds=ttl_seconds,
            )

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear_expired(self) -> int:
        removed = 0
        with self._lock:
            expired = [k for k, v in self._cache.items() if v.is_expired]
            for k in expired:
                del self._cache[k]
                removed += 1
        return removed

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "total_hits": sum(e.hit_count for e in self._cache.values()),
            }

    def _evict(self) -> None:
        """Evict the least useful entry (lowest hit_count, oldest if tie)."""
        if not self._cache:
            return
        worst = min(self._cache.items(),
                   key=lambda item: (item[1].hit_count, item[1].timestamp))
        del self._cache[worst[0]]


class GPUScheduler:
    """Manages GPU resource allocation with priority queues."""

    def __init__(self, total_gpus: int = 4) -> None:
        self._total = total_gpus
        self._allocated: dict[str, int] = {}  # agent_id -> gpu_count
        self._queue: list[tuple[int, str, int]] = []  # (priority, agent_id, requested)
        self._lock = threading.Lock()

    @property
    def available(self) -> int:
        return self._total - sum(self._allocated.values())

    def request(self, agent_id: str, gpus: int = 1, priority: int = 5) -> bool:
        """Request GPU allocation. Returns True if allocated immediately."""
        with self._lock:
            if gpus <= self.available:
                self._allocated[agent_id] = self._allocated.get(agent_id, 0) + gpus
                logger.debug("GPU allocated: %s x%d", agent_id, gpus)
                return True

            # Queue the request
            self._queue.append((priority, agent_id, gpus))
            self._queue.sort(key=lambda x: x[0], reverse=True)
            logger.debug("GPU queued: %s x%d (priority %d)", agent_id, gpus, priority)
            return False

    def release(self, agent_id: str, gpus: int = 1) -> None:
        """Release GPU allocation."""
        with self._lock:
            current = self._allocated.get(agent_id, 0)
            self._allocated[agent_id] = max(0, current - gpus)
            if self._allocated[agent_id] == 0:
                del self._allocated[agent_id]
            logger.debug("GPU released: %s x%d", agent_id, gpus)

        # Process queue
        self._process_queue()

    def _process_queue(self) -> None:
        with self._lock:
            remaining = []
            for priority, agent_id, gpus in self._queue:
                if gpus <= self.available:
                    self._allocated[agent_id] = self._allocated.get(agent_id, 0) + gpus
                    logger.debug("GPU dequeued: %s x%d", agent_id, gpus)
                else:
                    remaining.append((priority, agent_id, gpus))
            self._queue = remaining

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total": self._total,
                "available": self.available,
                "allocated": dict(self._allocated),
                "queue_length": len(self._queue),
            }


# ============================================================================
# 11-04: Neural Operations Center 3D
# ============================================================================

@dataclass
class NOCNode:
    """A node in the 3D NOC visualization (represents an agent)."""

    node_id: str
    label: str
    role: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    color: str = "#4A90D9"
    size: float = 1.0
    active: bool = False
    task_count: int = 0
    success_rate: float = 1.0
    reputation: str = "novice"


@dataclass
class NOCEdge:
    """An edge in the 3D NOC (represents communication between agents)."""

    source_id: str
    target_id: str
    message_count: int = 0
    last_message: str = ""
    color: str = "#2ECC71"
    width: float = 1.0


class NeuralOperationsCenter:
    """3D visualization state for the agent network.

    Maintains the data model for a 3D force-directed graph
    showing agents as nodes and communications as edges.
    Updates in real-time via EventBus subscriptions.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, NOCNode] = {}
        self._edges: dict[str, NOCEdge] = {}
        self._lock = threading.Lock()
        self._update_count = 0

    def register_agent(self, agent_id: str, label: str, role: str) -> NOCNode:
        with self._lock:
            import random
            node = NOCNode(
                node_id=agent_id,
                label=label,
                role=role,
                x=random.uniform(-10, 10),
                y=random.uniform(-10, 10),
                z=random.uniform(-5, 5),
                color=self._color_for_role(role),
            )
            self._nodes[agent_id] = node
            self._update_count += 1
            return node

    def update_agent_state(self, agent_id: str, active: bool = False,
                           task_count: int | None = None,
                           success_rate: float | None = None,
                           reputation: str | None = None) -> None:
        with self._lock:
            node = self._nodes.get(agent_id)
            if node:
                node.active = active
                if task_count is not None:
                    node.task_count = task_count
                    node.size = 0.5 + min(task_count / 10, 2.0)
                if success_rate is not None:
                    node.success_rate = success_rate
                if reputation is not None:
                    node.reputation = reputation
                self._update_count += 1

    def record_communication(self, source: str, target: str) -> None:
        with self._lock:
            edge_key = f"{source}->{target}"
            if edge_key not in self._edges:
                self._edges[edge_key] = NOCEdge(
                    source_id=source,
                    target_id=target,
                )
            edge = self._edges[edge_key]
            edge.message_count += 1
            edge.last_message = datetime.now(timezone.utc).isoformat()
            edge.width = min(1 + edge.message_count * 0.1, 5.0)
            self._update_count += 1

    def get_scene_data(self) -> dict[str, Any]:
        """Get complete scene data for 3D rendering."""
        with self._lock:
            return {
                "nodes": [self._node_to_dict(n) for n in self._nodes.values()],
                "edges": [self._edge_to_dict(e) for e in self._edges.values()],
                "update_count": self._update_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_agents": len(self._nodes),
                "active_agents": sum(1 for n in self._nodes.values() if n.active),
                "total_edges": len(self._edges),
                "total_messages": sum(e.message_count for e in self._edges.values()),
                "update_count": self._update_count,
            }

    def _color_for_role(self, role: str) -> str:
        colors = {
            "backend": "#4A90D9",
            "frontend": "#E67E22",
            "security": "#E74C3C",
            "qa": "#2ECC71",
            "data": "#9B59B6",
            "infra": "#1ABC9C",
            "ai": "#F1C40F",
            "product": "#3498DB",
        }
        return colors.get(role, "#95A5A6")

    def _node_to_dict(self, node: NOCNode) -> dict[str, Any]:
        return {
            "id": node.node_id,
            "label": node.label,
            "role": node.role,
            "position": {"x": node.x, "y": node.y, "z": node.z},
            "color": node.color,
            "size": node.size,
            "active": node.active,
            "taskCount": node.task_count,
            "successRate": node.success_rate,
            "reputation": node.reputation,
        }

    def _edge_to_dict(self, edge: NOCEdge) -> dict[str, Any]:
        return {
            "source": edge.source_id,
            "target": edge.target_id,
            "messageCount": edge.message_count,
            "color": edge.color,
            "width": edge.width,
        }