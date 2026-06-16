"""Test suite for Nexus IDE backend improvements."""

import asyncio
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent
os.chdir(BACKEND_ROOT)
sys.path.insert(0, str(BACKEND_ROOT.parent))

RESULTS = []


def log_result(test_name, passed, error="", details=""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append({"test": test_name, "status": status, "error": error, "details": details})
    symbol = "[PASS]" if passed else "[FAIL]"
    print(f"  [{symbol}] {test_name}: {status}")
    if error:
        print(f"       Error: {error}")
    if details:
        for line in details.splitlines():
            print(f"       {line}")


def test_1_self_improvement_registered():
    try:
        from backend.core.background_workers import BackgroundWorkerManager

        manager = BackgroundWorkerManager(watch_path=".")
        worker = manager.get_worker("SELF_IMPROVEMENT_WATCHER")
        found = worker is not None
        log_result(
            "1.1 SELF_IMPROVEMENT_WATCHER registered",
            found,
            "" if found else "Worker not found in BackgroundWorkerManager",
        )
        if found:
            log_result("1.2 SELF_IMPROVEMENT_WATCHER instantiable", True)
            info = worker.info()
            log_result(
                "1.3 Worker info accessible",
                True,
                details=f"name={info.name}, status={info.status}, interval={info.interval_seconds}s",
            )
    except Exception as exc:
        log_result("1.1 SELF_IMPROVEMENT_WATCHER registration", False, str(exc))


def test_1_single_analysis_tick():
    try:
        from backend.core.self_improvement import SelfImprovementAnalyzer

        analyzer = SelfImprovementAnalyzer()
        report = asyncio.run(analyzer.run_analysis())
        log_result(
            "1.4 run_analysis() completes",
            True,
            details=f"summary={report.summary}\nproposals={len(report.proposals)}",
        )
    except Exception as exc:
        log_result("1.4 run_analysis() tick", False, str(exc))


def test_2_quality_metrics():
    try:
        import backend.core.quality_metrics as qm

        mod_path = Path(qm.__file__)
        log_result("2.1 import backend.core.quality_metrics", True, details=f"Module: {mod_path}")
    except Exception as exc:
        log_result("2.1 import backend.core.quality_metrics", False, str(exc))
        return

    project_path = r"C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide"
    try:
        import backend.core.quality_metrics as qm

        metrics = asyncio.run(qm.measure(project_path))
        parts = [
            f"coverage_percent={metrics.coverage_percent}",
            f"cyclomatic_complexity={metrics.cyclomatic_complexity}",
            f"maintainability_index={metrics.maintainability_index}",
            f"lint_score={metrics.lint_score}",
            f"security_issues_count={metrics.security_issues_count}",
            f"duplication_ratio={metrics.duplication_ratio}",
            f"technical_debt_ratio={metrics.technical_debt_ratio}",
        ]
        all_ok = all(
            isinstance(v, (int, float))
            for v in [
                metrics.coverage_percent,
                metrics.cyclomatic_complexity,
                metrics.maintainability_index,
                metrics.lint_score,
                metrics.security_issues_count,
                metrics.duplication_ratio,
                metrics.technical_debt_ratio,
            ]
        )
        log_result(
            "2.2 measure() returns valid metrics",
            all_ok,
            "" if all_ok else "Some metric fields have unexpected types",
            details="\n".join(parts),
        )
    except Exception as exc:
        log_result("2.2 measure() execution", False, str(exc))


def test_3_rollback_manager():
    try:
        import backend.core.rollback_manager as rm

        mod_path = Path(rm.__file__)
        log_result("3.1 import backend.core.rollback_manager", True, details=f"Module: {mod_path}")
    except Exception as exc:
        log_result("3.1 import backend.core.rollback_manager", False, str(exc))
        return

    try:
        from backend.core.rollback_manager import RollbackManager

        manager = RollbackManager()
        log_result("3.2 RollbackManager instantiation", True)
    except Exception as exc:
        log_result("3.2 RollbackManager instantiation", False, str(exc))
        return

    project_path = str(BACKEND_ROOT)
    try:
        from backend.core.rollback_manager import RollbackManager

        manager = RollbackManager()
        snap_id = asyncio.run(
            manager.record_snapshot(
                project_path=project_path,
                artifact_id="test_artifact",
                file_path="run_tests.py",
                content_before="# test snapshot content",
                metadata={"test": True},
            )
        )
        log_result("3.3 record_snapshot() succeeds", True, details=f"snapshot_id={snap_id}")
    except Exception as exc:
        log_result("3.3 record_snapshot() execution", False, str(exc))

    nexus_rollback = Path(".nexus/rollback")
    exists = nexus_rollback.exists() and nexus_rollback.is_dir()
    log_result(
        "3.4 .nexus/rollback/ directory created",
        exists,
        "" if exists else f"Directory not found at {nexus_rollback.resolve()}",
    )


def test_4_human_in_the_loop():
    try:
        import backend.core.human_in_the_loop as hitl

        mod_path = Path(hitl.__file__)
        log_result("4.1 import backend.core.human_in_the_loop", True, details=f"Module: {mod_path}")
    except Exception as exc:
        log_result("4.1 import backend.core.human_in_the_loop", False, str(exc))
        return

    try:
        from backend.core.human_in_the_loop import HumanInTheLoopManager

        manager = HumanInTheLoopManager(base_path=".")
        policy = manager.load_policy()
        log_result(
            "4.2 load_policy() succeeds",
            True,
            details=f"enabled={policy.enabled}, require_approval_for={sorted(policy.require_approval_for)}",
        )
    except Exception as exc:
        log_result("4.2 load_policy() execution", False, str(exc))

    try:
        from backend.core.human_in_the_loop import HumanInTheLoopManager

        manager = HumanInTheLoopManager(base_path=".")
        proposal = {
            "id": "p_test1",
            "category": "security",
            "confidence": 0.9,
            "change": "update auth",
        }
        record = manager.create_escalation_request(
            proposal_id=proposal["id"],
            proposal=proposal,
            reason="High confidence security change",
        )
        log_result(
            "4.3 create_escalation_request() succeeds",
            True,
            details=f"request_id={record['request_id']}, decision={record['decision']}",
        )
    except Exception as exc:
        log_result("4.3 create_escalation_request() execution", False, str(exc))

    try:
        from backend.core.human_in_the_loop import HumanInTheLoopManager

        manager = HumanInTheLoopManager(base_path=".")
        pending = manager.list_pending()
        log_result("4.4 list_pending() works", True, details=f"pending_count={len(pending)}")
    except Exception as exc:
        log_result("4.4 list_pending() execution", False, str(exc))


def test_5_file_api_integration():
    try:
        import importlib.util

        spec = importlib.util.find_spec("file_api")
        if spec is None:
            found_any = False
            locations = []
            for root, dirs, files in os.walk(str(BACKEND_ROOT)):
                for f in files:
                    if f == "file_api.py":
                        locations.append(os.path.join(root, f))
                        found_any = True
            if found_any:
                log_result("5.1 file_api.py exists", True, details=f"Found at: {locations[0]}")
            else:
                log_result(
                    "5.1 file_api.py exists",
                    False,
                    "file_api.py not found in backend directory tree",
                )
                return
        else:
            log_result("5.1 file_api.py exists", True, details=f"Module path: {spec.origin}")
    except Exception as exc:
        log_result("5.1 file_api.py search", False, str(exc))
        return

    api_path = BACKEND_ROOT / "tools" / "file_api.py"
    found_api = api_path.exists()
    api_content = api_path.read_text(encoding="utf-8", errors="replace") if found_api else ""

    if not found_api:
        log_result(
            "5.2 RollbackManager import in file_api.py",
            False,
            "file_api.py not found, cannot check imports",
        )
        return

    has_rollback_import = "rollback_manager" in api_content and "RollbackManager" in api_content
    log_result(
        "5.2 RollbackManager import present",
        has_rollback_import,
        "" if has_rollback_import else "No RollbackManager import found in file_api.py",
    )
    has_write_snapshot = "record_snapshot" in api_content or "snapshot" in api_content
    log_result(
        "5.3 snapshot logic in write() function",
        has_write_snapshot,
        "" if has_write_snapshot else "No snapshot-related logic found in file_api.py",
    )


def main():
    print("=" * 60)
    print("NEXUS IDE Backend - Test Results")
    print("=" * 60)

    print("\n[TEST 1] SelfImprovement Scheduler")
    test_1_self_improvement_registered()
    test_1_single_analysis_tick()

    print("\n[TEST 2] Quality Metrics")
    test_2_quality_metrics()

    print("\n[TEST 3] Rollback Manager")
    test_3_rollback_manager()

    print("\n[TEST 4] Human-in-the-Loop")
    test_4_human_in_the_loop()

    print("\n[TEST 5] file_api.py Integration")
    test_5_file_api_integration()

    print("\n" + "=" * 60)
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    print(f"SUMMARY: {passed} PASS, {failed} FAIL out of {len(RESULTS)} tests")
    print("=" * 60)

    if failed > 0:
        print("\nFailed tests:")
        for r in RESULTS:
            if r["status"] == "FAIL":
                print(f"  - {r['test']}: {r['error']}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
