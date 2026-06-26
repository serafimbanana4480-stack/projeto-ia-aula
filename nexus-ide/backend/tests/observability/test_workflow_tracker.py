"""Tests for WorkflowTracker."""
import json

import pytest

from backend.observability.workflow_tracker import WorkflowTracker


class TestWorkflowTracker:
    def test_create_and_get(self) -> None:
        tracker = WorkflowTracker()
        wf = tracker.create_workflow("story-1", "Build API")
        assert wf.story_id == "story-1"
        assert wf.goal == "Build API"
        assert wf.status == "pending"

        retrieved = tracker.get_workflow(wf.workflow_id)
        assert retrieved is not None
        assert retrieved.workflow_id == wf.workflow_id

    def test_workflow_lifecycle(self) -> None:
        tracker = WorkflowTracker()
        wf = tracker.create_workflow("story-1", "Build API")
        tracker.start_workflow(wf.workflow_id)

        assert wf.status == "running"
        assert wf.started_at > 0

        step = tracker.add_step(wf.workflow_id, "generate", "coder", inputs={"lang": "python"})
        assert step.name == "generate"
        assert step.status == "running"

        tracker.complete_step(wf.workflow_id, step.step_id, outputs={"files": 3})
        assert step.status == "completed"
        assert step.duration_ms >= 0

        tracker.complete_workflow(wf.workflow_id)
        assert wf.status == "completed"
        assert wf.completed_at > 0

    def test_fail_step(self) -> None:
        tracker = WorkflowTracker()
        wf = tracker.create_workflow("story-1", "Build API")
        step = tracker.add_step(wf.workflow_id, "test", "tester")
        tracker.fail_step(wf.workflow_id, step.step_id, "assertion failed")

        assert step.status == "failed"
        assert step.error == "assertion failed"

    def test_timeline(self) -> None:
        tracker = WorkflowTracker()
        wf = tracker.create_workflow("story-1", "Build API")
        tracker.start_workflow(wf.workflow_id)

        s1 = tracker.add_step(wf.workflow_id, "step1", "a1")
        tracker.complete_step(wf.workflow_id, s1.step_id)

        s2 = tracker.add_step(wf.workflow_id, "step2", "a2")
        tracker.complete_step(wf.workflow_id, s2.step_id)

        tracker.log_message(wf.workflow_id, "a1", "a2", "consult", "help")

        timeline = tracker.get_timeline(wf.workflow_id)
        assert len(timeline) == 3  # 2 steps + 1 message

    def test_conflict_detection(self) -> None:
        tracker = WorkflowTracker()
        wf = tracker.create_workflow("story-1", "Build API")

        tracker.log_message(wf.workflow_id, "a1", "a2", "conflict", "disagree")

        s1 = tracker.add_step(wf.workflow_id, "same", "coder")
        s2 = tracker.add_step(wf.workflow_id, "same", "coder")

        conflicts = tracker.detect_conflicts(wf.workflow_id)
        assert len(conflicts) == 2  # 1 conflict message + 1 duplicate work

    def test_export(self) -> None:
        tracker = WorkflowTracker()
        wf = tracker.create_workflow("story-1", "Build API")
        exported = tracker.export_workflow(wf.workflow_id)
        data = json.loads(exported)
        assert data["story_id"] == "story-1"

    def test_list_workflows(self) -> None:
        tracker = WorkflowTracker()
        wf1 = tracker.create_workflow("story-1", "A")
        wf2 = tracker.create_workflow("story-2", "B")
        tracker.complete_workflow(wf1.workflow_id)

        all_wfs = tracker.list_workflows()
        assert len(all_wfs) == 2

        completed = tracker.list_workflows(status="completed")
        assert len(completed) == 1
        assert completed[0].workflow_id == wf1.workflow_id
