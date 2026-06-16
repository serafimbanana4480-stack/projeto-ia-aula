"""Nexus IDE Reliability Audit — direct tool execution with independent FS verification."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, UTC
from pathlib import Path

os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path.cwd()))

AUDIT_SESSION_ID = "reliability-audit"


def verify_file(path: Path, expected: str | None = None) -> dict:
    exists = path.exists()
    result = {"exists": exists, "path": str(path)}
    if exists and path.is_file():
        try:
            content = path.read_text(encoding="utf-8")
            result["content"] = content
            result["size"] = len(content)
            if expected is not None:
                result["content_match"] = content == expected
        except Exception as e:
            result["read_error"] = str(e)
    return result


async def main() -> None:
    from backend.tools.registry import execute_tool, list_tools

    report: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tools": {},
        "file_ops": [],
        "schema_issues": [],
        "metrics": {},
        "scores": {},
    }

    # ── 1. Tool inventory + schema validation ──────────────────────────
    tools = list_tools()

    for spec in sorted(tools, key=lambda t: t.name):
        schema = spec.schema or {}
        issues = []
        if not schema:
            issues.append("empty_schema")
        elif schema.get("type") != "object":
            issues.append(f"type_not_object:{schema.get('type')}")
        if not spec.handler:
            issues.append("no_handler")
        if not spec.description:
            issues.append("no_description")
        report["tools"][spec.name] = {
            "enabled": spec.enabled,
            "has_handler": spec.handler is not None,
            "schema_type": schema.get("type"),
            "required": schema.get("required", []),
            "properties": list((schema.get("properties") or {}).keys()),
            "issues": issues,
        }
        if issues:
            report["schema_issues"].append({"tool": spec.name, "issues": issues})

    # ── 2. Writable tool tests with independent verification ───────────
    audit_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "tmp" / "nexus_reliability_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    test_cases = [
        {
            "id": "CREATE",
            "tool": "write_file_absolute",
            "args": {"path": str(audit_dir / "create_test.txt"), "content": "AUDIT_CREATE_MARKER"},
            "verify_path": audit_dir / "create_test.txt",
            "expected": "AUDIT_CREATE_MARKER",
        },
        {
            "id": "EDIT",
            "tool": "write_file_absolute",
            "args": {"path": str(audit_dir / "create_test.txt"), "content": "AUDIT_EDIT_MARKER"},
            "verify_path": audit_dir / "create_test.txt",
            "expected": "AUDIT_EDIT_MARKER",
        },
        {
            "id": "NESTED_CREATE",
            "tool": "write_file_absolute",
            "args": {
                "path": str(audit_dir / "sub" / "nested" / "deep.txt"),
                "content": "NESTED_MARKER",
            },
            "verify_path": audit_dir / "sub" / "nested" / "deep.txt",
            "expected": "NESTED_MARKER",
        },
        {
            "id": "POSIX_TMP",
            "tool": "write_file_absolute",
            "args": {"path": "/tmp/nexus_reliability_audit/posix_test.txt", "content": "POSIX_TMP_MARKER"},
            "verify_path": Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "tmp" / "nexus_reliability_audit" / "posix_test.txt",
            "expected": "POSIX_TMP_MARKER",
        },
        {
            "id": "RELATIVE_WRITE",
            "tool": "write_file",
            "args": {
                "path": "audit_relative.txt",
                "content": "RELATIVE_MARKER",
                "project_path": str(audit_dir),
            },
            "verify_path": audit_dir / "audit_relative.txt",
            "expected": "RELATIVE_MARKER",
        },
    ]

    for tc in test_cases:
        tool_result = await execute_tool(tc["tool"], AUDIT_SESSION_ID, tc["args"])
        inner = tool_result.get("result") or tool_result
        tool_ok = "error" not in tool_result and "error" not in (inner if isinstance(inner, dict) else {})
        tool_written = isinstance(inner, dict) and inner.get("written", inner.get("verified", "error" not in inner))

        fs_verify = verify_file(tc["verify_path"], tc["expected"])
        fs_ok = fs_verify.get("exists") and fs_verify.get("content_match", False)

        # Re-read after 100ms to test persistence
        await asyncio.sleep(0.1)
        fs_reread = verify_file(tc["verify_path"], tc["expected"])
        persist_ok = fs_reread.get("exists") and fs_reread.get("content_match", False)

        # Directory listing check
        parent = tc["verify_path"].parent
        dir_list = list(parent.iterdir()) if parent.exists() else []
        in_dir = tc["verify_path"].name in [p.name for p in dir_list]

        op_report = {
            "id": tc["id"],
            "requested_path": tc["args"].get("path"),
            "resolved_path_tool": inner.get("path") if isinstance(inner, dict) else None,
            "actual_written_path": str(tc["verify_path"]) if fs_verify.get("exists") else None,
            "tool_reported_success": tool_ok and bool(tool_written),
            "fs_exists": fs_verify.get("exists"),
            "content_match": fs_verify.get("content_match"),
            "persist_after_reread": persist_ok,
            "in_directory_listing": in_dir,
            "verification_pass": fs_ok and persist_ok and in_dir,
            "false_success": (tool_ok and bool(tool_written)) and not fs_ok,
            "tool_result": tool_result,
        }
        report["file_ops"].append(op_report)

    # Delete test
    delete_path = audit_dir / "create_test.txt"
    delete_result = await execute_tool(
        "delete_file_absolute",
        AUDIT_SESSION_ID,
        {"path": str(delete_path)},
    )
    delete_inner = delete_result.get("result") or delete_result
    delete_tool_ok = "error" not in delete_result and "error" not in (delete_inner if isinstance(delete_inner, dict) else {})
    delete_fs_ok = not delete_path.exists()
    report["file_ops"].append({
        "id": "DELETE",
        "requested_path": str(delete_path),
        "tool_reported_success": delete_tool_ok,
        "fs_exists_after": delete_path.exists(),
        "verification_pass": delete_fs_ok,
        "false_success": delete_tool_ok and not delete_fs_ok,
        "tool_result": delete_result,
    })

    # Rename test (unique names to avoid collisions across runs)
    rename_stamp = int(time.time() * 1000)
    rename_src = audit_dir / f"rename_src_{rename_stamp}.txt"
    rename_dst = audit_dir / f"rename_dst_{rename_stamp}.txt"
    await execute_tool("write_file_absolute", AUDIT_SESSION_ID, {"path": str(rename_src), "content": "RENAME_MARKER"})
    # Nexus has no rename_file_absolute tool; use move_file_absolute if registered
    rename_tool = "move_file_absolute"
    from backend.tools.registry import get_tool
    if not get_tool(rename_tool):
        rename_tool = "move_file"
    rename_result = await execute_tool(
        rename_tool,
        AUDIT_SESSION_ID,
        {"src": str(rename_src), "dest": str(rename_dst)}
        if rename_tool == "move_file_absolute"
        else {"src": str(rename_src), "dest": str(rename_dst), "project_path": str(audit_dir)},
    )
    rename_inner = rename_result.get("result") or rename_result
    rename_tool_ok = "error" not in rename_result
    rename_fs_ok = not rename_src.exists() and rename_dst.exists()
    rename_content_ok = verify_file(rename_dst, "RENAME_MARKER").get("content_match", False)
    report["file_ops"].append({
        "id": "RENAME",
        "requested_path": f"{rename_src} -> {rename_dst}",
        "tool_reported_success": rename_tool_ok,
        "verification_pass": rename_fs_ok and rename_content_ok,
        "false_success": rename_tool_ok and not (rename_fs_ok and rename_content_ok),
        "tool_result": rename_result,
    })

    # ── 4. Metrics endpoint probe ──────────────────────────────────────
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            for endpoint in [
                "/api/metrics/current",
                "/api/dashboard/status",
                "/api/dashboard/stream",
            ]:
                try:
                    resp = await client.get(f"http://localhost:8000{endpoint}", timeout=3.0)
                    report["metrics"][endpoint] = {
                        "status": resp.status_code,
                        "available": resp.status_code == 200,
                        "content_type": resp.headers.get("content-type"),
                    }
                except Exception as e:
                    report["metrics"][endpoint] = {"status": 0, "available": False, "error": str(e)}
    except ImportError:
        report["metrics"]["error"] = "httpx not available"

    # ── 5. Scores ──────────────────────────────────────────────────────
    file_pass = sum(1 for op in report["file_ops"] if op.get("verification_pass"))
    file_total = len(report["file_ops"])
    schema_ok = sum(1 for t in report["tools"].values() if not t["issues"])
    tool_total = len(report["tools"])

    false_successes = [op for op in report["file_ops"] if op.get("false_success")]

    report["scores"] = {
        "tool_schema_score": round(schema_ok / tool_total * 100, 1) if tool_total else 0,
        "file_modification_score": round(file_pass / file_total * 100, 1) if file_total else 0,
        "false_success_count": len(false_successes),
        "tool_count": tool_total,
    }

    out_path = Path(__file__).parent / "reliability_audit_results.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["scores"], indent=2))
    print(f"\nFalse successes: {len(false_successes)}")
    for op in report["file_ops"]:
        status = "PASS" if op.get("verification_pass") else "FAIL"
        fs_flag = " [FALSE SUCCESS]" if op.get("false_success") else ""
        print(f"  {op['id']}: {status}{fs_flag}")
    print(f"\nTools: {tool_total}, Schema issues: {len(report['schema_issues'])}")
    print(f"Results: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
