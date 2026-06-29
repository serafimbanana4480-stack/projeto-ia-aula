"""Tests for RefactorEngine."""
from backend.pipeline.refactor import RefactorEngine


class TestRefactorEngine:
    def test_add_type_hints(self) -> None:
        source = "def greet(name):\n    return f'Hello {name}'\n"
        engine = RefactorEngine()
        result = engine.refactor(source)
        assert "def greet(name: Any) -> Any:" in result.transformed
        assert any("Added type hints" in c for c in result.changes)

    def test_harden_exceptions(self) -> None:
        source = "try:\n    x = 1\nexcept:\n    pass\n"
        engine = RefactorEngine()
        result = engine.refactor(source)
        assert "except Exception:" in result.transformed
        assert any("bare except" in c.lower() for c in result.changes)

    def test_no_changes_for_clean_code(self) -> None:
        source = "def add(a: int, b: int) -> int:\n    return a + b\n"
        engine = RefactorEngine()
        result = engine.refactor(source)
        # Should not add type hints (already present)
        assert result.transformed == source or "def add(a: int, b: int) -> int:" in result.transformed

    def test_invalid_source(self) -> None:
        source = "def broken("
        engine = RefactorEngine()
        result = engine.refactor(source)
        assert len(result.errors) > 0
        assert "Parse error" in result.errors[0]
