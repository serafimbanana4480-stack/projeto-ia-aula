"""Tests for Mission Control.

The properties under test are the ones that make the layer worth having. A
brief that invents facts, a confidence score that ignores whether anything was
verified, or a wave that spawns an agent the project has no use for would each
individually defeat the purpose — so each has a test that fails loudly.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from backend.orchestrator.mission_control import (
    ContractState,
    MissionPhase,
    MissionPlanner,
    MissionReport,
    MissionTracker,
    ProjectIntelligence,
    Severity,
    start_mission,
)

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def py_project(tmp_path: Path) -> Path:
    """A minimal Python project with tests and a TODO."""
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "main.py").write_text(
        "# TODO: handle timeouts\ndef run():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_run(): pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def bare_project(tmp_path: Path) -> Path:
    """A project with source but no tests, no docs, no manifests."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "thing.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


# ═══════════════════════════════════════════════════════════════════════════
# ProjectIntelligence — measures, never guesses
# ═══════════════════════════════════════════════════════════════════════════

class TestProjectIntelligence:
    def test_measures_languages_and_tests(self, py_project: Path) -> None:
        snap = ProjectIntelligence(py_project).scan()
        assert snap.languages.get("Python", 0) >= 2
        assert snap.test_files == 1
        assert "pytest" in snap.test_frameworks
        assert "pyproject.toml" in snap.dependency_manifests

    def test_counts_todo_markers(self, py_project: Path) -> None:
        assert ProjectIntelligence(py_project).scan().todo_count == 1

    def test_shallow_scan_skips_todo_read(self, py_project: Path) -> None:
        """``deep=False`` is the pre-flight path; it must not open every file."""
        assert ProjectIntelligence(py_project).scan(deep=False).todo_count == 0

    def test_missing_root_is_a_critical_finding_not_an_exception(self, tmp_path: Path) -> None:
        snap = ProjectIntelligence(tmp_path / "does-not-exist").scan()
        assert snap.file_count == 0
        assert any(f.severity is Severity.CRITICAL for f in snap.findings)

    def test_absent_tests_produce_a_high_finding(self, bare_project: Path) -> None:
        snap = ProjectIntelligence(bare_project).scan()
        ids = {f.id for f in snap.findings}
        assert "no-tests" in ids
        assert "no-docs" in ids

    def test_skips_noise_directories(self, py_project: Path) -> None:
        noise = py_project / "node_modules" / "pkg"
        noise.mkdir(parents=True)
        for i in range(30):
            (noise / f"f{i}.js").write_text("x", encoding="utf-8")
        assert ProjectIntelligence(py_project).scan().languages.get("JavaScript", 0) == 0

    def test_every_finding_carries_evidence(self, bare_project: Path) -> None:
        """A finding without evidence is an assertion the reader cannot check."""
        for f in ProjectIntelligence(bare_project).scan().findings:
            assert f.evidence, f"finding {f.id} has no evidence"


# ═══════════════════════════════════════════════════════════════════════════
# Planner
# ═══════════════════════════════════════════════════════════════════════════

class TestMissionPlanner:
    def test_brief_reports_only_measured_state(self, py_project: Path) -> None:
        snap = ProjectIntelligence(py_project).scan()
        brief = MissionPlanner(snap).build_brief("corrigir bugs")
        joined = " ".join(brief.snapshot.summary_lines())
        assert "Python" in joined
        assert "Ficheiros de teste: 1" in joined

    def test_interpretation_reflects_the_request(self, py_project: Path) -> None:
        planner = MissionPlanner(ProjectIntelligence(py_project).scan())
        fix = planner.build_brief("corrigir bugs").objective_interpreted
        sec = planner.build_brief("rever segurança").objective_interpreted
        assert "corrigir defeitos" in fix.lower()
        assert "segurança" in sec.lower()
        # Sentence-cased, and the tail is preserved verbatim.
        assert fix[0].isupper() and fix.endswith(".")

    def test_unmatched_request_is_echoed_not_invented(self, py_project: Path) -> None:
        planner = MissionPlanner(ProjectIntelligence(py_project).scan())
        interpreted = planner.build_brief("zzz qqq").objective_interpreted
        assert "zzz qqq" in interpreted

    def test_verification_phase_is_skipped_with_a_reason_when_no_runner(
        self, bare_project: Path
    ) -> None:
        snap = ProjectIntelligence(bare_project).scan()
        planner = MissionPlanner(snap)
        plan = planner.build_plan(planner.build_brief("melhorar"))
        verify = next(p for p in plan.phases if p.phase is MissionPhase.VERIFICATION)
        assert verify.skipped
        assert verify.skip_reason

    def test_plan_always_has_five_phases_in_order(self, py_project: Path) -> None:
        snap = ProjectIntelligence(py_project).scan()
        planner = MissionPlanner(snap)
        plan = planner.build_plan(planner.build_brief("x"))
        assert [p.phase for p in plan.phases] == list(MissionPhase)

    def test_concurrency_stays_inside_the_band(self, py_project: Path) -> None:
        snap = ProjectIntelligence(py_project).scan()
        planner = MissionPlanner(snap)
        assert 3 <= planner.build_plan(planner.build_brief("x")).concurrency_limit <= 6

    def test_agents_the_project_has_no_use_for_are_skipped(self, py_project: Path) -> None:
        """The failure mode this replaces: an agent existing because it was
        available rather than because it was needed."""
        snap = ProjectIntelligence(py_project).scan()
        planner = MissionPlanner(snap)
        waves = planner.build_waves(planner.build_brief("x"))
        by_name = {c.name: c for w in waves for c in w.contracts}

        frontend = by_name["Frontend Agent"]
        assert frontend.state is ContractState.SKIPPED
        assert "frontend" in frontend.error.lower()

        assert by_name["Backend Agent"].state is ContractState.PROPOSED

    def test_no_agent_starts_at_planning_time(self, py_project: Path) -> None:
        snap = ProjectIntelligence(py_project).scan()
        planner = MissionPlanner(snap)
        waves = planner.build_waves(planner.build_brief("x"))
        assert all(
            c.state in (ContractState.PROPOSED, ContractState.SKIPPED)
            for w in waves
            for c in w.contracts
        )

    def test_every_live_contract_justifies_itself(self, py_project: Path) -> None:
        snap = ProjectIntelligence(py_project).scan()
        planner = MissionPlanner(snap)
        for wave in planner.build_waves(planner.build_brief("x")):
            for c in wave.contracts:
                assert c.justification.strip()
                if c.state is not ContractState.SKIPPED:
                    assert c.completion_criteria, f"{c.name} has no completion criteria"

    def test_later_waves_depend_on_earlier_ones(self, py_project: Path) -> None:
        snap = ProjectIntelligence(py_project).scan()
        planner = MissionPlanner(snap)
        waves = planner.build_waves(planner.build_brief("x"))
        assert waves[0].contracts[0].dependencies == []
        assert waves[1].contracts[0].dependencies


# ═══════════════════════════════════════════════════════════════════════════
# Tracker
# ═══════════════════════════════════════════════════════════════════════════

class TestMissionTracker:
    def test_start_mission_emits_brief_before_waves(self, py_project: Path) -> None:
        """Ordering is the contract: the user must be able to disagree with the
        interpretation before agents exist."""
        seen: list[str] = []
        start_mission(
            "melhorar", project_path=str(py_project),
            sink=lambda e, _p: seen.append(e), deep_scan=False,
        )
        assert seen.index("mission_brief") < seen.index("mission_plan")
        assert seen.index("mission_plan") < seen.index("mission_waves")

    def test_a_broken_sink_cannot_break_the_mission(self, py_project: Path) -> None:
        def explode(_e: str, _p: dict) -> None:
            raise RuntimeError("observability is down")

        tracker = start_mission(
            "x", project_path=str(py_project), sink=explode, deep_scan=False
        )
        assert tracker.mission.brief is not None
        assert tracker.mission.waves

    def test_agent_lifecycle_updates_state(self, py_project: Path) -> None:
        t = start_mission("x", project_path=str(py_project), deep_scan=False)
        t.start_wave(1)
        c = t.start_agent("Project Intelligence Agent")
        assert c.state is ContractState.RUNNING
        t.update_agent(
            "Project Intelligence Agent",
            activity="os.walk",
            discovery="SSE não fecha",
            file_changed="backend/main.py",
            confidence=0.84,
        )
        assert c.discoveries == ["SSE não fecha"]
        assert c.confidence == pytest.approx(0.84)
        t.finish_agent("Project Intelligence Agent")
        assert c.state is ContractState.COMPLETED

    def test_confidence_is_clamped(self, py_project: Path) -> None:
        t = start_mission("x", project_path=str(py_project), deep_scan=False)
        t.start_wave(1)
        t.start_agent("Project Intelligence Agent")
        t.update_agent("Project Intelligence Agent", confidence=5.0)
        assert t.find_contract("Project Intelligence Agent").confidence == 1.0

    def test_progress_counts_skipped_as_resolved(self, py_project: Path) -> None:
        t = start_mission("x", project_path=str(py_project), deep_scan=False)
        assert t.mission.progress > 0  # skipped agents already resolved

    def test_verification_passes_only_on_exit_zero(self, py_project: Path) -> None:
        """The point of the layer: success cannot be asserted, only earned."""
        t = start_mission("x", project_path=str(py_project), deep_scan=False)
        ok = t.run_verification(["python3", "-c", "raise SystemExit(0)"])
        bad = t.run_verification(["python3", "-c", "raise SystemExit(3)"])
        assert ok.passed and ok.exit_code == 0
        assert not bad.passed and bad.exit_code == 3
        assert t.mission.tests_passed == 1
        assert t.mission.tests_failed == 1

    def test_unrunnable_command_is_recorded_not_raised(self, py_project: Path) -> None:
        r = start_mission(
            "x", project_path=str(py_project), deep_scan=False
        ).run_verification(["definitely-not-a-real-binary-xyz"])
        assert not r.passed
        assert r.skipped_reason == "not-executable"

    def test_decisions_are_numbered_and_keep_alternatives(self, py_project: Path) -> None:
        t = start_mission("x", project_path=str(py_project), deep_scan=False)
        d = t.record_decision("A", "porque sim", ["B", "C"], outcome="A")
        assert d.number == 2  # #1 is the wave-strategy decision from start_mission
        assert d.alternatives == ["B", "C"]

    def test_persist_round_trips(self, py_project: Path, tmp_path: Path, monkeypatch) -> None:
        import backend.orchestrator.mission_control as mc

        monkeypatch.setattr(mc, "MISSIONS_DIR", tmp_path / "missions")
        t = start_mission("x", project_path=str(py_project), deep_scan=False)
        path = t.persist()
        assert path is not None
        assert json.loads(path.read_text(encoding="utf-8"))["id"] == t.mission.id

    def test_to_dict_is_json_serialisable(self, py_project: Path) -> None:
        t = start_mission("x", project_path=str(py_project), deep_scan=False)
        t.start_wave(1)
        t.start_agent("Project Intelligence Agent")
        assert json.loads(json.dumps(t.mission.to_dict()))["waves"]


# ═══════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════

class TestMissionReport:
    def _finished(self, project: Path) -> MissionTracker:
        t = start_mission("corrigir bugs", project_path=str(project), deep_scan=False)
        t.start_wave(1)
        t.start_agent("Project Intelligence Agent")
        t.update_agent(
            "Project Intelligence Agent",
            file_changed="backend/main.py",
            command="pytest -q",
        )
        t.finish_agent("Project Intelligence Agent")
        t.finish_wave(1)
        return t

    def test_report_contains_every_mandated_section(self, py_project: Path) -> None:
        t = self._finished(py_project)
        t.run_verification(["python3", "-c", "pass"])
        t.complete(risks=["SSE sem reconexão"], suggestions=["Usar Redis Streams"])
        md = MissionReport(t.mission).render()
        for section in (
            "Pedido original", "Interpretação do objetivo", "Estado inicial",
            "Problemas encontrados", "Plano executado", "Agentes criados",
            "Alterações realizadas", "Comandos executados", "Testes e resultados",
            "Registo de decisões", "Problemas corrigidos", "Problemas não resolvidos",
            "Riscos técnicos", "Melhorias sugeridas", "Próximas ações",
            "Como reverter", "Resumo executivo", "Confiança global",
        ):
            assert section in md, f"missing section: {section}"

    def test_changes_without_verification_cap_confidence_low(self, py_project: Path) -> None:
        """A run that edited files and tested nothing must not read as assurance."""
        t = self._finished(py_project)
        t.complete()
        assert "baixa" in MissionReport(t.mission).render()

    def test_all_green_reads_high(self, py_project: Path) -> None:
        t = self._finished(py_project)
        t.run_verification(["python3", "-c", "pass"])
        t.complete()
        assert "alta" in MissionReport(t.mission).render()

    def test_failed_verification_downgrades_confidence(self, py_project: Path) -> None:
        t = self._finished(py_project)
        t.run_verification(["python3", "-c", "raise SystemExit(1)"])
        t.complete()
        assert "média" in MissionReport(t.mission).render()

    def test_untested_changes_are_named_in_next_actions(self, py_project: Path) -> None:
        t = self._finished(py_project)
        t.complete()
        assert "alterações não validadas" in MissionReport(t.mission).render()

    def test_pipes_in_content_do_not_break_tables(self, py_project: Path) -> None:
        t = self._finished(py_project)
        t.mission.waves[0].contracts[0].justification = "a | b | c"
        t.complete()
        assert "a \\| b \\| c" in MissionReport(t.mission).render()

    def test_no_changes_means_nothing_to_revert(self, py_project: Path) -> None:
        t = start_mission("x", project_path=str(py_project), deep_scan=False)
        t.complete()
        assert "não há nada para reverter" in MissionReport(t.mission).render()

    def test_writes_to_reports_directory(self, py_project: Path, tmp_path: Path, monkeypatch) -> None:
        import backend.orchestrator.mission_control as mc

        monkeypatch.setattr(mc, "REPORTS_DIR", tmp_path / "reports")
        t = self._finished(py_project)
        t.complete()
        path = MissionReport(t.mission).write()
        assert path is not None and path.exists()
        assert path.name.startswith("nexus-run-") and path.suffix == ".md"


# ═══════════════════════════════════════════════════════════════════════════
# Git-aware rollback
# ═══════════════════════════════════════════════════════════════════════════

class TestRollbackInstructions:
    def test_git_repo_yields_checkout_commands(self, tmp_path: Path) -> None:
        try:
            for args in (
                ["init", "-q"],
                ["config", "user.email", "t@t.t"],
                ["config", "user.name", "t"],
            ):
                subprocess.run(["git", *args], cwd=tmp_path, check=True, timeout=15)
            (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, timeout=15)
            subprocess.run(
                ["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True, timeout=15
            )
        except (OSError, subprocess.SubprocessError):
            pytest.skip("git unavailable")

        t = start_mission("x", project_path=str(tmp_path), deep_scan=False)
        t.start_wave(1)
        t.start_agent("Project Intelligence Agent")
        t.update_agent("Project Intelligence Agent", file_changed="a.py")
        t.finish_agent("Project Intelligence Agent")
        t.complete()

        md = MissionReport(t.mission).render()
        assert "git checkout -- a.py" in md
        assert t.mission.brief.snapshot.git_branch is not None

    def test_without_git_the_report_says_so_instead_of_inventing_commands(
        self, py_project: Path
    ) -> None:
        t = start_mission("x", project_path=str(py_project), deep_scan=False)
        t.start_wave(1)
        t.start_agent("Project Intelligence Agent")
        t.update_agent("Project Intelligence Agent", file_changed="backend/main.py")
        t.finish_agent("Project Intelligence Agent")
        t.complete()
        md = MissionReport(t.mission).render()
        assert "Sem repositório git" in md
        assert "git checkout" not in md


class TestTestFileCountingIsNotNameOnly:
    """``_is_test_file`` matched on filename alone, so any artifact called
    ``test_*`` counted as a test. A pytest SQLite fixture (``test_nexus.db``)
    plus its ``-wal``/``-shm`` siblings turned a 1-test project into a
    4-test one, and every mission brief reported the inflated number."""

    def test_binary_fixtures_named_test_are_not_tests(self) -> None:
        for name in ("test_nexus.db", "test_nexus.db-wal", "test_data.json",
                     "test_fixture.sql", "test_image.png", "test_report.md"):
            assert ProjectIntelligence._is_test_file(name) is False, name

    def test_real_test_sources_still_count(self) -> None:
        for name in ("test_main.py", "handlers_test.py", "auth.test.ts",
                     "Button.spec.tsx", "api_test.go"):
            assert ProjectIntelligence._is_test_file(name) is True, name

    def test_count_ignores_a_database_dropped_into_the_project(
        self, py_project: Path
    ) -> None:
        """Reproduces the pollution exactly: a DB fixture beside the sources."""
        (py_project / "test_nexus.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
        (py_project / "test_nexus.db-wal").write_bytes(b"\x00" * 32)

        snap = ProjectIntelligence(py_project).scan()

        assert snap.test_files == 1, "only tests/test_main.py is a test"
        assert "Ficheiros de teste: 1" in " ".join(snap.summary_lines())
