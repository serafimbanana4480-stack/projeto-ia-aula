"""Telemetry: prove where the time goes, and never invent progress."""

from __future__ import annotations

import time

from backend.runtime.telemetry import (
    BlockedOn,
    ProgressReport,
    RunPhase,
    RunTelemetry,
)


def test_headline_latencies_are_recorded_once() -> None:
    telemetry = RunTelemetry(run_id="run-1")
    telemetry.mark_first_token()
    first = telemetry.time_to_first_token
    time.sleep(0.01)
    telemetry.mark_first_token()
    assert telemetry.time_to_first_token == first


def test_text_alone_is_not_useful_work() -> None:
    """Answering fast is not the goal; starting real work fast is."""
    telemetry = RunTelemetry(run_id="run-1")
    telemetry.mark_first_token()

    assert telemetry.time_to_first_token is not None
    assert telemetry.time_to_first_action is None
    assert telemetry.time_to_first_tool_call is None
    assert telemetry.time_to_first_useful_work is None


def test_a_read_only_tool_call_is_an_action_and_useful_work() -> None:
    telemetry = RunTelemetry(run_id="run-1")
    telemetry.mark_tool_call()
    assert telemetry.time_to_first_action is not None
    assert telemetry.time_to_first_tool_call is not None
    assert telemetry.time_to_first_useful_work is None

    telemetry.mark_file_read()
    assert telemetry.time_to_first_useful_work is not None
    assert telemetry.files_read == 1


def test_phase_durations_accumulate() -> None:
    telemetry = RunTelemetry(run_id="run-1")
    telemetry.enter_phase(RunPhase.ROUTING)
    time.sleep(0.01)
    telemetry.enter_phase(RunPhase.PLANNING)
    time.sleep(0.01)
    telemetry.finish()

    assert telemetry.phase_durations[RunPhase.ROUTING.value] >= 0.005
    assert telemetry.phase_durations[RunPhase.PLANNING.value] >= 0.005
    assert telemetry.total_duration is not None


def test_parallelism_peak_tracks_the_high_water_mark() -> None:
    telemetry = RunTelemetry(run_id="run-1")
    telemetry.mark_subagent_started(1)
    telemetry.mark_subagent_started(3)
    telemetry.mark_subagent_started(2)
    assert telemetry.parallelism_peak == 3
    assert telemetry.agents_spawned == 3


def test_snapshot_is_serialisable_and_complete() -> None:
    telemetry = RunTelemetry(run_id="run-1")
    telemetry.blocked_on = BlockedOn.WAITING_MODEL
    snapshot = telemetry.snapshot()
    for key in (
        "time_to_first_token",
        "time_to_first_action",
        "time_to_first_tool_call",
        "time_to_first_useful_work",
        "tool_calls",
        "files_read",
        "files_changed",
        "commands_run",
        "tests_run",
        "retries",
        "parser_failures",
        "agents_spawned",
        "parallelism_peak",
    ):
        assert key in snapshot
    assert snapshot["blocked_on"] == "waiting_model"


def test_progress_never_reports_a_fake_zero_percent() -> None:
    indeterminate = ProgressReport(total=0, completed=0, running=1, pending=0, label="Indexing project…")
    assert indeterminate.percent is None
    assert indeterminate.render() == "Indexing project…"


def test_progress_is_derived_from_real_task_counts() -> None:
    report = ProgressReport(total=5, completed=2, running=1, pending=2)
    assert report.percent == 40
    assert report.render() == "2/5 (40%)"
