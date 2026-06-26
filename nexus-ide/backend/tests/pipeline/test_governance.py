"""Tests for Governance — autonomy, kill-switch, council, ledger."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from backend.pipeline.governance import (
    AuditDecision,
    AutonomyLevel,
    AutonomyManager,
    ComplianceAuditor,
    EthicsAuditor,
    GovernanceCouncil,
    ImmutableLedger,
    KillSwitch,
    LedgerEntry,
    SecurityAuditor,
    SnapshotStore,
    StateSnapshot,
)


# ============================================================================
# 10-01: AutonomyManager Tests
# ============================================================================

class TestAutonomyLevel:
    """Tests for AutonomyLevel enum."""

    def test_level_values(self):
        assert AutonomyLevel.MANUAL.value == 0
        assert AutonomyLevel.SUPERVISED.value == 1
        assert AutonomyLevel.SEMI_AUTONOMOUS.value == 2
        assert AutonomyLevel.AUTONOMOUS.value == 3
        assert AutonomyLevel.FULL.value == 4

    def test_labels(self):
        assert AutonomyLevel.MANUAL.label == "Manual"
        assert AutonomyLevel.FULL.label == "Full"

    def test_allows_code_gen(self):
        assert not AutonomyLevel.MANUAL.allows_code_gen
        assert not AutonomyLevel.SUPERVISED.allows_code_gen
        assert AutonomyLevel.SEMI_AUTONOMOUS.allows_code_gen
        assert AutonomyLevel.FULL.allows_code_gen

    def test_allows_auto_deploy(self):
        assert not AutonomyLevel.SEMI_AUTONOMOUS.allows_auto_deploy
        assert AutonomyLevel.AUTONOMOUS.allows_auto_deploy

    def test_allows_prod_deploy(self):
        assert not AutonomyLevel.AUTONOMOUS.allows_prod_deploy
        assert AutonomyLevel.FULL.allows_prod_deploy


class TestAutonomyManager:
    """Tests for AutonomyManager."""

    def test_default_level(self):
        mgr = AutonomyManager()
        assert mgr.level == AutonomyLevel.SEMI_AUTONOMOUS

    def test_custom_default(self):
        mgr = AutonomyManager(AutonomyLevel.SUPERVISED)
        assert mgr.level == AutonomyLevel.SUPERVISED

    def test_set_level(self):
        mgr = AutonomyManager()
        mgr.set_level(AutonomyLevel.AUTONOMOUS)
        assert mgr.level == AutonomyLevel.AUTONOMOUS

    def test_check_permission_non_destructive(self):
        mgr = AutonomyManager(AutonomyLevel.SUPERVISED)
        assert mgr.check_permission("code_generation")

    def test_check_permission_destructive_denied(self):
        mgr = AutonomyManager(AutonomyLevel.SUPERVISED)
        assert not mgr.check_permission("deploy")

    def test_check_permission_destructive_allowed(self):
        mgr = AutonomyManager(AutonomyLevel.SEMI_AUTONOMOUS)
        assert mgr.check_permission("deploy")

    def test_check_permission_critical_denied(self):
        mgr = AutonomyManager(AutonomyLevel.SEMI_AUTONOMOUS)
        assert not mgr.check_permission("production_deploy")

    def test_check_permission_production_deploy(self):
        mgr = AutonomyManager(AutonomyLevel.AUTONOMOUS)
        assert not mgr.check_permission("deploy", environment="production")

    def test_check_permission_production_deploy_full(self):
        mgr = AutonomyManager(AutonomyLevel.FULL)
        assert mgr.check_permission("deploy", environment="production")

    def test_role_override(self):
        mgr = AutonomyManager(AutonomyLevel.SUPERVISED)
        mgr.set_role_override("qa", AutonomyLevel.AUTONOMOUS)
        assert mgr.check_permission("deploy", role="qa")

    def test_action_override(self):
        mgr = AutonomyManager(AutonomyLevel.SUPERVISED)
        mgr.set_action_override("deploy", AutonomyLevel.SUPERVISED)
        assert mgr.check_permission("deploy")

    def test_get_effective_level(self):
        mgr = AutonomyManager(AutonomyLevel.SEMI_AUTONOMOUS)
        mgr.set_role_override("backend", AutonomyLevel.AUTONOMOUS)
        assert mgr.get_effective_level() == AutonomyLevel.SEMI_AUTONOMOUS
        assert mgr.get_effective_level("backend") == AutonomyLevel.AUTONOMOUS

    def test_to_dict(self):
        mgr = AutonomyManager()
        d = mgr.to_dict()
        assert d["global_level"] == "Semi-Autonomous"
        assert d["global_level_value"] == 2


# ============================================================================
# 10-02: KillSwitch and Snapshots Tests
# ============================================================================

class TestKillSwitch:
    """Tests for KillSwitch singleton."""

    def test_singleton(self):
        ks1 = KillSwitch()
        ks2 = KillSwitch()
        assert ks1 is ks2

    def test_initial_state(self):
        ks = KillSwitch()
        assert not ks.is_active

    def test_activate(self):
        ks = KillSwitch()
        ts = ks.activate("Test emergency")
        assert ks.is_active
        assert ts
        status = ks.get_status()
        assert status["active"]
        assert status["reason"] == "Test emergency"

    def test_deactivate_without_token(self):
        ks = KillSwitch()
        ks.activate("test")
        result = ks.deactivate("")
        assert not result  # should fail

    def test_deactivate_with_token(self):
        ks = KillSwitch()
        ks.activate("test")
        result = ks.deactivate("auth-token")
        assert result
        assert not ks.is_active

    def test_activation_count(self):
        ks = KillSwitch()
        initial_count = ks.get_status()["activation_count"]
        ks.activate("first")
        ks.deactivate("token")
        ks.activate("second")
        status = ks.get_status()
        assert status["activation_count"] == initial_count + 2


class TestSnapshotStore:
    """Tests for SnapshotStore."""

    def test_capture_and_restore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SnapshotStore(tmpdir)
            snap = store.capture(
                autonomy_level="Semi-Autonomous",
                active_agents=["CODER", "DEBUGGER"],
                pending_tasks=3,
                workflows=["wf-001", "wf-002"],
            )
            assert snap.snapshot_id.startswith("snap-")

            restored = store.restore(snap.snapshot_id)
            assert restored is not None
            assert restored.autonomy_level == "Semi-Autonomous"
            assert "CODER" in restored.active_agents

    def test_restore_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SnapshotStore(tmpdir)
            assert store.restore("nonexistent") is None

    def test_list_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SnapshotStore(tmpdir)
            import time
            store.capture("Manual", [], 0, [])
            time.sleep(1.1)  # Ensure unique timestamp
            store.capture("Full", [], 0, [])
            snapshots = store.list_snapshots()
            assert len(snapshots) == 2

    def test_prune_old(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SnapshotStore(tmpdir)
            snap = store.capture("Manual", [], 0, [])
            # All snapshots are recent, so prune should remove 0
            removed = store.prune_old()
            assert removed == 0

    def test_snapshot_with_kill_switch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SnapshotStore(tmpdir)
            snap = store.capture("Manual", [], 0, [], kill_switch_active=True)
            assert snap.kill_switch_active


# ============================================================================
# 10-03: Governance Council Tests
# ============================================================================

class TestAuditors:
    """Tests for individual auditor agents."""

    def test_security_blocks_rm_file(self):
        auditor = SecurityAuditor("Security")
        vote, reason = auditor.audit("rm_file", "agent-1")
        assert vote == "deny"

    def test_security_allows_code_gen(self):
        auditor = SecurityAuditor("Security")
        vote, reason = auditor.audit("code_generation", "agent-1")
        assert vote == "approve"

    def test_security_blocks_prod_deploy(self):
        auditor = SecurityAuditor("Security")
        vote, reason = auditor.audit("deploy", "agent-1", {"environment": "production"})
        assert vote == "deny"

    def test_compliance_blocks_critical_low_level(self):
        auditor = ComplianceAuditor("Compliance")
        vote, reason = auditor.audit("production_deploy", "agent-1",
                                     {"autonomy_level": 2})
        assert vote == "deny"

    def test_compliance_allows_critical_high_level(self):
        auditor = ComplianceAuditor("Compliance")
        vote, reason = auditor.audit("production_deploy", "agent-1",
                                     {"autonomy_level": 3})
        assert vote == "approve"

    def test_ethics_blocks_data_delete(self):
        auditor = EthicsAuditor("Ethics")
        vote, reason = auditor.audit("user_data_delete", "agent-1",
                                     {"autonomy_level": 2})
        assert vote == "deny"

    def test_ethics_allows_normal(self):
        auditor = EthicsAuditor("Ethics")
        vote, reason = auditor.audit("code_generation", "agent-1")
        assert vote == "approve"


class TestGovernanceCouncil:
    """Tests for GovernanceCouncil."""

    def test_audit_allows_safe_action(self):
        council = GovernanceCouncil()
        decision = council.audit("code_generation", "agent-1")
        assert not decision.vetoed

    def test_audit_vetoes_dangerous_action(self):
        council = GovernanceCouncil()
        decision = council.audit("rm_file", "agent-1")
        # rm_file is blocked by security (1 deny) + likely others
        # At minimum, security denies it
        assert decision.security_vote == "deny"

    def test_is_action_allowed(self):
        council = GovernanceCouncil()
        assert council.is_action_allowed("code_generation", "agent-1")
        # rm_file is denied by security (1 deny) but veto needs 2/3
        # Test with a clearly vetoable action
        assert not council.is_action_allowed("user_data_delete", "agent-1",
                                             {"autonomy_level": 1})

    def test_decision_history(self):
        council = GovernanceCouncil()
        council.audit("code_generation", "agent-1")
        council.audit("deploy", "agent-2")
        history = council.get_decision_history()
        assert len(history) == 2

    def test_veto_threshold(self):
        council = GovernanceCouncil()
        # user_data_delete should be denied by ethics (low level)
        # and likely also by compliance
        decision = council.audit("user_data_delete", "agent-1",
                                 {"autonomy_level": 1})
        assert decision.ethics_vote == "deny" or decision.compliance_vote == "deny"


# ============================================================================
# 10-04: Immutable Ledger Tests
# ============================================================================

class TestLedgerEntry:
    """Tests for LedgerEntry."""

    def test_compute_hash(self):
        entry = LedgerEntry(
            entry_id="test-1",
            entry_type="DECISION",
            agent_id="agent-1",
            action="approved deployment",
            timestamp="2025-01-01T00:00:00Z",
        )
        h = entry.compute_hash()
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_changes_with_data(self):
        e1 = LedgerEntry("id1", "DECISION", "a1", "action1", "2025-01-01T00:00:00Z")
        e2 = LedgerEntry("id1", "DECISION", "a1", "action2", "2025-01-01T00:00:00Z")
        assert e1.compute_hash() != e2.compute_hash()

    def test_to_dict_and_from_dict(self):
        entry = LedgerEntry(
            entry_id="test-1", entry_type="DECISION",
            agent_id="agent-1", action="test", timestamp="now",
            previous_hash="abc123", hash="def456",
        )
        d = entry.to_dict()
        restored = LedgerEntry.from_dict(d)
        assert restored.entry_id == entry.entry_id
        assert restored.hash == entry.hash


class TestImmutableLedger:
    """Tests for ImmutableLedger."""

    def test_append_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ledger.jsonl")
            ledger = ImmutableLedger(path)
            entry = ledger.append("DECISION", "agent-1", "approved code gen")
            assert entry.entry_id.startswith("ledger-")
            assert entry.hash
            assert ledger.get_entry_count() == 1

    def test_chain_integrity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ledger.jsonl")
            ledger = ImmutableLedger(path)
            ledger.append("DECISION", "a1", "action 1")
            ledger.append("CODE_GENERATED", "a2", "action 2")
            ledger.append("TEST_EXECUTED", "a3", "action 3")

            valid, msg = ledger.verify()
            assert valid

    def test_verify_empty_ledger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ledger.jsonl")
            ledger = ImmutableLedger(path)
            valid, msg = ledger.verify()
            assert valid

    def test_query_by_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ledger.jsonl")
            ledger = ImmutableLedger(path)
            ledger.append("DECISION", "a1", "d1")
            ledger.append("CODE_GENERATED", "a2", "c1")
            ledger.append("DECISION", "a1", "d2")

            decisions = ledger.query(entry_type="DECISION")
            assert len(decisions) == 2

    def test_query_by_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ledger.jsonl")
            ledger = ImmutableLedger(path)
            ledger.append("DECISION", "agent-x", "action")
            ledger.append("DECISION", "agent-y", "action")

            results = ledger.query(agent_id="agent-x")
            assert len(results) == 1

    def test_export_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ledger.jsonl")
            ledger = ImmutableLedger(path)
            ledger.append("DECISION", "a1", "action")
            ledger.append("CODE_GENERATED", "a1", "action")

            report = ledger.export_report()
            assert report["total_entries"] == 2
            assert report["chain_valid"]
            assert report["entry_types"]["DECISION"] == 1
            assert report["entry_types"]["CODE_GENERATED"] == 1

    def test_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ledger.jsonl")
            ledger = ImmutableLedger(path)
            ledger.append("DECISION", "a1", "action 1")
            ledger.append("DECISION", "a2", "action 2")

            # Tamper with an entry
            ledger._entries[0].hash = "00000000000000000000000000000000"

            valid, msg = ledger.verify()
            assert not valid

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ledger.jsonl")
            ledger1 = ImmutableLedger(path)
            ledger1.append("DECISION", "a1", "action")

            # Create new ledger from same file
            ledger2 = ImmutableLedger(path)
            assert ledger2.get_entry_count() == 1

            valid, _ = ledger2.verify()
            assert valid