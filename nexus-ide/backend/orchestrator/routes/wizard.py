"""Project Wizard API — interactive project creation from scratch."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.middleware.auth import require_auth
from backend.tools.advanced_templates import TEMPLATES, generate_project

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory session store (in production, use Redis)
_wizard_sessions: dict[str, dict[str, Any]] = {}


class WizardStartRequest(BaseModel):
    objective: str


class WizardAnswerRequest(BaseModel):
    session_id: str
    answers: dict[str, Any]


class WizardGenerateRequest(BaseModel):
    session_id: str
    project_path: str = "."


@router.get("/wizard/templates")
async def list_templates() -> dict[str, Any]:
    """List all available project templates."""
    return {
        "templates": [
            {
                "id": key,
                "name": template["name"],
                "description": template["description"],
                "tags": template.get("tags", []),
                "files_count": len(template.get("files", {})),
            }
            for key, template in TEMPLATES.items()
        ]
    }


@router.get("/wizard/templates/{template_id}")
async def get_template(template_id: str) -> dict[str, Any]:
    """Get details of a specific template."""
    template = TEMPLATES.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "id": template_id,
        **template,
    }


@router.post("/wizard/start")
async def wizard_start(req: WizardStartRequest) -> dict[str, Any]:
    """Start a new wizard session with a set of questions."""
    import uuid

    session_id = str(uuid.uuid4())

    # Simple heuristic: choose template based on objective keywords
    objective_lower = req.objective.lower()
    if "web" in objective_lower or "site" in objective_lower or "app" in objective_lower:
        template_id = "nextjs"
    elif "api" in objective_lower or "backend" in objective_lower or "fastapi" in objective_lower:
        template_id = "python_api"
    elif "ml" in objective_lower or "model" in objective_lower or "ai" in objective_lower:
        template_id = "python_ml"
    else:
        template_id = "python"

    template = TEMPLATES.get(template_id, TEMPLATES["python"])

    _wizard_sessions[session_id] = {
        "status": "started",
        "progress": 0,
        "template": template_id,
        "questions": template.get("questions", []),
        "answers": {},
        "objective": req.objective,
    }

    return {
        "session_id": session_id,
        "status": "started",
        "template": template_id,
        "questions": template.get("questions", []),
    }


@router.post("/wizard/answer")
async def wizard_answer(req: WizardAnswerRequest) -> dict[str, Any]:
    """Submit answers for the current wizard session."""
    session = _wizard_sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    if session["status"] == "done":
        raise HTTPException(status_code=400, detail="Wizard already completed")

    # Merge answers
    session["answers"].update(req.answers)

    # Check if all required questions are answered
    answered = session["answers"]
    questions = session.get("questions", [])
    required = [q["id"] for q in questions if q.get("required", True)]
    missing = [q for q in required if q not in answered]

    if not missing:
        session["status"] = "ready"
        session["progress"] = 100
    else:
        session["progress"] = int(100 * len(answered) / max(1, len(required)))

    return {
        "session_id": req.session_id,
        "status": session["status"],
        "progress": session["progress"],
        "missing": missing,
    }


@router.post("/wizard/generate")
async def wizard_generate(
    req: WizardGenerateRequest,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Generate complete project based on wizard answers."""
    session = _wizard_sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    if session["status"] != "ready":
        raise HTTPException(status_code=400, detail="Wizard not ready. Answer all questions first.")

    answers = session["answers"]
    template_id = answers.get("template", "python")
    project_name = answers.get("project_name", "my-project")
    description = answers.get("description", f"{project_name} project")

    try:
        result = await generate_project(
            template_id=template_id,
            name=project_name,
            description=description,
            project_path=req.project_path,
        )

        session["status"] = "done"
        session["progress"] = 100
        session["result"] = result

        return {
            "session_id": req.session_id,
            "status": "done",
            "progress": 100,
            **result,
        }
    except Exception as exc:
        logger.exception("Project generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")


@router.get("/wizard/status/{session_id}")
async def wizard_status(session_id: str) -> dict[str, Any]:
    """Get wizard session status."""
    session = _wizard_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")
    return {
        "session_id": session_id,
        "status": session["status"],
        "progress": session["progress"],
        "answers": session.get("answers", {}),
    }
