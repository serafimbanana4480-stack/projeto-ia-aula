"""DataScientistAgent — data analysis and experiment design specialist."""
from __future__ import annotations

from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest


class DataScientistAgent(AgentBase):
    """Specialist agent for data science and analytics."""

    name = "DATA_SCIENTIST"
    model_key = "deep"
    prompt_file = "data_scientist_system"
    supported_actions = set()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        yield f"<event>ds_start|{request.query[:50]}</event>"

        query = request.query.lower()
        if "analyze" in query or "eda" in query:
            yield "## Exploratory Data Analysis\n\n"
            yield "### Steps\n"
            yield "1. Data profiling (nulls, types, distributions)\n"
            yield "2. Correlation analysis\n"
            yield "3. Outlier detection\n"
            yield "4. Visualization recommendations\n"
        elif "experiment" in query or "ab test" in query:
            yield "## Experiment Design\n\n"
            yield "- Define hypothesis and success metrics\n"
            yield "- Calculate required sample size\n"
            yield "- Set up control and treatment groups\n"
            yield "- Determine test duration\n"
        else:
            yield "Data Scientist ready. Ask about analysis, experiments, or visualizations.\n"

        yield "<event>ds_end</event>"

    def analyze_dataset(self, schema: dict[str, str]) -> dict[str, Any]:
        """Analyze a dataset schema and provide insights."""
        numeric = [k for k, v in schema.items() if v in ("int", "float", "numeric")]
        categorical = [k for k, v in schema.items() if v in ("str", "category", "text")]
        return {
            "numeric_columns": numeric,
            "categorical_columns": categorical,
            "recommendations": [
                f"Normalize {numeric[0]}" if numeric else None,
                f"Encode {categorical[0]}" if categorical else None,
            ],
        }
