"""End-to-end: one normal group-composer message = one primary execution.

The backend is a real uvicorn process; the provider is a real loopback HTTP
server whose *answers* are scripted.  The coordinator, SQLite persistence, tool
registry, file confinement, SSE relay and restart behaviour are the production
implementations.

Evidence for every run is written under ``$TEMP/opencode/nexus-e2e-group-*`` (or
``NEXUS_E2E_EVIDENCE_DIR``), never under the canonical ``data/`` directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.tests.support.group_harness import GroupHarness
from backend.tests.support.group_runtime import (
    frame_envelope_problems,
    group_messages,
    run_messages,
    runtime_seq_problems,
    session_messages,
    wait_for_group_run,
    wait_for_terminal,
)
from backend.tests.support.nexus_backend import table_columns
from backend.tests.support.scripted_provider import tool_call

pytestmark = pytest.mark.integration

CANARY = "CANARY-7F3A-DO-RUNTIME"


def _read_then_answer(call) -> str:
    prompt = call.prompt_text
    if CANARY in prompt and "Tool read_file returned" in prompt:
        return f"Token lido do ficheiro: {CANARY}"
    if call.index == 0:
        return tool_call("read_file", {"path": "canary.txt"})
    return f"Token lido do ficheiro: {CANARY}"


def test_normal_composer_runs_one_primary_execution_with_real_tool_call(
    tmp_path: Path,
) -> None:
    with GroupHarness(tmp_path / "normal") as harness:
        harness.register_project()
        (harness.handle.workspace / "canary.txt").write_text(
            f"fixture token {CANARY}\n", encoding="utf-8"
        )
        seeded = harness.seed(bot_names=["Leitor", "Revisor"], group_name="Composer E2E")
        group_id = seeded["group"]["id"]
        harness.provider.set_responder(_read_then_answer)

        result = harness.send(
            group_id,
            "Lê o ficheiro canary.txt do projeto e devolve o token exato que lá está.",
            project_path=str(harness.handle.workspace),
            timeout=120.0,
        )

        problems: list[str] = []
        if result.status_code != 200:
            problems.append(
                f"composer returned HTTP {result.status_code}: {result.error or result.body[:500]}"
            )
        if "text/event-stream" not in result.content_type:
            problems.append(
                f"composer did not stream SSE (content-type={result.content_type!r})"
            )
        if not result.frames:
            problems.append("no SSE frames were produced")
        if result.run_ids:
            run_id = result.run_ids[0]
        else:
            problems.append("no frame carried a canonical run_id")
            run_id = ""
        envelope = frame_envelope_problems(result.frames)
        if envelope:
            problems.extend(envelope[:8])
        runtime_order = runtime_seq_problems(result.frames)
        if runtime_order:
            problems.extend(runtime_order[:8])

        run_row: dict[str, Any] | None = None
        if group_id:
            run_row = wait_for_group_run(
                harness.handle.db_path,
                group_id,
                request="Lê o ficheiro canary.txt do projeto e devolve o token exato que lá está.",
                timeout=20,
            )
        if run_row is None:
            problems.append("no bot_group_runs row was created for the composer message")
            persisted_run_id = run_id
        else:
            persisted_run_id = str(run_row.get("id") or "")
            if run_id and persisted_run_id != run_id:
                problems.append(
                    f"frame run_id {run_id!r} != persisted bot_group_runs.id {persisted_run_id!r}"
                )
            if not persisted_run_id.startswith("run-"):
                problems.append(f"run id is not canonical: {persisted_run_id!r}")
            if run_row.get("status") != "completed":
                problems.append(
                    f"bot_group_runs.status={run_row.get('status')!r}, expected completed"
                )
            if run_row.get("execution_engine") != "primary":
                problems.append(
                    "bot_group_runs.execution_engine="
                    f"{run_row.get('execution_engine')!r}, expected 'primary'"
                )

        state: dict[str, Any] = harness.state(persisted_run_id) if persisted_run_id else {}
        run_state = state.get("run_state") or {}
        if not run_state:
            problems.append("run_state row is missing")
        else:
            if run_state.get("run_id") != persisted_run_id:
                problems.append("run_state.run_id does not match the projection")
            if run_state.get("state") != "completed":
                problems.append(f"run_state.state={run_state.get('state')!r}, expected completed")
            dod_raw = run_state.get("dod_results_json")
            try:
                dod = json.loads(dod_raw or "[]")
            except (TypeError, ValueError):
                dod = []
            if not dod:
                problems.append("run_state has no definition-of-done evidence")
            else:
                requirements = {str(item.get("requirement")) for item in dod}
                if len(requirements) < 2:
                    problems.append(f"definition-of-done evidence is incomplete: {dod}")
                if not all(str(item.get("verdict")) in {"PASS", "N/A"} for item in dod):
                    problems.append(f"definition-of-done has a non-passing verdict: {dod}")

        tasks = state.get("tasks") or []
        if len(tasks) != 1:
            problems.append(f"expected exactly one selected bot task, found {len(tasks)}")
        else:
            if tasks[0].get("status") != "completed":
                problems.append(f"selected task status={tasks[0].get('status')!r}")
            if tasks[0].get("bot_id") not in {bot["id"] for bot in seeded["bots"]}:
                problems.append("selected task bot_id is not a group member")

        if not state.get("checkpoints"):
            problems.append("no run_checkpoints were persisted")
        if not state.get("session_runs"):
            problems.append("no session_runs row was persisted for the canonical run")

        bots_by_id = {bot["id"]: bot for bot in seeded["bots"]}
        selected_bot_id = str(tasks[0].get("bot_id") or "") if tasks else ""
        selected = bots_by_id.get(selected_bot_id)
        if selected is None:
            problems.append("could not resolve the selected bot's session")
        else:
            session_runs = state.get("session_runs") or []
            group_session_id = str(session_runs[0].get("session_id") or "") if session_runs else ""
            if not group_session_id or group_session_id == str(selected["session_id"]):
                problems.append("group run did not use its own session")
            bot_messages = session_messages(harness.handle.db_path, group_session_id)
            assistant = [m for m in bot_messages if m.get("role") == "assistant"]
            if not assistant:
                problems.append("the selected bot session has no assistant message")
            else:
                if assistant[-1].get("run_id") != persisted_run_id:
                    problems.append(
                        "the bot session assistant message is not linked to the canonical run_id"
                    )
                if CANARY not in str(assistant[-1].get("content") or ""):
                    problems.append("the assistant message does not contain the real tool result")

        message_columns = table_columns(harness.handle.db_path, "bot_group_messages")
        if "run_id" not in message_columns:
            problems.append(
                "CONTRACT-GAP: bot_group_messages.run_id is missing; the run link only "
                "exists in bot_group_run_records"
            )
        else:
            linked = run_messages(harness.handle.db_path, persisted_run_id)
            if not linked:
                problems.append("no group message is persisted with the canonical run_id")
            assistant_group = [m for m in linked if m.get("role") == "assistant"]
            if not assistant_group:
                problems.append("no assistant group message is linked to the canonical run_id")
            elif CANARY not in str(assistant_group[-1].get("content") or ""):
                problems.append("the assistant group message does not contain the tool result")

        # A UI reload reads the same group history. A duplicated message after
        # one request would make the same answer appear twice.
        page = harness.client.get(f"/api/bot-groups/{group_id}/messages?limit=100")
        if page.status_code != 200:
            problems.append(f"GET group messages failed: HTTP {page.status_code}")
        else:
            payload = page.json().get("messages") or []
            if len([m for m in payload if m.get("role") == "user"]) != 1:
                problems.append("the reloaded group history has more than one user message")
            if len([m for m in payload if m.get("role") == "assistant"]) != 1:
                problems.append("the reloaded group history does not have exactly one answer")

        # Provider proof: the model was called at least twice (tool request then
        # answer), and the second prompt contained the real tool output.
        if harness.provider.chat_calls < 2:
            problems.append(
                f"only {harness.provider.chat_calls} provider call(s); a tool-using "
                "PrimaryLoop must call the model again with the tool result"
            )
        prompts = harness.provider.chat_prompts
        if len(prompts) >= 2 and CANARY not in prompts[1]:
            problems.append("the second provider prompt did not contain the real tool result")
        if any(model != "scripted:latest" for model in harness.provider.chat_models):
            problems.append(f"unexpected provider model calls: {harness.provider.chat_models}")

        # The legacy file executor has a very specific fingerprint: it records
        # a handoff and a read_file tool call before any provider turn. The new
        # composer path must not have produced it.
        records = state.get("records") or []
        if records:
            if any(str(record.get("kind")) == "handoff" for record in records):
                problems.append("LEGACY PATH USED: a handoff record exists")
            for record in records:
                if str(record.get("kind")) != "tool_call":
                    continue
                payload = record.get("payload") or {}
                if (
                    payload.get("tool") == "read_file"
                    and payload.get("path") == "canary.txt"
                    and "runtime_seq" not in payload
                ):
                    problems.append("LEGACY PATH USED: _execute_run recorded the pre-read")
            if not any(str(record.get("kind")) == "execution" for record in records):
                problems.append("no execution record identifies the engine")
        else:
            problems.append("the run has no durable records")

        done_frames = [
            frame for frame in result.frames if str(frame.get("type")) == "done"
        ]
        if not done_frames:
            problems.append("no terminal done frame")
        else:
            final_status = str(done_frames[-1].get("status") or "")
            if final_status != "completed":
                problems.append(f"terminal frame status={final_status!r}, expected completed")
            if not done_frames[-1].get("verification"):
                problems.append("terminal frame has no verification evidence")

        harness.write_evidence(
            "normal-composer",
            {
                "run_id": persisted_run_id,
                "result": {
                    "status": result.status_code,
                    "content_type": result.content_type,
                    "frame_types": result.event_types,
                    "frames": result.frames,
                    "run_ids": result.run_ids,
                    "text": result.text[-2000:],
                },
                "run_row": run_row,
                "run_state": run_state,
                "tasks": tasks,
                "problems": problems,
            },
        )
        if problems:
            pytest.fail(
                "normal composer scenario failed:\n- " + "\n- ".join(dict.fromkeys(problems))
            )


def test_reload_and_restart_keep_the_same_run_and_terminal_state(tmp_path: Path) -> None:
    with GroupHarness(tmp_path / "reload") as harness:
        harness.register_project()
        seeded = harness.seed(bot_names=["Alpha", "Beta"], group_name="Reload E2E")
        group_id = seeded["group"]["id"]
        harness.provider.load(["Resposta estável e verificável."])

        message = "Diz apenas OK."
        first = harness.send(group_id, message, timeout=120.0)
        assert first.status_code == 200, first.error or first.body[:500]
        run_id = next(iter(first.run_ids), "")
        assert run_id, "the composer did not expose a canonical run_id"
        row = wait_for_terminal(harness.handle.db_path, group_id, run_id, timeout=30)
        assert row["status"] == "completed"

        before_messages = group_messages(harness.handle.db_path, group_id)
        before_page = harness.client.get(f"/api/bot-groups/{group_id}/messages?limit=100")
        assert before_page.status_code == 200
        before_api = before_page.json()["messages"]
        before_calls = harness.provider.chat_calls

        # Browser reload: same history, no duplicated answer.
        reload_page = harness.client.get(f"/api/bot-groups/{group_id}/messages?limit=100")
        assert reload_page.status_code == 200
        reloaded = reload_page.json()["messages"]
        assert [m["id"] for m in reloaded] == [m["id"] for m in before_api]
        assert len([m for m in reloaded if m["role"] == "assistant"]) == 1

        # Backend restart: same database and workspace, new process.
        harness.restart_backend()
        after_page = harness.client.get(f"/api/bot-groups/{group_id}/messages?limit=100")
        assert after_page.status_code == 200
        after_api = after_page.json()["messages"]
        assert [m["id"] for m in after_api] == [m["id"] for m in before_api]
        after_messages = group_messages(harness.handle.db_path, group_id)
        assert [m["id"] for m in after_messages] == [m["id"] for m in before_messages]

        runs_response = harness.client.get(f"/api/bot-groups/{group_id}/runs")
        assert runs_response.status_code == 200
        runs = runs_response.json()["runs"]
        matching = [run for run in runs if run.get("id") == run_id]
        assert matching, "the same run disappeared after restart"
        assert matching[0].get("execution_engine") == "primary"
        assert matching[0].get("run_state") == "completed"

        state = harness.state(run_id)
        assert state.get("run_state", {}).get("state") == "completed"
        assert harness.provider.chat_calls == before_calls, (
            "a completed run was replayed after restart (new provider calls)"
        )

        harness.write_evidence(
            "reload-restart",
            {
                "run_id": run_id,
                "messages_before": len(before_messages),
                "messages_after": len(after_messages),
                "provider_calls_before": before_calls,
                "provider_calls_after": harness.provider.chat_calls,
                "run_after": matching[0],
                "run_state": state.get("run_state"),
            },
        )
