"""Tool discovery — formatted overviews for the LLM system prompt.

Builds a compact, LLM-friendly text block listing the available tools, when
to use them, examples, and risk level. Used by ``AgentBase`` to inject a
"what can I do" section into the system prompt so the LLM knows what tools
it can call without having to discover them at runtime.

Typical usage:
    from backend.tools.discovery import build_tool_overview

    system_prompt = base_prompt + build_tool_overview(agent_name="CODER")
"""

from __future__ import annotations

import logging

from backend.tools.registry import (
    ToolSpec,
    get_tool_descriptions_for_llm,
    get_tools_for_agent,
    list_tools_by_category,
)

logger = logging.getLogger(__name__)


def build_tool_overview(
    agent_name: str | None = None,
    max_tools: int | None = None,
    include_examples: bool = True,
    include_risk: bool = True,
) -> str:
    """Build a tool overview section for the system prompt.

    Args:
        agent_name: If provided, filter to tools relevant to the agent.
        max_tools: Optional cap on the number of tools listed.
        include_examples: Include 1 example invocation per tool.
        include_risk: Include risk-level annotations.

    Returns:
        A formatted text block. Empty string if no tools are available.
    """
    return get_tool_descriptions_for_llm(
        agent_name=agent_name,
        include_examples=include_examples,
        include_risk=include_risk,
        max_tools=max_tools,
    )


def build_compact_tool_list(
    agent_name: str | None = None,
    max_chars: int = 2000,
) -> str:
    """Build a compact (token-light) tool list for smaller-context models.

    Each tool gets a single line: `- name: short description`. Tools are
    filtered by agent relevance and truncated to fit within ``max_chars``.
    """
    tools = get_tools_for_agent(agent_name) if agent_name else None
    if tools is None:
        from backend.tools.registry import list_tools
        tools = list_tools()
    lines: list[str] = ["Tools: "]
    for tool in tools:
        line = f"- {tool.name}: {tool.description}"
        if len("\n".join(lines)) + len(line) + 1 > max_chars:
            lines.append(f"  ... and {len(tools) - tools.index(tool)} more")
            break
        lines.append(line)
    return "\n".join(lines)


def build_tool_section_markdown(
    agent_name: str | None = None,
) -> str:
    """Build a Markdown-formatted tool section for prompts that support it.

    Grouped by category, with examples and risk levels.
    """
    tools = get_tools_for_agent(agent_name) if agent_name else None
    if tools is None:
        from backend.tools.registry import list_tools
        tools = list_tools()
    by_cat = list_tools_by_category()
    # Filter to only tools in our filtered list
    allowed = {t.name for t in tools}
    sections: list[str] = ["# Tool Reference", ""]
    for cat, cat_tools in by_cat.items():
        relevant = [t for t in cat_tools if t.name in allowed]
        if not relevant:
            continue
        sections.append(f"## {cat.title()}")
        sections.append("")
        for t in relevant:
            sections.append(_format_tool_markdown(t))
    return "\n".join(sections)


def _format_tool_markdown(tool: ToolSpec) -> str:
    """Format a single tool as Markdown."""
    lines: list[str] = [f"### `{tool.name}`"]
    lines.append("")
    lines.append(tool.description)
    if tool.when_to_use:
        lines.append("")
        lines.append(f"**When to use:** {tool.when_to_use}")
    if tool.risk_level and tool.risk_level != "low":
        lines.append("")
        lines.append(f"**Risk level:** {tool.risk_level}")
    if tool.requires_confirmation:
        lines.append("")
        lines.append("**Requires user confirmation before execution.**")
    if tool.examples:
        lines.append("")
        lines.append("**Examples:**")
        lines.append("")
        for ex in tool.examples[:2]:
            args_str = ", ".join(f"{k}={v!r}" for k, v in ex.items())
            lines.append(f"- `{tool.name}({args_str})`")
    if tool.tags:
        lines.append("")
        lines.append(f"**Tags:** {', '.join(tool.tags)}")
    return "\n".join(lines)


def list_tools_by_capability(capability: str) -> list[ToolSpec]:
    """Return tools that match a high-level capability.

    Capabilities:
        - "file": read, write, list, search files
        - "git": git operations
        - "code": execute code, run tests
        - "web": search web, fetch URLs
        - "docker": docker operations
        - "db": database operations
        - "shell": run shell commands
        - "memory": store/recall memories
        - "agent": consult other agents
        - "notification": send notifications
        - "api": HTTP requests
        - "quality": lint, format, type-check
        - "scaffold": create project scaffolding
        - "docs": document generation
        - "data": data analysis, reports
    """
    cap_to_tags: dict[str, list[str]] = {
        "file": ["file", "fs", "io"],
        "git": ["git", "vcs"],
        "code": ["code", "exec", "test"],
        "web": ["web", "search", "fetch"],
        "docker": ["docker", "container"],
        "db": ["db", "database", "sql"],
        "shell": ["shell", "bash", "cmd"],
        "memory": ["memory", "recall", "context"],
        "agent": ["agent", "consult", "bus"],
        "notification": ["notification", "notify", "alert", "webhook", "email"],
        "api": ["api", "http", "request"],
        "quality": ["quality", "lint", "format", "type"],
        "scaffold": ["scaffold", "project", "template"],
        "docs": ["doc", "docs", "report"],
        "data": ["data", "analysis", "report"],
    }
    target_tags = cap_to_tags.get(capability.lower(), [])
    if not target_tags:
        return []
    from backend.tools.registry import list_tools
    matches: list[ToolSpec] = []
    for t in list_tools():
        for tag in t.tags:
            if tag.lower() in target_tags:
                matches.append(t)
                break
    return matches
