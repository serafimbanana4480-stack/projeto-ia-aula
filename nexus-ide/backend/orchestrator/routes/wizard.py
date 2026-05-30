"""Project Wizard API — interactive project creation from scratch."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    if template_id not in TEMPLATES:
        raise HTTPException(status_code=404, detail="Template not found")
    template = TEMPLATES[template_id]
    return {
        "id": template_id,
        "name": template["name"],
        "description": template["description"],
        "tags": template.get("tags", []),
        "files": list(template.get("files", {}).keys()),
        "setup_commands": template.get("setup_commands", []),
    }


@router.post("/wizard/start")
async def wizard_start(req: WizardStartRequest) -> dict[str, Any]:
    """Start a wizard session. Analyzes objective and returns questions."""
    import uuid

    session_id = f"wizard_{uuid.uuid4().hex[:12]}"

    # Analyze objective to determine template and questions
    objective_lower = req.objective.lower()

    # Simple template detection
    template_id = "python"  # default
    if any(k in objective_lower for k in ["web", "nextjs", "next.js", "react", "frontend"]):
        template_id = "fullstack_next_fastapi"
    elif any(k in objective_lower for k in ["api", "fastapi", "backend", "rest"]):
        template_id = "fastapi"
    elif any(k in objective_lower for k in ["mobile", "flutter", "app"]):
        template_id = "mobile_flutter"
    elif any(k in objective_lower for k in ["cli", "command line", "terminal"]):
        template_id = "cli_python"
    elif any(k in objective_lower for k in ["data", "jupyter", "ml", "machine learning"]):
        template_id = "data_science"
    elif any(k in objective_lower for k in ["microservice", "docker", "kong"]):
        template_id = "microservices"
    elif any(k in objective_lower for k in ["chrome", "extension", "browser"]):
        template_id = "chrome_extension"
    elif any(k in objective_lower for k in ["vscode", "extension"]):
        template_id = "vscode_extension"
    elif any(k in objective_lower for k in ["discord", "bot"]):
        template_id = "discord_bot"

    template = TEMPLATES.get(template_id, TEMPLATES["python"])

    questions = [
        {
            "id": "project_name",
            "question": "What is the project name?",
            "type": "text",
            "required": True,
        },
        {
            "id": "description",
            "question": "Brief project description?",
            "type": "text",
            "required": False,
        },
        {
            "id": "template",
            "question": "Which template to use?",
            "type": "select",
            "options": list(TEMPLATES.keys()),
            "default": template_id,
            "required": True,
        },
    ]

    _wizard_sessions[session_id] = {
        "session_id": session_id,
        "objective": req.objective,
        "questions": questions,
        "answers": {},
        "status": "asking",
        "progress": 20,
    }

    return {
        "session_id": session_id,
        "status": "asking",
        "questions": questions,
        "recommended_template": template_id,
        "progress": 20,
    }


@router.post("/wizard/answer")
async def wizard_answer(req: WizardAnswerRequest) -> dict[str, Any]:
    """Answer wizard questions."""
    session = _wizard_sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    session["answers"].update(req.answers)

    # Check if all required questions answered
    required = {q["id"] for q in session["questions"] if q.get("required", False)}
    answered = set(session["answers"].keys())

    if required.issubset(answered):
        session["status"] = "ready"
        session["progress"] = 80
        return {
            "session_id": req.session_id,
            "status": "ready",
            "answers": session["answers"],
            "progress": 80,
            "message": "All questions answered. Ready to generate project.",
        }

    # Return remaining questions
    remaining = [q for q in session["questions"] if q["id"] not in answered]
    return {
        "session_id": req.session_id,
        "status": "asking",
        "questions": remaining,
        "progress": 20 + int(60 * len(answered) / max(1, len(session["questions"]))),
    }


@router.post("/wizard/generate")
async def wizard_generate(req: WizardGenerateRequest) -> dict[str, Any]:
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
