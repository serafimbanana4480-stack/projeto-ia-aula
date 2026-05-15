"""Base class for all NEXUS agents with ReAct loop support.

Each concrete agent declares:
- `name`: identifier used in routing and metrics.
- `model_key`: key into `config/models.yaml`.
- `prompt_file`: filename under `config/prompts/` (without extension).
- ReAct action set supported.

Supports:
- Thinking blocks (separate from final answer)
- Tool calls via <tool>name|json_args</tool> format
- Iteration loop with max_iterations
- Streaming events: thinking, tool_call, tool_result, answer
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from backend.config.settings import get_model_config, load_prompt
from backend.observability.metrics_collector import get_metrics_collector
from backend.tools.ollama_client import ChatMessage, OllamaClient, OllamaError
from backend.tools.registry import execute_tool

logger = logging.getLogger(__name__)


class AgentAction(StrEnum):
    """Available ReAct actions — see ARCHITECTURE.md §5.2."""

    SEARCH_WEB = "search_web"
    FETCH_URL = "fetch_url"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    EXECUTE_CODE = "execute_code"
    CONSULT_AGENT = "consult_agent"
    SEARCH_CODEBASE = "search_codebase"
    READ_DOCS = "read_docs"
    RECALL_CONTEXT = "recall_context"
    ANALYZE_DATA = "analyze_data"
    GENERATE_REPORT = "generate_report"


@dataclass
class AgentRequest:
    """Input passed from the orchestrator to an agent.

    ``client`` is injected so agents are trivially mockable in unit tests.
    ``history`` holds prior turns in the same session (oldest first).
    ``project_path`` is the active project directory for file operations.
    """

    session_id: str
    query: str
    client: OllamaClient
    history: list[ChatMessage] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    max_iterations: int = 7
    enable_thinking: bool = False
    project_path: str = ""


@dataclass
class AgentResponse:
    agent: str
    model: str
    content: str
    tokens_out: int
    metrics: dict[str, Any] = field(default_factory=dict)


class AgentBase(ABC):
    """Abstract agent with ReAct loop support.

    Subclasses declare three class attributes:

    - ``name``: identifier used in routing, metrics and logs.
    - ``model_key``: key into ``config/models.yaml`` (e.g. ``"nano"``).
    - ``prompt_file``: filename stem under ``config/prompts/``.
    """

    name: str
    model_key: str
    prompt_file: str
    supported_actions: set[AgentAction] = set()

    # ------------------------------------------------------------------
    # Shared helpers (DRY for single-shot streaming agents)
    # ------------------------------------------------------------------
    def resolve_model_id(self) -> str:
        """Return the concrete Ollama model tag for this agent."""
        return get_model_config(self.model_key)["id"]

    def system_prompt(self) -> str:
        """Return the cached system prompt for this agent."""
        return load_prompt(self.prompt_file)

    # Action-to-tool mapping for ReAct loop
    _ACTION_TOOLS: dict[AgentAction, tuple[str, str]] = {
        AgentAction.READ_FILE: ("read_file", '{"path": "<file_path>"}'),
        AgentAction.WRITE_FILE: ("write_file", '{"path": "<file_path>", "content": "<file_content>"}'),
        AgentAction.EXECUTE_CODE: ("execute_code", '{"code": "<code_string>", "language": "python"}'),
        AgentAction.SEARCH_CODEBASE: ("search_codebase", '{"query": "<search_query>", "project_path": "."}'),
        AgentAction.SEARCH_WEB: ("web_search", '{"query": "<search_query>"}'),
        AgentAction.FETCH_URL: ("fetch_url", '{"url": "<target_url>"}'),
        AgentAction.CONSULT_AGENT: ("consult_agent", '{"agent": "<agent_name>", "question": "<question_to_ask>"}'),
        AgentAction.READ_DOCS: ("read_file", '{"path": "<doc_file>"}'),
        AgentAction.RECALL_CONTEXT: ("recall_context", '{"query": "<search_query>"}'),
        AgentAction.ANALYZE_DATA: ("data_analysis", '{"data_path": "<file>", "query": "<analysis_query>"}'),
        AgentAction.GENERATE_REPORT: ("report_generation", '{"title": "<title>", "sections": "<json_sections>"}'),
    }

    def build_messages(self, request: AgentRequest, context: str = "") -> list[ChatMessage]:
        """Assemble the message list sent to Ollama: system + history + user."""
        system_content = self.system_prompt()

        # Inject tool usage instructions if agent supports ReAct actions
        if self.supported_actions:
            tool_instructions = self._build_tool_instructions()
            if tool_instructions:
                system_content += "\n\n" + tool_instructions

        messages: list[ChatMessage] = [ChatMessage(role="system", content=system_content)]
        if context:
            messages.append(
                ChatMessage(role="system", content=f"Context from previous steps:\n{context}")
            )
        messages.extend(request.history)
        messages.append(ChatMessage(role="user", content=request.query))
        return messages

    def _build_tool_instructions(self) -> str:
        """Build tool usage instructions for agents with ReAct support."""
        lines = [
            "TOOL USAGE — You have access to the following tools. Use them by outputting one of these formats:",
            "",
            "Format 1 (preferred - JSON code block):",
            '```tool',
            '{"name": "tool_name", "arguments": {"arg1": "value1", "arg2": "value2"}}',
            '```',
            "",
            "Format 2 (legacy - inline tags):",
            '<tool>tool_name|{"arg1": "value1", "arg2": "value2"}</tool>',
            "",
            "Available tools:",
        ]
        for action in self.supported_actions:
            mapping = self._ACTION_TOOLS.get(action)
            if mapping:
                tool_name, example_args = mapping
                lines.append(f'  - {tool_name}: {example_args}')

        lines.extend([
            "",
            "RULES:",
            "- Always use write_file to create or modify files - NEVER just describe code.",
            "- Always use read_file before modifying existing files.",
            "- Always use execute_code to test your code after writing it.",
            "- You may use multiple tool calls in one response.",
            "- After tool results, continue with your next action or provide your final answer.",
        ])
        return "\n".join(lines)

    async def stream_llm(
        self,
        request: AgentRequest,
        *,
        temperature: float | None = None,
        context: str = "",
    ) -> AsyncIterator[str]:
        """Default single-shot streaming with automatic model fallback.

        Tries the primary model first. If it fails (e.g. model not installed),
        falls back to the fallback_id defined in models.yaml.
        """
        model_cfg = get_model_config(self.model_key)
        options: dict[str, Any] = {
            "temperature": temperature
            if temperature is not None
            else model_cfg.get("temperature", 0.7),
            "num_predict": model_cfg.get("max_tokens", 2048),
        }
        messages = self.build_messages(request, context)

        # Try primary model, then fallback
        fallback_id = model_cfg.get("fallback_id")
        models_to_try = [model_cfg["id"]]
        if fallback_id and fallback_id != model_cfg["id"]:
            models_to_try.append(fallback_id)

        last_error: Exception | None = None
        for model_id in models_to_try:
            collector = get_metrics_collector()
            started_at = time.monotonic()
            tokens_out = 0
            request_success = False

            def _capture_final_chunk(chunk: dict[str, Any]) -> None:
                nonlocal tokens_out
                usage = chunk.get("usage") if isinstance(chunk, dict) else None
                if not isinstance(usage, dict):
                    return
                tokens_out_value = usage.get("output_tokens") or usage.get("completion_tokens")
                if isinstance(tokens_out_value, int) and tokens_out_value > 0:
                    tokens_out = tokens_out_value

            try:
                if model_id != models_to_try[0]:
                    logger.warning(
                        "Primary model %s failed, falling back to %s for agent %s",
                        models_to_try[0], model_id, self.name,
                    )
                async for token in request.client.chat_stream(
                    model=model_id,
                    messages=messages,
                    options=options,
                    on_final_chunk=_capture_final_chunk,
                ):
                    tokens_out += 1
                    yield token
                request_success = True
                return  # Success — done
            except OllamaError as exc:
                last_error = exc
                logger.warning(
                    "Model %s failed for agent %s: %s. Trying next fallback.",
                    model_id, self.name, exc,
                )
                continue
            finally:
                latency_ms = (time.monotonic() - started_at) * 1000.0
                await collector.record_request(success=request_success, latency_ms=latency_ms)
                if tokens_out > 0:
                    await collector.record_token(model_id, tokens_out)

        # All models exhausted
        if last_error:
            raise last_error

    def _parse_tool_calls(self, content: str) -> list[tuple[str, dict]]:
        """Parse tool calls from content.

        Supports two formats:
        1. <tool>name|json_args</tool>  (legacy tag format)
        2. ```tool\n{"name": "...", "arguments": {...}}\n```  (JSON code block format)

        Returns list of (tool_name, args_dict) tuples.
        """
        calls = []

        # Format 1: Legacy <tool>name|json_args</tool> tags
        tag_pattern = r"<tool>(\w+)\|(.+?)</tool>"
        for match in re.finditer(tag_pattern, content):
            tool_name = match.group(1)
            try:
                args = json.loads(match.group(2))
                calls.append((tool_name, args))
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse tool args: {match.group(2)}")

        # Format 2: JSON code blocks with tool calls
        # Matches: ```tool\n{"name": "tool_name", "arguments": {...}}\n```
        # Also matches: ```tool\n{"tool": "tool_name", "args": {...}}\n```
        code_block_pattern = r"```tool\s*\n(.*?)```"
        for match in re.finditer(code_block_pattern, content, re.DOTALL):
            try:
                tool_json = json.loads(match.group(1).strip())
                # Support multiple key naming conventions
                tool_name = (
                    tool_json.get("name")
                    or tool_json.get("tool")
                    or tool_json.get("function")
                    or ""
                )
                tool_args = (
                    tool_json.get("arguments")
                    or tool_json.get("args")
                    or tool_json.get("parameters")
                    or tool_json.get("params")
                    or {}
                )
                if tool_name and isinstance(tool_args, dict):
                    calls.append((tool_name, tool_args))
            except (json.JSONDecodeError, AttributeError):
                logger.warning("Failed to parse JSON tool block: %s", match.group(1)[:100])

        # Format 3: Inline JSON tool calls (no code block)
        # Matches: {"tool_call": {"name": "...", "arguments": {...}}}
        inline_pattern = r'\{["\s]*tool_call["\s]*:\s*\{[^}]*"name"["\s]*:\s*"([^"]+)"[^}]*\}[^}]*\}'
        for match in re.finditer(inline_pattern, content):
            try:
                full_json = json.loads(match.group(0))
                tc = full_json.get("tool_call", {})
                tool_name = tc.get("name", "")
                tool_args = tc.get("arguments", tc.get("args", {}))
                if tool_name and isinstance(tool_args, dict):
                    calls.append((tool_name, tool_args))
            except (json.JSONDecodeError, AttributeError):
                pass

        return calls

    def _extract_thinking(self, content: str) -> tuple[str, str]:
        """Extract thinking block from content if present."""
        thinking_pattern = r"<thinking>(.*?)</thinking>"
        match = re.search(thinking_pattern, content, re.DOTALL)
        if match:
            thinking = match.group(1).strip()
            answer = content[: match.start()] + content[match.end() :]
            return thinking, answer
        return "", content

    async def _run_react_loop(
        self,
        request: AgentRequest,
    ) -> AsyncIterator[str]:
        """ReAct loop with tool calls and thinking blocks."""
        context = ""
        iteration = 0
        while iteration < request.max_iterations:
            iteration += 1

            # Yield thinking block if enabled
            if request.enable_thinking:
                yield f"<event>thinking|iteration:{iteration}</event>"

            # Stream LLM response
            full_response = ""
            async for token in self.stream_llm(request, context=context):
                full_response += token
                yield token

            # Extract thinking and final answer
            thinking, answer = self._extract_thinking(full_response)

            if thinking:
                yield "<event>thinking_end</event>"
                yield f"<thinking>{thinking}</thinking>"

            # Parse tool calls
            tool_calls = self._parse_tool_calls(answer)

            if not tool_calls:
                # No more tools, return final answer
                yield "<event>answer</event>"
                yield answer
                return

            # Execute tools
            for tool_name, args in tool_calls:
                yield f"<event>tool_call|{tool_name}|{json.dumps(args)}</event>"

                # Inject project_path from the request if the tool expects it
                if request.project_path and "project_path" not in args:
                    args["project_path"] = request.project_path

                result = await execute_tool(tool_name, request.session_id, args)

                if "error" in result:
                    yield f"<event>tool_error|{result['error']}</event>"
                else:
                    yield f"<event>tool_result|{tool_name}|{json.dumps(result.get('result', ''))}</event>"

                context += f"\nTool {tool_name} returned: {json.dumps(result, default=str)}"

            # Continue loop with context

    # ------------------------------------------------------------------
    # Required override
    # ------------------------------------------------------------------
    @abstractmethod
    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Execute the agent, yielding streaming chunks to the caller."""
        raise NotImplementedError
