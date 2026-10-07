"""APIAgent — REST API design and endpoint generation specialist."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from backend.agents.base import AgentBase, AgentRequest

logger = logging.getLogger(__name__)


@dataclass
class APIReviewResult:
    """Structured result from an API code review."""

    passed: bool
    score: int
    auth_check: bool
    validation_check: bool
    error_handling_check: bool
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class APIAgent(AgentBase):
    """Specialist agent for REST API design, endpoint generation, and API review."""

    name = "API"
    model_key = "coder"
    prompt_file = "api_system"
    supported_actions = set()

    def __init__(self) -> None:
        super().__init__()
        self._stats: dict[str, int] = {
            "design_requests": 0,
            "endpoint_requests": 0,
            "review_requests": 0,
        }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Handle API-related queries: REST design, endpoint generation, API review."""
        yield f"<event>api_start|{request.query[:50]}</event>"

        query = request.query.lower()
        if any(k in query for k in ["design", "rest", "architecture", "spec"]):
            self._stats["design_requests"] += 1
            yield "## REST API Design\n\n"
            yield self._rest_design_guidelines()
        elif any(k in query for k in ["endpoint", "generate", "route", "path"]):
            self._stats["endpoint_requests"] += 1
            yield "## Endpoint Generation\n\n"
            yield self._generate_endpoint_template(request.query)
        elif any(k in query for k in ["review", "audit", "check"]):
            self._stats["review_requests"] += 1
            yield "## API Review\n\n"
            yield "Provide the API code you'd like reviewed as context.\n"
        else:
            yield "API Agent ready. Ask for:\n"
            yield "- REST API design guidelines\n"
            yield "- Endpoint generation\n"
            yield "- API code review\n"

        yield "<event>api_end</event>"

    def _rest_design_guidelines(self) -> str:
        """Return standard REST design guidelines."""
        return (
            "### Resource Naming\n"
            "- Use plural nouns: `/users`, `/orders`\n"
            "- Nested resources: `/users/{id}/orders`\n"
            "- Avoid verbs in paths; use HTTP methods instead\n\n"
            "### HTTP Methods\n"
            "- GET: read, POST: create, PUT/PATCH: update, DELETE: remove\n"
            "- Return 201 for created, 204 for no-content deletes\n\n"
            "### Versioning\n"
            "- URL path: `/api/v1/resource`\n"
            "- Header: `Accept: application/vnd.api+json;version=1`\n\n"
            "### Pagination & Filtering\n"
            "- `?page=1&limit=20`\n"
            "- `?sort=-created_at&filter[status]=active`\n"
        )

    def _generate_endpoint_template(self, description: str) -> str:
        """Generate a basic FastAPI-style endpoint template."""
        words = description.split()
        resource = "resource"
        for w in words:
            clean = w.strip(".,!?;:").lower()
            if clean and clean not in {"a", "an", "the", "for", "new", "create", "endpoint", "api"}:
                resource = clean
                break

        class_name = "".join(part.capitalize() for part in resource.split("_"))

        return f"""```python
# routers/{resource}.py
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

router = APIRouter(prefix="/{resource}s", tags=["{class_name}"])


class {class_name}Create(BaseModel):
    # TODO: define fields
    pass


class {class_name}Response(BaseModel):
    id: int
    # TODO: define fields
    pass


@router.post("/", response_model={class_name}Response, status_code=status.HTTP_201_CREATED)
async def create_{resource}(body: {class_name}Create):
    \"\"\"Create a new {resource}.\"\"\"
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/{{{resource}_id}}", response_model={class_name}Response)
async def get_{resource}({resource}_id: int):
    \"\"\"Retrieve a {resource} by ID.\"\"\"
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not implemented")
```
"""

    def review_api(self, code: str) -> APIReviewResult:
        """Review API code for auth, validation, and error handling.

        Args:
            code: Source code string of the API implementation.

        Returns:
            Structured review result with checks and suggestions.
        """
        issues: list[str] = []
        suggestions: list[str] = []

        auth_check = "Depends" in code or "auth" in code.lower() or "token" in code.lower() or "oauth" in code.lower()
        if not auth_check:
            issues.append("No authentication/authorization detected")
            suggestions.append("Add OAuth2 or API-key dependency injection (e.g., `Depends(get_current_user)`)")

        validation_check = "BaseModel" in code or "pydantic" in code.lower() or "validator" in code.lower() or "Field(" in code
        if not validation_check:
            issues.append("Input validation not detected")
            suggestions.append("Use Pydantic models for request validation")

        error_handling_check = "HTTPException" in code or "try:" in code or "except" in code
        if not error_handling_check:
            issues.append("Explicit error handling not detected")
            suggestions.append("Add try/except blocks and raise appropriate HTTPExceptions")

        score = max(0, 100 - len(issues) * 25)
        passed = len(issues) == 0

        logger.info("API review completed: score=%s passed=%s", score, passed)
        return APIReviewResult(
            passed=passed,
            score=score,
            auth_check=auth_check,
            validation_check=validation_check,
            error_handling_check=error_handling_check,
            issues=issues,
            suggestions=suggestions,
        )

    def stats(self) -> dict[str, Any]:
        """Return agent usage statistics."""
        return {
            "agent": self.name,
            **self._stats,
            "total_requests": sum(self._stats.values()),
        }
