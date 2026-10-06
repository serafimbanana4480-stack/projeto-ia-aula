"""Test generation and execution API routes.

``POST /api/tests/run`` executes pytest inside a directory on disk, which is an
arbitrary-code-execution primitive (pytest imports ``conftest.py`` and collects
test modules).  The endpoint is therefore **admin only** and the work happens
off the event loop so a long run cannot wedge uvicorn.  Containment, the
dependency allow-list and every subprocess timeout live in
:mod:`backend.pipeline.test_generator`.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.middleware.auth import require_admin
from backend.pipeline.test_generator import (
    TestGenerator,
    TestRunner,
    TestRunSecurityError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class GenerateTestsRequest(BaseModel):
    module_name: str
    source_code: str
    requirements: list[str] | None = None


class GenerateTestsResponse(BaseModel):
    test_files: list[dict[str, str]]
    generated_by: str = "llm"


class RunTestsRequest(BaseModel):
    project_path: str
    extra_deps: list[str] | None = None


@router.post("/tests/generate", response_model=GenerateTestsResponse)
async def generate_tests(req: GenerateTestsRequest, request: Request) -> dict[str, Any]:
    """Generate pytest unit tests from source code."""
    try:
        ollama = request.app.state.ollama
        generator = TestGenerator(ollama_client=ollama)
        test_files = await generator.generate_with_llm(
            module_name=req.module_name,
            source_code=req.source_code,
            requirements=req.requirements or [],
        )
        return {"test_files": test_files, "generated_by": "llm"}
    except Exception as exc:
        logger.error("Test generation failed: %s", exc)
        # Fallback to stub generation
        try:
            generator = TestGenerator()
            functions = generator.discover_functions(req.source_code)
            stub = generator.generate_stub(req.module_name, functions)
            return {
                "test_files": [{
                    "path": f"tests/test_{req.module_name.replace('.', '_')}.py",
                    "content": stub,
                    "target_module": req.module_name,
                }],
                "generated_by": "stub",
            }
        except Exception:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/tests/run", dependencies=[Depends(require_admin)])
async def run_tests(
    req: RunTestsRequest,
    request: Request,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Run pytest in a project directory (admin only).

    Guards applied before any subprocess starts:

    * ``Depends(require_admin)`` — DB-backed admin role, no hard-coded fallback.
    * ``project_path`` must resolve inside an allow-listed root (traversal and
      symlink escapes are rejected by :func:`resolve_contained_path`).
    * ``extra_deps`` entries must be exact ``name[extras]==version`` pins from a
      name allow-list.
    * ``requirements.txt`` is never auto-installed unless the operator opted in
      via ``NEXUS_TEST_RUN_INSTALL_REQUIREMENTS``.
    * the pytest process runs in a worker thread with a mandatory timeout, so
      the event loop is never blocked and a hung run is killed.

    The response shape is unchanged.
    """
    from pathlib import Path

    runner = TestRunner()
    try:
        report = await asyncio.to_thread(
            runner.run, Path(req.project_path), req.extra_deps
        )
    except TestRunSecurityError as exc:
        logger.warning("Rejected test run for %r: %s", req.project_path, exc)
        raise HTTPException(
            status_code=400,
            detail={"error": exc.code, "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Test run failed for %r", req.project_path)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "skipped": report.skipped,
        "duration": report.duration,
        "success_rate": report.success_rate,
        "summary": report.summary,
        "failures": [
            {
                "test_name": f.test_name,
                "status": f.status,
                "failure_type": f.failure_type.value,
                "error_message": f.error_message,
            }
            for f in report.failures()
        ],
    }
