"""Tests for documentation generators."""
from backend.pipeline.architecture import ArchitecturalDecision, DecisionRecorder
from backend.pipeline.documentation import CommentGenerator, ReadmeGenerator


class TestCommentGenerator:
    def test_pattern_comment(self) -> None:
        gen = CommentGenerator()
        comment = gen.generate_pattern_comment("Repository")
        assert "Repository pattern" in comment
        assert "Why:" in comment

    def test_architecture_comment(self) -> None:
        gen = CommentGenerator()
        comment = gen.generate_architecture_comment("fastapi-layered")
        assert "fastapi-layered" in comment
        assert "layered architecture" in comment

    def test_security_comment(self) -> None:
        gen = CommentGenerator()
        comment = gen.generate_security_comment("sql_injection")
        assert "parameterized queries" in comment


class TestReadmeGenerator:
    def test_generate(self) -> None:
        gen = ReadmeGenerator()
        recorder = DecisionRecorder()
        adr = recorder.record("Need API", "Use FastAPI", "Fast and modern")

        readme = gen.generate(
            project_name="MyAPI",
            stack="Python/FastAPI",
            architecture="Layered (routes → services → repositories)",
            setup_commands="pip install -r requirements.txt\nuvicorn app.main:app",
            test_commands="pytest tests/",
            file_tree="app/\n  routes/\n  services/\n  repositories/",
            decisions=[adr],
        )

        assert "MyAPI" in readme
        assert "FastAPI" in readme
        assert "ADR-001" in readme
        assert "app/" in readme
