"""META_ANALYZER API routes.

Endpoints:
    POST /api/meta/analyze      — Run META_ANALYZER and stream SSE results.
    GET  /api/meta/evolution-log — Read the evolution log.
    GET  /api/meta/criteria      — Return quality criteria thresholds.
    POST /api/meta/approve       — Submit metrics for formal approval evaluation.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.agents.base import AgentRequest
from backend.middleware.auth import require_auth
from backend.models.api import StreamEvent

logger = logging.getLogger(__name__)
router = APIRouter()


def _sse(event: StreamEvent) -> str:
    """Serialise a StreamEvent as one SSE frame."""
    return f"data: {event.model_dump_json()}\n\n"


def _get_meta_analyzer(request: Request):
    """Resolve META_ANALYZER from the app registry."""
    registry = getattr(request.app.state, "registry", {})
    return registry.get("META_ANALYZER")


@router.post("/meta/analyze", dependencies=[Depends(require_auth)])
async def meta_analyze(request: Request) -> StreamingResponse:
    """Run META_ANALYZER on the current session state and stream results via SSE."""
    agent = _get_meta_analyzer(request)
    if not agent:
        raise HTTPException(status_code=503, detail="META_ANALYZER not registered")

    llm_client = request.app.state.llm_client
    session_id = request.query_params.get("session_id", "default")
    query = request.query_params.get(
        "query",
        "Synthesize all recent agent outputs, evaluate against quality criteria, and render a gatekeeper report.",
    )

    async def event_stream() -> AsyncIterator[str]:
        agent_req = AgentRequest(
            session_id=session_id,
            query=query,
            client=llm_client,
            max_iterations=7,
            enable_thinking=True,
        )
        yield _sse(StreamEvent(type="agent_started", agent="META_ANALYZER"))
        try:
            async for token in agent.run(agent_req):
                yield _sse(StreamEvent(type="token", agent="META_ANALYZER", content=token))
        except Exception as exc:
            logger.exception("META_ANALYZER execution failed: %s", exc)
            yield _sse(StreamEvent(type="error", content=f"Meta-analysis failed: {exc}"))
        yield _sse(StreamEvent(type="agent_finished", agent="META_ANALYZER"))
        yield _sse(StreamEvent(type="done"))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/meta/evolution-log", dependencies=[Depends(require_auth)])
async def meta_evolution_log(request: Request) -> dict[str, Any]:
    """Return the contents of the evolution log."""
    from backend.agents.meta_analyzer import EVOLUTION_LOG_PATH

    if not EVOLUTION_LOG_PATH.exists():
        return {"content": "", "exists": False}
    return {
        "content": EVOLUTION_LOG_PATH.read_text(encoding="utf-8"),
        "exists": True,
    }


@router.get("/meta/criteria", dependencies=[Depends(require_auth)])
async def meta_criteria(request: Request) -> dict[str, Any]:
    """Return the current quality criteria thresholds."""
    from backend.agents.meta_analyzer import QualityCriteria

    return {
        "tests": {
            "coverage_min_percent": QualityCriteria.TEST_COVERAGE_MIN,
            "failures_max": QualityCriteria.TEST_FAILURES_MAX,
        },
        "security": {
            "critical_max": QualityCriteria.SECURITY_CRITICAL_MAX,
            "high_max": QualityCriteria.SECURITY_HIGH_MAX,
        },
        "performance": {
            "regression_max_percent": QualityCriteria.PERFORMANCE_REGRESSION_PCT,
        },
        "complexity": {
            "cyclomatic_max_function": QualityCriteria.CYCLOMATIC_MAX_FUNCTION,
            "cyclomatic_max_file": QualityCriteria.CYCLOMATIC_MAX_FILE,
        },
        "style": {
            "lint_errors_max": QualityCriteria.LINT_ERRORS_MAX,
        },
        "documentation": {
            "docstring_required_public": QualityCriteria.DOCSTRING_REQUIRED_PUBLIC,
        },
    }


@router.post("/meta/approve", dependencies=[Depends(require_auth)])
async def meta_approve(request: Request) -> dict[str, Any]:
    """Submit metrics for a formal META_ANALYZER approval evaluation.

    Expects JSON body with at least:
        { "metrics": { ... } }

    Optional fields:
        "recommendations": ["..."],
        "log_decision": true,
        "decision_name": "...",
        "rationale": "...",
        "agents_involved": ["..."]
    """
    agent = _get_meta_analyzer(request)
    if not agent:
        raise HTTPException(status_code=503, detail="META_ANALYZER not registered")

    try:
        body = await request.json()
    except Exception:
        body = {}

    metrics = body.get("metrics", {})
    verdict = agent.evaluate_quality(metrics)
    report = agent.build_approval_report(verdict, [], body.get("recommendations", []))

    if body.get("log_decision"):
        agent.log_evolution_entry(
            decision=body.get("decision_name", "Manual approval request"),
            rationale=body.get("rationale", "Submitted via API"),
            agents_involved=body.get("agents_involved", []),
            quality_verdict=verdict,
        )

    return {
        "verdict": verdict,
        "report": report,
    }
