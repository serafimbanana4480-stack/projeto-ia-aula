"""Tests for Scalability — multi-tenancy, budget, GPU, NOC."""
from __future__ import annotations

import time

import pytest

from backend.pipeline.scalability import (
    BudgetOptimizer,
    GPUScheduler,
    IntelligentCache,
    ModelTier,
    NeuralOperationsCenter,
    TenantConfig,
    TenantIsolationLevel,
    TenantManager,
)


# ============================================================================
# 11-01: Multi-tenancy Tests
# ============================================================================

class TestTenantManager:
    """Tests for TenantManager."""

    def test_register_and_get(self):
        mgr = TenantManager()
        config = TenantConfig(tenant_id="t1", name="Tenant 1")
        mgr.register(config)
        retrieved = mgr.get("t1")
        assert retrieved is not None
        assert retrieved.name == "Tenant 1"

    def test_get_nonexistent(self):
        mgr = TenantManager()
        assert mgr.get("nonexistent") is None

    def test_rate_limit_allows(self):
        mgr = TenantManager()
        mgr.register(TenantConfig(tenant_id="t1", name="T1", rate_limit_per_minute=100))
        assert mgr.check_rate_limit("t1")

    def test_rate_limit_blocks_inactive(self):
        mgr = TenantManager()
        mgr.register(TenantConfig(tenant_id="t1", name="T1", active=False))
        assert not mgr.check_rate_limit("t1")

    def test_can_start_workflow(self):
        mgr = TenantManager()
        mgr.register(TenantConfig(tenant_id="t1", name="T1", max_concurrent_workflows=2))
        assert mgr.can_start_workflow("t1")
        mgr.workflow_started("t1")
        mgr.workflow_started("t1")
        assert not mgr.can_start_workflow("t1")

    def test_workflow_completed(self):
        mgr = TenantManager()
        mgr.register(TenantConfig(tenant_id="t1", name="T1", max_concurrent_workflows=2))
        mgr.workflow_started("t1")
        mgr.workflow_started("t1")
        mgr.workflow_completed("t1")
        assert mgr.can_start_workflow("t1")

    def test_namespace_key(self):
        mgr = TenantManager()
        assert mgr.namespace_key("t1", "mykey") == "tenant:t1:mykey"

    def test_list_tenants(self):
        mgr = TenantManager()
        mgr.register(TenantConfig(tenant_id="t1", name="T1"))
        mgr.register(TenantConfig(tenant_id="t2", name="T2"))
        assert len(mgr.list_tenants()) == 2

    def test_usage_stats(self):
        mgr = TenantManager()
        mgr.register(TenantConfig(tenant_id="t1", name="T1"))
        mgr.workflow_started("t1")
        stats = mgr.get_usage_stats("t1")
        assert stats["active_workflows"] == 1
        assert stats["rate_limit_max"] == 100


# ============================================================================
# 11-02: Budget Optimizer Tests
# ============================================================================

class TestBudgetOptimizer:
    """Tests for BudgetOptimizer."""

    def test_select_tier_default(self):
        opt = BudgetOptimizer()
        tier, cost = opt.select_tier("code_generation")
        assert tier == ModelTier.BALANCED
        assert cost > 0

    def test_select_tier_cost_saving(self):
        opt = BudgetOptimizer()
        tier, cost = opt.select_tier("code_generation", priority="cost_saving")
        assert tier == ModelTier.MINI

    def test_select_tier_quality(self):
        opt = BudgetOptimizer()
        tier, cost = opt.select_tier("code_generation", priority="quality")
        assert tier == ModelTier.OPUS

    def test_select_tier_budget_exhausted(self):
        opt = BudgetOptimizer()
        opt.set_budget("t1", 0)
        tier, cost = opt.select_tier("code_generation", tenant_id="t1")
        assert tier == ModelTier.MINI

    def test_estimate_cost(self):
        opt = BudgetOptimizer()
        estimate = opt.estimate_cost("architecture_design")
        assert estimate.recommended_tier == ModelTier.OPUS
        assert estimate.estimated_cost > 0
        assert len(estimate.alternative_tiers) == 2

    def test_record_usage(self):
        opt = BudgetOptimizer()
        opt.set_budget("t1", 10.0)
        opt.record_usage("t1", "agent-1", "balanced", 5000, "code_generation", True)
        report = opt.get_usage_report("t1")
        assert report["total_cost"] > 0
        assert report["total_tokens"] == 5000

    def test_predict_monthly_cost(self):
        opt = BudgetOptimizer()
        opt.record_usage("t1", "a1", "balanced", 1000, "code_generation", True)
        predicted = opt.predict_monthly_cost("t1")
        assert predicted >= 0

    def test_get_usage_report_empty(self):
        opt = BudgetOptimizer()
        report = opt.get_usage_report("unknown")
        assert report["total_cost"] == 0

    def test_budget_deduction(self):
        opt = BudgetOptimizer()
        opt.set_budget("t1", 1.0)
        opt.record_usage("t1", "a1", "opus", 10000, "architecture_design", True)
        remaining = opt.get_budget("t1")
        assert remaining < 1.0

    def test_model_tier_costs(self):
        assert ModelTier.MINI.cost_per_1k_tokens < ModelTier.BALANCED.cost_per_1k_tokens
        assert ModelTier.BALANCED.cost_per_1k_tokens < ModelTier.OPUS.cost_per_1k_tokens


# ============================================================================
# 11-03: Cache and GPU Tests
# ============================================================================

class TestIntelligentCache:
    """Tests for IntelligentCache."""

    def test_set_and_get(self):
        cache = IntelligentCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing(self):
        cache = IntelligentCache()
        assert cache.get("missing") is None

    def test_ttl_expiry(self):
        cache = IntelligentCache()
        cache.set("key1", "value1", ttl_seconds=-1)  # Immediate expiry
        assert cache.get("key1") is None

    def test_invalidate(self):
        cache = IntelligentCache()
        cache.set("key1", "value1")
        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_hit_count(self):
        cache = IntelligentCache()
        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("key1")
        stats = cache.stats()
        assert stats["total_hits"] == 2

    def test_clear_expired(self):
        cache = IntelligentCache()
        cache.set("key1", "v1", ttl_seconds=-1)
        cache.set("key2", "v2", ttl_seconds=3600)
        removed = cache.clear_expired()
        assert removed == 1
        assert cache.get("key2") == "v2"

    def test_eviction_when_full(self):
        cache = IntelligentCache(max_size=3)
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")
        cache.set("k4", "v4")  # Should evict one
        stats = cache.stats()
        assert stats["size"] == 3


class TestGPUScheduler:
    """Tests for GPUScheduler."""

    def test_initial_available(self):
        sched = GPUScheduler(total_gpus=4)
        assert sched.available == 4

    def test_request_and_release(self):
        sched = GPUScheduler(total_gpus=4)
        assert sched.request("agent-1", 2)
        assert sched.available == 2
        sched.release("agent-1", 2)
        assert sched.available == 4

    def test_request_queues_when_full(self):
        sched = GPUScheduler(total_gpus=2)
        assert sched.request("agent-1", 2)
        assert not sched.request("agent-2", 1)  # Queued
        status = sched.get_status()
        assert status["queue_length"] == 1

    def test_queue_processed_on_release(self):
        sched = GPUScheduler(total_gpus=2)
        sched.request("agent-1", 2)
        sched.request("agent-2", 1)  # Queued
        sched.release("agent-1", 2)  # Should process queue
        status = sched.get_status()
        assert status["queue_length"] == 0

    def test_get_status(self):
        sched = GPUScheduler(total_gpus=4)
        sched.request("agent-1", 1)
        status = sched.get_status()
        assert status["total"] == 4
        assert status["available"] == 3


# ============================================================================
# 11-04: NOC 3D Tests
# ============================================================================

class TestNeuralOperationsCenter:
    """Tests for NeuralOperationsCenter."""

    def test_register_agent(self):
        noc = NeuralOperationsCenter()
        node = noc.register_agent("agent-1", "Coder Agent", "backend")
        assert node.node_id == "agent-1"
        assert node.role == "backend"
        assert node.color != ""

    def test_update_agent_state(self):
        noc = NeuralOperationsCenter()
        noc.register_agent("agent-1", "Agent 1", "backend")
        noc.update_agent_state("agent-1", active=True, task_count=5,
                               success_rate=0.95, reputation="expert")
        scene = noc.get_scene_data()
        node = next(n for n in scene["nodes"] if n["id"] == "agent-1")
        assert node["active"]
        assert node["taskCount"] == 5
        assert node["successRate"] == 0.95

    def test_record_communication(self):
        noc = NeuralOperationsCenter()
        noc.register_agent("a1", "A1", "backend")
        noc.register_agent("a2", "A2", "frontend")
        noc.record_communication("a1", "a2")
        scene = noc.get_scene_data()
        assert len(scene["edges"]) == 1
        assert scene["edges"][0]["source"] == "a1"
        assert scene["edges"][0]["target"] == "a2"

    def test_get_stats(self):
        noc = NeuralOperationsCenter()
        noc.register_agent("a1", "A1", "backend")
        noc.register_agent("a2", "A2", "qa")
        noc.update_agent_state("a1", active=True)
        stats = noc.get_stats()
        assert stats["total_agents"] == 2
        assert stats["active_agents"] == 1

    def test_get_scene_data_empty(self):
        noc = NeuralOperationsCenter()
        scene = noc.get_scene_data()
        assert scene["nodes"] == []
        assert scene["edges"] == []

    def test_color_for_role(self):
        noc = NeuralOperationsCenter()
        node = noc.register_agent("a1", "A1", "security")
        assert node.color == "#E74C3C"

    def test_multiple_communications(self):
        noc = NeuralOperationsCenter()
        noc.register_agent("a1", "A1", "backend")
        noc.register_agent("a2", "A2", "qa")
        noc.record_communication("a1", "a2")
        noc.record_communication("a1", "a2")
        scene = noc.get_scene_data()
        assert scene["edges"][0]["messageCount"] == 2