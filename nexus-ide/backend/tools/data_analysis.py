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

#: Marker the generated script prints when pandas is not installed in the
#: resolved interpreter. The parent then runs the pure-Python analysis.
_NO_PANDAS_MARKER = "__NEXUS_NO_PANDAS__"


def _resolve_interpreter(project_path: str = ".") -> str:
    """Return the Python interpreter used to run the analysis script.

    Resolution order: the ``NEXUS_PYTHON`` override, the project's own
    virtualenv (``.venv/Scripts/python.exe`` on Windows, ``.venv/bin/python``
    elsewhere) and finally the interpreter running the backend
    (``sys.executable``). The previous code only knew the POSIX layout and
    fell back to the literal command ``python3``, which does not exist on
    Windows — the tool could never find Python there.
    """
    from backend.tools.interpreters import resolve_python_interpreter

    return resolve_python_interpreter(project_path)


async def analyze_data(
    data_path: str = "",
    query: str = "",
    project_path: str = ".",
    code: str = "",
) -> dict:
    """Analyze data files (CSV, JSON) with Python/pandas.

    If `data_path` is provided, load and summarize the data.
    If `query` is provided, a safe analysis is generated.
    The `code` parameter is rejected for security reasons.
    """
    try:
        if code:
            return {
                "error": "The 'code' parameter is no longer supported for security reasons. Use 'data_path' and 'query' instead."
            }

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

        if data_path:
            # Load and analyze a data file
            sandbox = Path(project_path).resolve()
            full_path = (sandbox / data_path).resolve()
            if not full_path.exists():
                full_path = Path(data_path).resolve()
            if not full_path.exists():
                return {"error": f"Data file not found: {data_path}"}

            allowed = False
            try:
                full_path.relative_to(sandbox)
                allowed = True
            except ValueError:
                temp_dir = Path(tempfile.gettempdir()).resolve()
                try:
                    full_path.relative_to(temp_dir)
                    allowed = True
                except ValueError:
                    pass
            if not allowed:
                return {"error": "Access denied: file path is outside the project workspace"}

            ext = full_path.suffix.lower()
            if ext == ".csv":
                # The pandas branch is guarded: pandas is NOT a project
                # dependency, and the old script used ``pd`` unconditionally,
                # so a missing pandas raised ``NameError: name 'pd' is not
                # defined`` — which the fallback below did not recognise, and
                # the tool could not analyse a CSV at all.
                script_parts.append("if HAS_PANDAS:")
                script_parts.append(f"    df = pd.read_csv({repr(str(full_path))})")
                script_parts.append('    print("Shape:", df.shape)')
                script_parts.append('    print("\\nColumns:", list(df.columns))')
                script_parts.append('    print("\\nDtypes:\\n", df.dtypes)')
                script_parts.append('    print("\\nDescribe:\\n", df.describe().to_string())')
                script_parts.append('    print("\\nHead:\\n", df.head(10).to_string())')
                script_parts.append("else:")
                script_parts.append(f"    print({_NO_PANDAS_MARKER!r})")
                if query:
                    script_parts.append(f"# Query: {query}")
                    script_parts.append(f"print('Query:', {repr(query)})")
            elif ext == ".json":
                script_parts.append(f"with open({repr(str(full_path))}) as f: data = json.load(f)")
                script_parts.append("if isinstance(data, list) and len(data) > 0:")
                script_parts.append("    if HAS_PANDAS:")
                script_parts.append("        df = pd.DataFrame(data)")
                script_parts.append('        print("Shape:", df.shape)')
                script_parts.append('        print("\\nColumns:", list(df.columns))')
                script_parts.append('        print("\\nDescribe:\\n", df.describe().to_string())')
                script_parts.append("    else:")
                script_parts.append(f"        print({_NO_PANDAS_MARKER!r})")
                script_parts.append("else:")
                script_parts.append("    print(json.dumps(data, indent=2)[:2000])")
            else:
                return {"error": f"Unsupported file type: {ext}. Use .csv or .json"}
        elif query:
            # General analysis query (no data_path — informational only)
            script_parts.append(f"# Analysis query: {query}")
            script_parts.append(f"print('Query:', {repr(query)})")
            script_parts.append(
                "print('Provide a data_path to a CSV/JSON file for concrete analysis.')"
            )
        else:
            return {"error": "Provide at least one of: data_path, query, or code"}

        script = "\n".join(script_parts)

        # Execute with the interpreter that is actually running the backend.
        # The old code shelled out to "python3" and probed the POSIX venv
        # layout (".venv/bin/python"), so on Windows it never found a Python
        # at all and the tool could not work.
        venv_python = _resolve_interpreter(project_path)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script)
            f.flush()
            tmp_path = f.name

        try:
            result = await asyncio.create_subprocess_exec(
                venv_python,
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(project_path).resolve()),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(result.communicate(), timeout=30)
            output = stdout_bytes.decode("utf-8", errors="replace")
            if result.returncode != 0:
                error = stderr_bytes.decode("utf-8", errors="replace")
                # If pandas not available, try basic analysis
                if "No module named 'pandas'" in error or "HAS_PANDAS" in error:
                    return await _analyze_without_pandas(data_path, query, project_path)
                return {"error": f"Analysis failed: {error[:500]}", "output": output[:500]}
            if _NO_PANDAS_MARKER in output:
                # pandas is not installed in the resolved interpreter: the
                # pure-Python analysis gives the caller a real answer instead
                # of a NameError.
                return await _analyze_without_pandas(data_path, query, project_path)
        finally:
            os.unlink(tmp_path)

        return {"output": output[:5000], "data_path": data_path, "query": query}

    except Exception as e:
        return {"error": f"Analysis error: {e}"}


async def _analyze_without_pandas(data_path: str, query: str, project_path: str) -> dict:
    """Fallback analysis when pandas is not available."""
    import csv as csv_mod

    if not data_path:
        return {"output": f"Query: {query}\n(Install pandas for full analysis: pip install pandas)"}

    sandbox = Path(project_path).resolve()
    full_path = (sandbox / data_path).resolve()
    if not full_path.exists():
        full_path = Path(data_path).resolve()
    if not full_path.exists():
        return {"error": f"Data file not found: {data_path}"}

    allowed = False
    try:
        full_path.relative_to(sandbox)
        allowed = True
    except ValueError:
        temp_dir = Path(tempfile.gettempdir()).resolve()
        try:
            full_path.relative_to(temp_dir)
            allowed = True
        except ValueError:
            pass
    if not allowed:
        return {"error": "Access denied: file path is outside the project workspace"}

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
            output += "First 5 rows:\n"
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
        category="data",
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
