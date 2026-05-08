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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

from backend.config.settings import get_model_config, load_prompt
from backend.persistence.db import add_message
from backend.tools.ollama_client import ChatMessage, OllamaClient
from backend.tools.registry import execute_tool

logger = logging.getLogger(__name__)


class AgentAction(str, Enum):
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


@dataclass
class AgentRequest:
    """Input passed from the orchestrator to an agent.

    ``client`` is injected so agents are trivially mockable in unit tests.
    ``history`` holds prior turns in the same session (oldest first).
    """

    session_id: str
    query: str
    client: OllamaClient
    history: list[ChatMessage] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    max_iterations: int = 7
    enable_thinking: bool = False


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

    def build_messages(self, request: AgentRequest, context: str = "") -> list[ChatMessage]:
        """Assemble the message list sent to Ollama: system + history + user."""
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=self.system_prompt())
        ]
        if context:
            messages.append(ChatMessage(role="system", content=f"Context from previous steps:\n{context}"))
        messages.extend(request.history)
        messages.append(ChatMessage(role="user", content=request.query))
        return messages

    async def stream_llm(
        self,
        request: AgentRequest,
        *,
        temperature: float | None = None,
        context: str = "",
    ) -> AsyncIterator[str]:
        """Default single-shot streaming: system prompt + history + query."""
        model_cfg = get_model_config(self.model_key)
        options: dict[str, Any] = {
            "temperature": temperature if temperature is not None
            else model_cfg.get("temperature", 0.7),
            "num_predict": model_cfg.get("max_tokens", 2048),
        }
        async for token in request.client.chat_stream(
            model=model_cfg["id"],
            messages=self.build_messages(request, context),
            options=options,
        ):
            yield token

    def _parse_tool_calls(self, content: str) -> list[tuple[str, dict]]:
        """Parse <tool>name|json_args</tool> format from content."""
        pattern = r'<tool>(\w+)\|(.+?)</tool>'
        calls = []
        for match in re.finditer(pattern, content):
            tool_name = match.group(1)
            try:
                args = json.loads(match.group(2))
                calls.append((tool_name, args))
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse tool args: {match.group(2)}")
        return calls

    def _extract_thinking(self, content: str) -> tuple[str, str]:
        """Extract thinking block from content if present."""
        thinking_pattern = r'<thinking>(.*?)</thinking>'
        match = re.search(thinking_pattern, content, re.DOTALL)
        if match:
            thinking = match.group(1).strip()
            answer = content[:match.start()] + content[match.end():]
            return thinking, answer
        return "", content

    async def _run_react_loop(
        self,
        request: AgentRequest,
    ) -> AsyncIterator[str]:
        """ReAct loop with tool calls and thinking blocks."""
        context = ""
        iteration = 0
        model_id = self.resolve_model_id()
        
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
                yield f"<event>thinking_end</event>"
                yield f"<thinking>{thinking}</thinking>"
            
            # Parse tool calls
            tool_calls = self._parse_tool_calls(answer)
            
            if not tool_calls:
                # No more tools, return final answer
                yield f"<event>answer</event>"
                yield answer
                return
            
            # Execute tools
            for tool_name, args in tool_calls:
                yield f"<event>tool_call|{tool_name}|{json.dumps(args)}</event>"
                
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
