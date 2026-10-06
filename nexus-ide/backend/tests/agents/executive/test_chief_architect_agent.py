"""Tests for Chief Architect Agent and components."""
from __future__ import annotations

from backend.agents.executive.chief_architect_agent import ChiefArchitectAgent
from backend.agents.executive.integration_planner import IntegrationPlanner, IntegrationStatus
from backend.agents.executive.pattern_catalog import PatternCatalog, PatternCategory
from backend.agents.executive.quality_gate import CheckSeverity, QualityGate
from backend.agents.executive.system_designer import SystemDesigner


class TestPatternCatalog:
    def test_default_patterns_loaded(self) -> None:
        catalog = PatternCatalog()
        assert catalog.stats()["total"] > 0

    def test_search(self) -> None:
        catalog = PatternCatalog()
        results = catalog.search("microservices")
        assert len(results) > 0
        assert results[0].name == "Microservices"

    def test_get_by_category(self) -> None:
        catalog = PatternCatalog()
        arch = catalog.get_by_category(PatternCategory.ARCHITECTURAL)
        assert len(arch) > 0
        assert all(p.category == PatternCategory.ARCHITECTURAL for p in arch)

    def test_recommend(self) -> None:
        catalog = PatternCatalog()
        recs = catalog.recommend(["scalability", "distributed"])
        assert len(recs) > 0
        assert recs[0][0] > 0


class TestSystemDesigner:
    def test_create_design(self) -> None:
        sd = SystemDesigner()
        design = sd.create_design(
            name="E-commerce API",
            description="REST API for e-commerce",
            requirements=["api", "database", "cache"],
        )
        assert design.design_id.startswith("design-")
        assert len(design.components) > 0

    def test_add_component(self) -> None:
        sd = SystemDesigner()
        design = sd.create_design("Test", "Test", ["api"])
        from backend.agents.executive.system_designer import SystemComponent
        comp = SystemComponent(
            component_id="c1", name="Test Comp", type="service",
            responsibilities=["test"],
        )
        assert sd.add_component(design.design_id, comp)
        assert len(sd.get_design(design.design_id).components) > 1

    def test_stats(self) -> None:
        sd = SystemDesigner()
        assert sd.stats()["total_designs"] == 0
        sd.create_design("Test", "Test", ["api"])
        assert sd.stats()["total_designs"] == 1


class TestQualityGate:
    def test_check_modularity_pass(self) -> None:
        gate = QualityGate()
        components = [
            {"name": "API", "responsibilities": ["routing", "auth"]},
            {"name": "DB", "responsibilities": ["storage"]},
        ]
        check = gate.check_modularity(components)
        assert check.passed
        assert check.severity == CheckSeverity.INFO

    def test_check_modularity_fail(self) -> None:
        gate = QualityGate()
        components = [
            {"name": "GodService", "responsibilities": ["a", "b", "c", "d", "e", "f"]},
        ]
        check = gate.check_modularity(components)
        assert not check.passed
        assert check.severity == CheckSeverity.CRITICAL

    def test_check_security_no_auth(self) -> None:
        gate = QualityGate()
        components = [{"name": "Service"}]
        check = gate.check_security(components)
        assert not check.passed
        assert check.severity == CheckSeverity.BLOCKER

    def test_run_all_checks(self) -> None:
        gate = QualityGate()
        components = [
            {"name": "API", "responsibilities": ["routing"]},
            {"name": "Auth", "responsibilities": ["login"]},
        ]
        flows = [{"source": "API", "target": "Auth", "protocol": "grpc"}]
        checks = gate.run_all_checks(components, flows)
        assert len(checks) == 4
        assert gate.get_summary()["total"] == 4


class TestIntegrationPlanner:
    def test_create_plan(self) -> None:
        planner = IntegrationPlanner()
        plan = planner.create_plan(
            name="API to DB",
            source_system="api",
            target_system="database",
            integration_type="api",
            protocol="REST",
        )
        assert plan.plan_id.startswith("int-")
        assert plan.status == IntegrationStatus.PLANNED

    def test_add_data_mapping(self) -> None:
        planner = IntegrationPlanner()
        plan = planner.create_plan("Test", "a", "b", "api", "REST")
        assert planner.add_data_mapping(plan.plan_id, "user_id", "id", "int")
        assert len(planner.get_plan(plan.plan_id).data_mapping) == 1

    def test_list_by_status(self) -> None:
        planner = IntegrationPlanner()
        planner.create_plan("Test", "a", "b", "api", "REST")
        assert len(planner.list_plans(IntegrationStatus.PLANNED)) == 1
        assert len(planner.list_plans(IntegrationStatus.COMPLETED)) == 0

    def test_stats(self) -> None:
        planner = IntegrationPlanner()
        planner.create_plan("Test", "a", "b", "api", "REST")
        assert planner.stats()["total"] == 1


class TestChiefArchitectAgent:
    def test_dashboard(self) -> None:
        agent = ChiefArchitectAgent()
        dashboard = agent.get_dashboard()
        assert "patterns" in dashboard
        assert "designs" in dashboard
        assert "integrations" in dashboard
        assert "quality_score" in dashboard

    def test_pattern_catalog_injected(self) -> None:
        catalog = PatternCatalog()
        agent = ChiefArchitectAgent(pattern_catalog=catalog)
        assert agent._catalog is catalog
