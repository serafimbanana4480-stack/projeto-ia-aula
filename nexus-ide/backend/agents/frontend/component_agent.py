"""ComponentAgent — React component generation specialist."""
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from backend.agents.base import AgentBase, AgentRequest


class ComponentAgent(AgentBase):
    """Specialist agent for generating React/Next.js components."""

    name = "COMPONENT"
    model_key = "pro"
    prompt_file = "component_system"
    supported_actions = set()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        yield f"<event>component_start|{request.query[:50]}</event>"

        query = request.query.lower()
        if "generate" in query or "create" in query:
            yield "## Component Generation\n\n"
            yield self._generate_component_template(request.query)
        elif "refactor" in query:
            yield "## Refactoring Suggestions\n\n"
            yield "- Extract reusable subcomponents\n"
            yield "- Use React.memo for pure components\n"
            yield "- Move logic to custom hooks\n"
        else:
            yield "Component Agent ready. Describe the component you need.\n"

        yield "<event>component_end</event>"

    def _generate_component_template(self, description: str) -> str:
        """Generate a basic Next.js component template."""
        # Extract component name from description (last capitalized word)
        words = description.split()
        name = "MyComponent"
        for w in reversed(words):
            clean = w.strip(".,!?;:")
            if clean and clean[0].isupper():
                name = clean
                break

        return f"""```tsx
// components/{name}.tsx
"use client";

import React from "react";

interface {name}Props {{
  // Define props here
}}

export function {name}(props: {name}Props) {{
  return (
    <div className="p-4 rounded-lg border bg-white dark:bg-gray-900">
      {{/* Implementation */}}
    </div>
  );
}}
```
"""

    def analyze_component(self, code: str) -> dict[str, Any]:
        """Analyze a component for quality metrics."""
        lines = code.split("\n")
        has_types = "interface " in code or "type " in code
        has_tests = "test" in code.lower()
        hooks = re.findall(r"use[A-Z]\\w+", code)

        return {
            "lines": len(lines),
            "has_types": has_types,
            "has_tests": has_tests,
            "hooks_used": list(set(hooks)),
            "recommendations": [
                "Add prop types" if not has_types else None,
                "Add unit tests" if not has_tests else None,
            ],
        }
