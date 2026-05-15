"""Report generation tool — create professional reports from data and analysis.

Generates reports in multiple formats:
- Markdown reports with structured sections
- HTML reports with styling
- Plain text summaries
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


async def generate_report(
    title: str = "Report",
    sections: str = "[]",
    format: str = "markdown",
    output_path: str = "",
    project_path: str = ".",
) -> dict:
    """Generate a structured report from sections.

    Args:
        title: Report title
        sections: JSON array of section objects with "heading" and "content" keys
        format: Output format - "markdown", "html", or "text"
        output_path: File path to save the report (relative to project root)
        project_path: Project root path
    """
    try:
        # Parse sections
        if isinstance(sections, str):
            try:
                parsed_sections = json.loads(sections)
            except json.JSONDecodeError:
                # Treat as plain text content
                parsed_sections = [{"heading": "Content", "content": sections}]
        elif isinstance(sections, list):
            parsed_sections = sections
        else:
            parsed_sections = [{"heading": "Content", "content": str(sections)}]

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        if format == "html":
            report = _generate_html(title, parsed_sections, now)
        elif format == "text":
            report = _generate_text(title, parsed_sections, now)
        else:
            report = _generate_markdown(title, parsed_sections, now)

        # Save to file if output_path specified
        saved_path = ""
        if output_path:
            # Validate path is within project root (sandbox)
            project = Path(project_path).resolve()
            full_path = project / output_path
            try:
                full_path.resolve().relative_to(project)
            except ValueError:
                return {"error": f"Path {output_path} is outside project root {project}"}
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(report, encoding="utf-8")
            saved_path = str(full_path)

        return {
            "report": report[:5000],
            "title": title,
            "sections_count": len(parsed_sections),
            "format": format,
            "saved_path": saved_path,
            "size_bytes": len(report.encode("utf-8")),
        }

    except Exception as e:
        return {"error": f"Report generation failed: {e}"}


def _generate_markdown(title: str, sections: list, timestamp: str) -> str:
    """Generate a Markdown report."""
    lines = [
        f"# {title}",
        "",
        f"*Generated on {timestamp} by NEXUS IDE*",
        "",
        "---",
        "",
    ]

    # Table of contents
    lines.append("## Table of Contents")
    lines.append("")
    for i, section in enumerate(sections, 1):
        heading = section.get("heading", f"Section {i}")
        anchor = heading.lower().replace(" ", "-")
        lines.append(f"{i}. [{heading}](#{anchor})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Sections
    for i, section in enumerate(sections, 1):
        heading = section.get("heading", f"Section {i}")
        content = section.get("content", "")
        lines.append(f"## {i}. {heading}")
        lines.append("")
        lines.append(content)
        lines.append("")
        lines.append("---")
        lines.append("")

    # Footer
    lines.append("*End of report*")
    lines.append("")

    return "\n".join(lines)


def _generate_html(title: str, sections: list, timestamp: str) -> str:
    """Generate an HTML report."""
    html_sections = ""
    for i, section in enumerate(sections, 1):
        heading = section.get("heading", f"Section {i}")
        content = section.get("content", "")
        # Convert newlines to <br> for HTML
        html_content = content.replace("\n", "<br>\n")
        html_sections += f"""
    <section>
      <h2>{i}. {heading}</h2>
      <div class="content">{html_content}</div>
    </section>
    <hr>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 0 auto; padding: 2rem; color: #1a1a1a; }}
    h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.5rem; }}
    h2 {{ color: #444; }}
    .meta {{ color: #666; font-size: 0.9rem; }}
    .content {{ line-height: 1.6; }}
    hr {{ border: none; border-top: 1px solid #ddd; margin: 2rem 0; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class="meta">Generated on {timestamp} by NEXUS IDE</p>
  <hr>
{html_sections}
  <p><em>End of report</em></p>
</body>
</html>"""


def _generate_text(title: str, sections: list, timestamp: str) -> str:
    """Generate a plain text report."""
    lines = [
        "=" * 60,
        title.center(60),
        "=" * 60,
        f"Generated: {timestamp}",
        "-" * 60,
        "",
    ]

    for i, section in enumerate(sections, 1):
        heading = section.get("heading", f"Section {i}")
        content = section.get("content", "")
        lines.append(f"[{i}] {heading}")
        lines.append("-" * 40)
        lines.append(content)
        lines.append("")

    lines.append("=" * 60)
    lines.append("End of report")
    lines.append("=" * 60)

    return "\n".join(lines)


register_tool(
    ToolSpec(
        name="report_generation",
        description="Generate professional reports in Markdown, HTML, or text format from structured sections.",
        schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Report title",
                    "default": "Report",
                },
                "sections": {
                    "type": "string",
                    "description": 'JSON array of sections: [{"heading": "...", "content": "..."}]',
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "html", "text"],
                    "default": "markdown",
                    "description": "Output format",
                },
                "output_path": {
                    "type": "string",
                    "description": "File path to save the report (relative to project root)",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
            "required": ["title", "sections"],
        },
        handler=generate_report,
    )
)
