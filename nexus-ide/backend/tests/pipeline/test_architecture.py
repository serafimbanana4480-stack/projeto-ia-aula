"""Tests for architecture templates and pattern catalog."""
import pytest

from backend.pipeline.architecture import (
    ArchitectureTemplate,
    DecisionRecorder,
    DesignPattern,
    LayerRule,
    PatternCatalog,
    TemplateRegistry,
)


class TestTemplateRegistry:
    def test_get_fastapi_layered(self) -> None:
        tmpl = TemplateRegistry.get("fastapi-layered")
        assert tmpl.name == "fastapi-layered"
        assert "routes" in tmpl.layers
        assert "services" in tmpl.layers

    def test_get_react_layered(self) -> None:
        tmpl = TemplateRegistry.get("react-layered")
        assert "pages" in tmpl.layers
        assert "components" in tmpl.layers

    def test_get_unknown(self) -> None:
        with pytest.raises(KeyError):
            TemplateRegistry.get("unknown")


class TestArchitectureTemplate:
    def test_validate_upward_dependency(self) -> None:
        tmpl = TemplateRegistry.get("fastapi-layered")
        assert tmpl.validate_dependency("services", "repositories")
        assert tmpl.validate_dependency("routes", "services")

    def test_validate_skip_layer_not_allowed(self) -> None:
        tmpl = TemplateRegistry.get("fastapi-layered")
        assert not tmpl.validate_dependency("routes", "repositories")

    def test_validate_downward_not_allowed(self) -> None:
        tmpl = TemplateRegistry.get("fastapi-layered")
        assert not tmpl.validate_dependency("repositories", "routes")

    def test_get_layer_for_file(self) -> None:
        tmpl = TemplateRegistry.get("fastapi-layered")
        assert tmpl.get_layer_for_file("app/routes/user.py") == "routes"
        assert tmpl.get_layer_for_file("app/services/auth.py") == "services"
        assert tmpl.get_layer_for_file("app/main.py") == "unknown"


class TestPatternCatalog:
    def test_search_repository(self) -> None:
        results = PatternCatalog.search("repository")
        assert len(results) >= 1
        assert results[0].name == "Repository"

    def test_search_by_category(self) -> None:
        results = PatternCatalog.search("creational")
        names = {r.name for r in results}
        assert "Factory" in names
        assert "Singleton" in names

    def test_get_by_name(self) -> None:
        pattern = PatternCatalog.get("Observer")
        assert pattern is not None
        assert pattern.name == "Observer"

    def test_get_unknown(self) -> None:
        assert PatternCatalog.get("Unknown") is None


class TestDecisionRecorder:
    def test_record_and_list(self) -> None:
        recorder = DecisionRecorder()
        adr = recorder.record(
            context="Need data access abstraction",
            decision="Use Repository pattern",
            consequences="Testable, extra layer",
            related_files=["app/repositories/user.py"],
        )
        assert adr.decision_id == "ADR-001"
        assert adr.status == "accepted"
        assert len(recorder.list_decisions()) == 1

    def test_export_adrs(self) -> None:
        recorder = DecisionRecorder()
        recorder.record("Context", "Decision A", "Good")
        recorder.record("Context 2", "Decision B", "Also good")
        exported = recorder.export_adrs()
        assert "ADR-001" in exported
        assert "ADR-002" in exported
        assert "Decision A" in exported
