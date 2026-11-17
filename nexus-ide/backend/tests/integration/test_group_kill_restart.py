"""Kill/restart and cancellation proofs for the group primary runtime.

These tests use a real backend process and a real loopback provider.  They do
not patch the coordinator, persistence or tools.  The provider is only a model
double; it can hold a call open, which is what makes the crash and cancel
windows deterministic.
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

import pytest

from backend.tests.support.group_harness import GroupHarness
from backend.tests.support.group_runtime import (
    group_messages,
    latest_group_run,
    wait_for,
    wait_for_group_run,
)
from backend.tests.support.scripted_provider import tool_call

pytestmark = pytest.mark.integration

TOKEN_A = "WRITE-ONCE-A-1f4c"
TOKEN_B = "SHOULD-NEVER-BE-WRITTEN-B-9e2a"


def _write_then_hold(call) -> str:
    """Write TOKEN_A, then hold the follow-up call; never write TOKEN_B."""
    prompt = call.prompt_text
    if "Tool write_file returned" in prompt:
        return f"Concluído: resultado.txt contém {TOKEN_A}."
    if call.index == 0:
        return tool_call(
            "write_file",
            {"path": "resultado.txt", "content": TOKEN_A},
        )
    # If the runtime restarts the request from scratch instead of reconciling,
    # this second write would overwrite the file with a different token.
    return tool_call(
        "write_file",
        {"path": "resultado.txt", "content": TOKEN_B},
    )


def _wait_for_file(path: Path, timeout: float = 30.0) -> str:
    def read() -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    value = wait_for(lambda: read() or None, timeout=timeout, description="workspace write")
    return str(value)


def test_kill_after_workspace_write_does_not_repeat_it(tmp_path: Path) -> None:
    with GroupHarness(tmp_path / "kill") as harness:
        harness.register_project()
        seeded = harness.seed(bot_names=["Executor", "Revisor"], group_name="Kill E2E")
        group_id = seeded["group"]["id"]
        harness.provider.set_responder(_write_then_hold)
        harness.provider.block_on(1)

        message = "Cria o ficheiro resultado.txt com o conteúdo pedido e confirma."
        stream = harness.background_send(
            group_id, message, project_path=str(harness.handle.workspace)
        )
        target = harness.handle.workspace / "resultado.txt"

        written = _wait_for_file(target)
        assert written == TOKEN_A, f"the real write did not land: {written!r}"
        assert harness.provider.entered_hold.wait(timeout=30), (
            "the provider was not called again after the tool result; the write "
            "did not reach a resumable boundary"
        )
        run_row = wait_for_group_run(
            harness.handle.db_path, group_id, request=message, timeout=30
        )
        run_id = str(run_row["id"])
        before_calls = harness.provider.chat_calls
        before = harness.state(run_id)
        before_state = before.get("run_state") or {}
        before_effects = before.get("side_effects") or []
        before_usage = {
            key: int(before_state.get(key) or 0)
            for key in ("usage_tool_calls", "usage_tokens", "usage_provider_calls", "usage_cost_usd")
            if before_state
        }
        before_budget = before_state.get("budget_json")
        assert before_state.get("state") == "running", before_state
        assert before_usage.get("usage_tool_calls", 0) >= 1, before_usage
        assert len(before_effects) == 1, before_effects
        assert before_effects[0].get("status") in {"pending", "confirmed"}

        # Hard kill: no shutdown hook, no final persistence.
        stream.abort()
        harness.backend.stop(kill=True)
        with contextlib.suppress(Exception):
            stream.wait(timeout=5)
        after_kill = harness.state(run_id)
        assert (target.read_text(encoding="utf-8")) == TOKEN_A

        recovery_started = time.monotonic()
        harness.restart_backend()
        # Startup recovery must settle the run; it must not run the request a
        # second time against the provider.
        def settled() -> dict[str, Any] | None:
            row = latest_group_run(harness.handle.db_path, group_id)
            if row is None or str(row.get("id")) != run_id:
                return None
            if str(row.get("status")) in {
                "blocked",
                "interrupted",
                "failed",
                "completed",
                "cancelled",
            }:
                return row
            return None

        recovered = wait_for(settled, timeout=30, description="startup recovery")
        recovery_seconds = time.monotonic() - recovery_started
        time.sleep(0.5)
        after = harness.state(run_id)
        after_state = after.get("run_state") or {}
        after_effects = after.get("side_effects") or []

        problems: list[str] = []
        if str(recovered.get("status")) not in {"blocked", "interrupted", "failed", "completed"}:
            problems.append(f"run did not settle after restart: {recovered.get('status')!r}")
        if after_state.get("state") == "running":
            problems.append("run_state remained running after restart (no recovery)")
        if (target.read_text(encoding="utf-8")) != TOKEN_A:
            problems.append(
                "the workspace write was replayed after restart: " + target.read_text(encoding="utf-8")
            )
        if TOKEN_B in harness.provider.chat_prompts[-1] and harness.provider.chat_calls > before_calls:
            problems.append("a second write response was requested after restart")
        if len(after_effects) != 1:
            problems.append(f"effect ledger has {len(after_effects)} rows after restart")
        else:
            status = str(after_effects[0].get("status"))
            if status not in {"pending", "confirmed"}:
                problems.append(f"unexpected effect ledger status: {status!r}")
            if status == "pending" and str(after_state.get("state")) not in {"paused"}:
                problems.append(
                    "a pending (unknown) effect did not park the run for reconciliation: "
                    f"state={after_state.get('state')!r}"
                )
        if after_state.get("budget_json") != before_budget:
            problems.append("the accumulated budget was changed by the restart")
        for key, value in before_usage.items():
            if int(after_state.get(key) or 0) < value:
                problems.append(f"usage counter {key} was reset ({value} -> {after_state.get(key)})")
        messages = group_messages(harness.handle.db_path, group_id)
        if len([m for m in messages if m.get("role") == "user"]) != 1:
            problems.append("the user message was duplicated after the restart")
        if len([m for m in messages if m.get("role") == "assistant"]) > 1:
            problems.append("the assistant answer was duplicated after the restart")
        if after_state.get("state") == "completed" and not [m for m in messages if m.get("role") == "assistant"]:
            problems.append("the run claims completed without a persisted answer")

        harness.write_evidence(
            "kill-after-write",
            {
                "run_id": run_id,
                "before_state": before_state,
                "after_kill_state": (after_kill.get("run_state") or {}),
                "after_restart_state": after_state,
                "effects_before": before_effects,
                "effects_after": after_effects,
                "workspace_content": target.read_text(encoding="utf-8"),
                "provider_calls_before": before_calls,
                "provider_calls_after": harness.provider.chat_calls,
                "recovery_seconds": round(recovery_seconds, 3),
                "messages": messages,
                "problems": problems,
            },
        )
        if problems:
            pytest.fail(
                "kill/restart scenario failed:\n- " + "\n- ".join(dict.fromkeys(problems))
            )


def test_cancel_stops_the_provider_and_releases_the_group(tmp_path: Path) -> None:
    with GroupHarness(tmp_path / "cancel") as harness:
        harness.register_project()
        seeded = harness.seed(bot_names=["Lento", "Rápido"], group_name="Cancel E2E")
        group_id = seeded["group"]["id"]
        harness.provider.block_on(0)
        harness.provider.load(["Resposta de controlo."])

        message = "Faz uma análise longa."
        stream = harness.background_send(
            group_id, message, project_path=str(harness.handle.workspace)
        )
        assert harness.provider.entered_hold.wait(timeout=30), (
            "the scripted provider never entered the in-flight call"
        )
        run_row = wait_for_group_run(
            harness.handle.db_path, group_id, request=message, timeout=30
        )
        run_id = str(run_row["id"])

        # Give the streaming task a moment to register itself in the cancel map,
        # then stop it through the same endpoint the UI uses.
        time.sleep(0.2)
        cancelled = harness.client.post(f"/api/bot-groups/{group_id}/runs/{run_id}/cancel")
        assert cancelled.status_code == 202, cancelled.text
        payload = cancelled.json()
        assert payload.get("cancelled") is True, payload
        assert payload.get("status") in {"cancelling", "cancelled"}, payload

        stream.wait(timeout=20)
        harness.provider.release()
        time.sleep(0.2)

        def cancelled_row() -> dict[str, Any] | None:
            row = latest_group_run(harness.handle.db_path, group_id)
            if row is None or str(row.get("id")) != run_id:
                return None
            return row if str(row.get("status")) in {"cancelled", "interrupted", "failed"} else None

        final_row = wait_for(cancelled_row, timeout=20, description="cancelled run state")
        state = harness.state(run_id)
        run_state = state.get("run_state") or {}
        messages = group_messages(harness.handle.db_path, group_id)
        problems: list[str] = []
        if final_row.get("status") != "cancelled":
            problems.append(f"run projection is {final_row.get('status')!r}, expected cancelled")
        if run_state.get("state") != "cancelled":
            problems.append(f"run_state.state={run_state.get('state')!r}, expected cancelled")
        if "cancel" not in str(run_state.get("stop_reason") or "").lower():
            problems.append(f"stop_reason does not explain the cancellation: {run_state.get('stop_reason')!r}")
        if [m for m in messages if m.get("role") == "assistant"]:
            problems.append("a cancelled run persisted a completed assistant answer")
        if any("provider_result" in json.dumps(m) for m in messages):
            problems.append("a cancelled run claims a remote provider result")
        frames = stream.frames + (stream.result.frames if stream.result else [])
        done = [f for f in frames if str(f.get("type")) == "done"]
        if done and str(done[-1].get("status")) == "completed":
            problems.append("the cancelled stream ended with a completed frame")
        # An avorted SSE connection is allowed to end without a ``done`` frame;
        # what matters is that no frame claims completion and the durable state
        # is cancelled. The UI treats the abort as a stop request.

        # Resources must be released: the same group accepts a new execution.
        harness.provider.release()
        follow = harness.send(
            group_id,
            "Diz apenas OK.",
            project_path=str(harness.handle.workspace),
            timeout=60.0,
        )
        if follow.status_code != 200:
            problems.append(f"the group did not accept a new run after cancel: HTTP {follow.status_code}")
        else:
            follow_ids = follow.run_ids
            if follow_ids:
                follow_row = wait_for(
                    lambda: latest_group_run(harness.handle.db_path, group_id),
                    timeout=20,
                    description="new run row",
                )
                if follow_row.get("status") not in {"completed", "failed", "interrupted"}:
                    wait_for(
                        lambda: (
                            latest_group_run(harness.handle.db_path, group_id)
                            if latest_group_run(harness.handle.db_path, group_id).get("status")
                            in {"completed", "failed", "interrupted"}
                            else None
                        ),
                        timeout=30,
                        description="follow-up run terminal",
                    )

        harness.write_evidence(
            "cancel",
            {
                "run_id": run_id,
                "cancel_response": payload,
                "run_state": run_state,
                "messages": messages,
                "frames": frames[-20:],
                "provider_calls": harness.provider.chat_calls,
                "provider_snapshot": harness.provider.snapshot(),
                "follow_up_status": follow.status_code,
                "problems": problems,
            },
        )
        if problems:
            pytest.fail("cancel scenario failed:\n- " + "\n- ".join(dict.fromkeys(problems)))
