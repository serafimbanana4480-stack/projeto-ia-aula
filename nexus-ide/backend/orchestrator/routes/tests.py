
"""Test generation and execution API routes."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


from backend.pipeline.test_generator import TestGenerator, TestRunner
from backend.tools.ollama_client import OllamaClient

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
            raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tests/run")
async def run_tests(req: RunTestsRequest, request: Request) -> dict[str, Any]:
    """Run pytest in a project directory."""
    from pathlib import Path
    runner = TestRunner()
    report = runner.run(Path(req.project_path), extra_deps=req.extra_deps)
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
