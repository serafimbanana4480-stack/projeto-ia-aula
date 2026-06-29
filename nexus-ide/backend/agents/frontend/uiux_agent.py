"""UIUXAgent — UI/UX design and review specialist."""
from __future__ import annotations

from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest


class UIUXAgent(AgentBase):
    """Specialist agent for UI/UX design and accessibility review."""

    name = "UIUX"
    model_key = "pro"
    prompt_file = "uiux_system"
    supported_actions = set()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        yield f"<event>uiux_start|{request.query[:50]}</event>"

        query = request.query.lower()
        if "review" in query:
            yield "## UI/UX Review\n\n"
            yield "### Accessibility\n- Check color contrast ratios\n- Verify keyboard navigation\n- Test screen reader compatibility\n\n"
            yield "### Usability\n- Consistent navigation patterns\n- Clear call-to-action visibility\n- Responsive breakpoints verified\n\n"
        elif "design" in query:
            yield "## Design Proposal\n\n"
            yield "### Color Palette\n- Primary: #3B82F6 (blue)\n- Secondary: #10B981 (green)\n- Accent: #F59E0B (amber)\n\n"
            yield "### Typography\n- Headings: Inter, 600 weight\n- Body: Inter, 400 weight\n\n"
            yield "### Layout Grid\n- 12-column responsive grid\n- Max content width: 1280px\n\n"
        else:
            yield "UI/UX Agent ready. Ask for design proposals or code reviews.\n"

        yield "<event>uiux_end</event>"

    def review_component(self, component_code: str) -> dict[str, Any]:
        """Review a React component for UI/UX best practices."""
        issues = []
        if "aria-" not in component_code:
            issues.append("Missing ARIA attributes for accessibility")
        if "className=" not in component_code:
            issues.append("Consider using Tailwind classes for styling")
        return {
            "score": max(0, 100 - len(issues) * 20),
            "issues": issues,
            "passed": len(issues) == 0,
        }
