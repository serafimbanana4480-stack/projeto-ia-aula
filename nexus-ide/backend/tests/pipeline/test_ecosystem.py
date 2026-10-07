"""Tests for Ecosystem — marketplace, voice, digital twin, auto-evolution, webhooks."""
from __future__ import annotations

from backend.pipeline.ecosystem import (
    AgentMarketplace,
    AgentPlugin,
    AgentStatus,
    AutoEvolution,
    DigitalTwin,
    VoiceAssistant,
    WebhookManager,
)

# ============================================================================
# 12-01: Marketplace Tests
# ============================================================================

class TestAgentMarketplace:
    """Tests for AgentMarketplace."""

    def test_submit_and_validate(self):
        market = AgentMarketplace()
        plugin = AgentPlugin(
            plugin_id="p1", name="Test Plugin", description="A test",
            version="1.0.0", author="dev", capabilities=["code_gen"],
        )
        result = market.submit(plugin)
        assert result.status == AgentStatus.VALIDATED

    def test_submit_incomplete(self):
        market = AgentMarketplace()
        plugin = AgentPlugin(
            plugin_id="p1", name="", description="",
            version="1.0.0", author="dev", capabilities=[],
        )
        result = market.submit(plugin)
        assert result.status == AgentStatus.REJECTED

    def test_search_by_query(self):
        market = AgentMarketplace()
        market.submit(AgentPlugin(
            "p1", "FastAPI Generator", "Generates FastAPI code",
            "1.0", "dev", ["code_gen"], tags=["python", "api"],
        ))
        market.submit(AgentPlugin(
            "p2", "React Builder", "Builds React components",
            "1.0", "dev", ["code_gen"], tags=["typescript", "ui"],
        ))

        results = market.search(query="fastapi")
        assert len(results) == 1
        assert results[0].name == "FastAPI Generator"

    def test_search_by_tags(self):
        market = AgentMarketplace()
        market.submit(AgentPlugin(
            "p1", "P1", "desc", "1.0", "dev", ["code_gen"], tags=["python"],
        ))
        market.submit(AgentPlugin(
            "p2", "P2", "desc", "1.0", "dev", ["code_gen"], tags=["typescript"],
        ))

        results = market.search(tags=["python"])
        assert len(results) == 1

    def test_search_by_capability(self):
        market = AgentMarketplace()
        market.submit(AgentPlugin(
            "p1", "P1", "desc", "1.0", "dev", ["code_gen"],
        ))
        market.submit(AgentPlugin(
            "p2", "P2", "desc", "1.0", "dev", ["test_gen"],
        ))

        results = market.search(capability="test_gen")
        assert len(results) == 1

    def test_install_increments_downloads(self):
        market = AgentMarketplace()
        market.submit(AgentPlugin(
            "p1", "P1", "desc", "1.0", "dev", ["code_gen"],
        ))
        market.install("p1")
        plugin = market.get_plugin("p1")
        assert plugin.downloads == 1

    def test_rate(self):
        market = AgentMarketplace()
        market.submit(AgentPlugin(
            "p1", "P1", "desc", "1.0", "dev", ["code_gen"],
        ))
        assert market.rate("p1", 5)
        plugin = market.get_plugin("p1")
        assert plugin.rating == 5

    def test_rate_invalid(self):
        market = AgentMarketplace()
        market.submit(AgentPlugin(
            "p1", "P1", "desc", "1.0", "dev", ["code_gen"],
        ))
        assert not market.rate("p1", 0)
        assert not market.rate("p1", 6)

    def test_stats(self):
        market = AgentMarketplace()
        market.submit(AgentPlugin("p1", "P1", "desc", "1.0", "dev", ["code_gen"]))
        market.submit(AgentPlugin("p2", "", "", "1.0", "dev", []))
        stats = market.stats()
        assert stats["total"] == 2
        assert stats["validated"] == 1


# ============================================================================
# 12-02: Voice & Digital Twin Tests
# ============================================================================

class TestVoiceAssistant:
    """Tests for VoiceAssistant."""

    def test_status_query(self):
        va = VoiceAssistant()
        response = va.query("What is the system status?")
        assert "operational" in response.lower()

    def test_agent_query(self):
        va = VoiceAssistant()
        response = va.query("Tell me about agents")
        assert "CODER" in response

    def test_error_query(self):
        va = VoiceAssistant()
        response = va.query("Are there any errors?")
        assert "healthy" in response.lower()

    def test_help_query(self):
        va = VoiceAssistant()
        response = va.query("help")
        assert "status" in response.lower()

    def test_unknown_query(self):
        va = VoiceAssistant()
        response = va.query("what is the meaning of life")
        assert "not sure" in response.lower()

    def test_conversation_history(self):
        va = VoiceAssistant()
        va.query("status")
        va.query("agents")
        history = va.get_history()
        assert len(history) == 4  # 2 user + 2 assistant

    def test_clear_history(self):
        va = VoiceAssistant()
        va.query("status")
        va.clear_history()
        assert len(va.get_history()) == 0


class TestDigitalTwin:
    """Tests for DigitalTwin."""

    def test_create_and_simulate(self):
        dt = DigitalTwin()
        scenario = dt.create_scenario(
            "Deploy Test",
            "Simulate a deployment",
            [
                {"type": "code_generation", "agent_id": "CODER"},
                {"type": "test_execution", "agent_id": "DEBUGGER"},
            ],
        )
        result = dt.simulate(scenario.scenario_id)
        assert result is not None
        assert result.passed

    def test_simulate_blocked_action(self):
        dt = DigitalTwin()
        scenario = dt.create_scenario(
            "Dangerous Action",
            "Simulate a dangerous action",
            [{"type": "rm_file", "agent_id": "agent-x"}],
        )
        result = dt.simulate(scenario.scenario_id)
        assert result is not None
        assert not result.passed

    def test_simulate_nonexistent(self):
        dt = DigitalTwin()
        assert dt.simulate("nonexistent") is None

    def test_list_scenarios(self):
        dt = DigitalTwin()
        dt.create_scenario("S1", "desc", [])
        dt.create_scenario("S2", "desc", [])
        assert len(dt.list_scenarios()) == 2

    def test_compare_scenarios(self):
        dt = DigitalTwin()
        s1 = dt.create_scenario("Fast", "fast", [{"type": "code_gen", "agent_id": "a1"}])
        s2 = dt.create_scenario("Slow", "slow", [
            {"type": "code_gen", "agent_id": "a1"},
            {"type": "test_gen", "agent_id": "a2"},
        ])
        dt.simulate(s1.scenario_id)
        dt.simulate(s2.scenario_id)

        comparison = dt.compare_scenarios(s1.scenario_id, s2.scenario_id)
        assert "duration_diff_ms" in comparison


# ============================================================================
# 12-03: Auto-Evolution & Webhooks Tests
# ============================================================================

class TestAutoEvolution:
    """Tests for AutoEvolution."""

    def test_propose(self):
        evo = AutoEvolution()
        proposal = evo.propose(
            "backend/pipeline/generator.py",
            "Optimize template cache",
            "Add LRU cache to template registry",
            "Reduces template lookup time by 50%",
        )
        assert proposal is not None
        assert proposal.status == "pending"

    def test_approve_and_apply(self):
        evo = AutoEvolution()
        proposal = evo.propose("file.py", "Fix bug", "patch", "reason")
        evo.approve(proposal.proposal_id, "admin")
        evo.apply(proposal.proposal_id)

        history = evo.get_history()
        assert history[0].status == "applied"

    def test_reject(self):
        evo = AutoEvolution()
        proposal = evo.propose("file.py", "Fix", "patch", "reason")
        evo.reject(proposal.proposal_id, "admin")
        assert evo.get_history()[0].status == "rejected"

    def test_rollback(self):
        evo = AutoEvolution()
        proposal = evo.propose("file.py", "Fix", "patch", "reason")
        evo.approve(proposal.proposal_id, "admin")
        evo.apply(proposal.proposal_id)
        evo.rollback(proposal.proposal_id)
        assert evo.get_history()[0].status == "rolled_back"

    def test_get_pending(self):
        evo = AutoEvolution()
        evo.propose("f1.py", "Fix 1", "patch", "reason")
        evo.propose("f2.py", "Fix 2", "patch", "reason")
        pending = evo.get_pending()
        assert len(pending) == 2

    def test_stats(self):
        evo = AutoEvolution()
        evo.propose("f1.py", "Fix", "patch", "reason")
        stats = evo.stats()
        assert stats["total_proposals"] == 1
        assert stats["pending"] == 1

    def test_daily_limit(self):
        evo = AutoEvolution()
        for i in range(6):
            result = evo.propose(f"file{i}.py", f"Fix {i}", "patch", "reason")
        # 6th should be None (limit is 5)
        assert result is None


class TestWebhookManager:
    """Tests for WebhookManager."""

    def test_register_and_dispatch(self):
        mgr = WebhookManager()
        hook = mgr.register("https://example.com/hook", ["workflow.completed", "deploy.started"])
        delivered = mgr.dispatch("workflow.completed", {"workflow_id": "wf-001"})
        assert len(delivered) == 1
        assert delivered[0] == hook.hook_id

    def test_dispatch_no_match(self):
        mgr = WebhookManager()
        mgr.register("https://example.com/hook", ["deploy.started"])
        delivered = mgr.dispatch("workflow.completed", {})
        assert len(delivered) == 0

    def test_dispatch_inactive_hook(self):
        mgr = WebhookManager()
        hook = mgr.register("https://example.com/hook", ["workflow.completed"])
        hook.active = False
        delivered = mgr.dispatch("workflow.completed", {})
        assert len(delivered) == 0

    def test_unregister(self):
        mgr = WebhookManager()
        hook = mgr.register("https://example.com/hook", ["workflow.completed"])
        assert mgr.unregister(hook.hook_id)
        assert not mgr.unregister("nonexistent")

    def test_get_hooks_for_event(self):
        mgr = WebhookManager()
        mgr.register("https://a.com", ["workflow.completed"])
        mgr.register("https://b.com", ["deploy.started"])
        hooks = mgr.get_hooks_for_event("workflow.completed")
        assert len(hooks) == 1

    def test_delivery_log(self):
        mgr = WebhookManager()
        mgr.register("https://example.com/hook", ["workflow.completed"])
        mgr.dispatch("workflow.completed", {"id": "wf-001"})
        log = mgr.get_delivery_log()
        assert len(log) == 1
        assert log[0]["event"] == "workflow.completed"

    def test_list_hooks(self):
        mgr = WebhookManager()
        mgr.register("https://a.com", ["e1"])
        mgr.register("https://b.com", ["e2"])
        assert len(mgr.list_hooks()) == 2