"""Data analysis tool — analyze CSV/JSON data with Python.

Provides real data analysis capabilities:
- Load CSV/JSON files from the project workspace
- Compute statistics (mean, median, std, correlations)
- Generate data summaries and insights
- Execute pandas-style analysis on data
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


async def analyze_data(
    data_path: str = "",
    query: str = "",
    project_path: str = ".",
    code: str = "",
) -> dict:
    """Analyze data files (CSV, JSON) with Python/pandas.

    If `code` is provided, execute it directly.
    If `query` is provided, generate analysis code from the query.
    If `data_path` is provided, load and summarize the data.
    """
    # Lazy imports — pandas/numpy are heavy and only needed at runtime
    try:
        import pandas as pd  # noqa: F811
    except ImportError:
        pd = None  # type: ignore[assignment]

    try:
        # Build analysis script
        script_parts = [
            "import json",
            "import sys",
            "try:",
            "    import pandas as pd",
            "    HAS_PANDAS = True",
            "except ImportError:",
            "    HAS_PANDAS = False",
        ]

        if code:
            # User-provided analysis code
            script_parts.append(code)
        elif data_path:
            # Load and analyze a data file
            full_path = Path(project_path).resolve() / data_path
            if not full_path.exists():
                full_path = Path(data_path).resolve()
            if not full_path.exists():
                return {"error": f"Data file not found: {data_path}"}

            ext = full_path.suffix.lower()
            if ext == ".csv":
                script_parts.append(f'df = pd.read_csv("{full_path}")')
                script_parts.append('print("Shape:", df.shape)')
                script_parts.append('print("\\nColumns:", list(df.columns))')
                script_parts.append('print("\\nDtypes:\\n", df.dtypes)')
                script_parts.append('print("\\nDescribe:\\n", df.describe().to_string())')
                script_parts.append('print("\\nHead:\\n", df.head(10).to_string())')
                if query:
                    script_parts.append(f"# Query: {query}")
                    script_parts.append(f"result = {query}")
                    script_parts.append('print("\\nResult:", result)')
            elif ext == ".json":
                script_parts.append(f'with open("{full_path}") as f: data = json.load(f)')
                script_parts.append("if isinstance(data, list) and len(data) > 0:")
                script_parts.append("    df = pd.DataFrame(data)")
                script_parts.append('    print("Shape:", df.shape)')
                script_parts.append('    print("\\nColumns:", list(df.columns))')
                script_parts.append('    print("\\nDescribe:\\n", df.describe().to_string())')
                script_parts.append("else:")
                script_parts.append('    print(json.dumps(data, indent=2)[:2000])')
            else:
                return {"error": f"Unsupported file type: {ext}. Use .csv or .json"}
        elif query:
            # General analysis query
            script_parts.append(f"# Analysis query: {query}")
            script_parts.append(f"print('Query: {query}')")
            script_parts.append("print('Provide a data_path to a CSV/JSON file for concrete analysis.')")
        else:
            return {"error": "Provide at least one of: data_path, query, or code"}

        script = "\n".join(script_parts)

        # Execute with the venv Python
        venv_python = os.environ.get("NEXUS_PYTHON", "python3")
        # Try to find the project's venv
        project_venv = Path(project_path).resolve() / ".venv" / "bin" / "python"
        if project_venv.exists():
            venv_python = str(project_venv)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script)
            f.flush()
            tmp_path = f.name

        try:
            result = await asyncio.create_subprocess_exec(
                venv_python, tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(project_path).resolve()),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                result.communicate(), timeout=30
            )
            output = stdout_bytes.decode("utf-8", errors="replace")
            if result.returncode != 0:
                error = stderr_bytes.decode("utf-8", errors="replace")
                # If pandas not available, try basic analysis
                if "No module named 'pandas'" in error or "HAS_PANDAS" in error:
                    return await _analyze_without_pandas(data_path, query, project_path)
                return {"error": f"Analysis failed: {error[:500]}", "output": output[:500]}
        finally:
            os.unlink(tmp_path)

        return {"output": output[:5000], "data_path": data_path, "query": query}

    except Exception as e:
        return {"error": f"Analysis error: {e}"}


async def _analyze_without_pandas(
    data_path: str, query: str, project_path: str
) -> dict:
    """Fallback analysis when pandas is not available."""
    import csv as csv_mod

    if not data_path:
        return {"output": f"Query: {query}\n(Install pandas for full analysis: pip install pandas)"}

    full_path = Path(project_path).resolve() / data_path
    if not full_path.exists():
        full_path = Path(data_path).resolve()
    if not full_path.exists():
        return {"error": f"Data file not found: {data_path}"}

    ext = full_path.suffix.lower()
    try:
        if ext == ".csv":
            with open(full_path, newline="", encoding="utf-8") as f:
                reader = csv_mod.reader(f)
                rows = list(reader)
            headers = rows[0] if rows else []
            data_rows = rows[1:] if len(rows) > 1 else []
            output = f"CSV: {full_path.name}\n"
            output += f"Columns ({len(headers)}): {', '.join(headers)}\n"
            output += f"Rows: {len(data_rows)}\n"
            output += f"First 5 rows:\n"
            for row in data_rows[:5]:
                output += f"  {row}\n"
            return {"output": output, "data_path": data_path}
        elif ext == ".json":
            with open(full_path, encoding="utf-8") as f:
                data = json.load(f)
            output = f"JSON: {full_path.name}\n"
            if isinstance(data, list):
                output += f"Array with {len(data)} items\n"
                if data:
                    output += f"First item keys: {list(data[0].keys()) if isinstance(data[0], dict) else type(data[0]).__name__}\n"
            elif isinstance(data, dict):
                output += f"Object with keys: {list(data.keys())}\n"
            output += f"Preview:\n{json.dumps(data, indent=2)[:1000]}\n"
            return {"output": output, "data_path": data_path}
        else:
            return {"error": f"Unsupported file type: {ext}"}
    except Exception as e:
        return {"error": f"Failed to read {data_path}: {e}"}


register_tool(
    ToolSpec(
        name="data_analysis",
        description="Analyze CSV/JSON data files with statistics and insights. Supports pandas-based analysis.",
        schema={
            "type": "object",
            "properties": {
                "data_path": {
                    "type": "string",
                    "description": "Path to CSV or JSON data file",
                },
                "query": {
                    "type": "string",
                    "description": "Analysis query or question about the data",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "code": {
                    "type": "string",
                    "description": "Python code to execute for custom analysis",
                },
            },
        },
        handler=analyze_data,
    )
)
