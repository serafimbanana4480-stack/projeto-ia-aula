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

import asyncio
import contextlib

# Cache modules — best-effort; system works without them
import importlib.util
import json
import logging
import re
import time
from abc import ABC
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from backend.agents.action_registry import get_action_registry
from backend.config.settings import get_model_config, load_prompt
from backend.observability.metrics_collector import get_metrics_collector
from backend.token_management import (
    ContextOverflowError,
    count_tokens,
    deduplicate_context_blocks,
    dynamic_threshold,
    trim_context_structured,
    validate_total_budget,
)
from backend.tools.ollama_client import ChatMessage
from backend.tools.registry import execute_tool

_HAVE_CACHE = (
    importlib.util.find_spec("backend.cache.semantic_cache") is not None
    and importlib.util.find_spec("backend.cache.tool_result_cache") is not None
)

try:
    from backend.observability.metrics import get_cost_tracker

    _HAVE_COST_TRACKER = True
except ImportError:
    _HAVE_COST_TRACKER = False

logger = logging.getLogger(__name__)


class AgentAction(StrEnum):
    """Available ReAct actions — see ARCHITECTURE.md §5.2."""

    SEARCH_WEB = "search_web"
    FETCH_URL = "fetch_url"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    WRITE_FILE_ABSOLUTE = "write_file_absolute"
    READ_FILE_ABSOLUTE = "read_file_absolute"
    LIST_DIR = "list_dir"
    LIST_DIR_ABSOLUTE = "list_dir_absolute"
    EXECUTE_CODE = "execute_code"
    CONSULT_AGENT = "consult_agent"
    SEARCH_CODEBASE = "search_codebase"
    SEARCH_SYMBOLS = "search_symbols"
    INDEX_SYMBOLS = "index_symbols"
    READ_DOCS = "read_docs"
    RECALL_CONTEXT = "recall_context"
    STORE_MEMORY = "store_memory"
    ANALYZE_DATA = "analyze_data"
    GENERATE_REPORT = "generate_report"
    SCAFFOLD_PROJECT = "scaffold_project"
    SEARCH_GITHUB = "search_github"
    SEARCH_DOCS = "search_docs"
    DEEP_RESEARCH = "deep_research"


@dataclass
class AgentRequest:
    """Input passed from the orchestrator to an agent.

    ``client`` is injected so agents are trivially mockable in unit tests.
    ``history`` holds prior turns in the same session (oldest first).
    ``project_path`` is the active project directory for file operations.
    """

    session_id: str
    query: str
    client: Any  # LLM provider — OllamaProvider, OpenAIProvider, etc.
    history: list[ChatMessage] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    max_iterations: int = 4
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
    enable_memory: bool = True  # automatically recall/store semantic memories

    # ------------------------------------------------------------------
    # Shared helpers (DRY for single-shot streaming agents)
    # ------------------------------------------------------------------
    def resolve_model_id(self) -> str:
        """Return the concrete Ollama model tag for this agent."""
        return get_model_config(self.model_key)["id"]

    def system_prompt(self) -> str:
        """Return the cached system prompt for this agent."""
        return load_prompt(self.prompt_file)

    async def abuild_messages(
        self, request: AgentRequest, context: str = ""
    ) -> list[dict[str, str]]:
        """Assemble the message list sent to the LLM: system + history + user.

        When ``enable_memory`` is true, relevant semantic memories from past
        sessions are automatically injected as an additional system message.
        """
        system_content = self.system_prompt()

        # Inject tool usage instructions if agent supports ReAct actions
        if self.supported_actions:
            tool_instructions = self._build_tool_instructions()
            if tool_instructions:
                system_content += "\n\n" + tool_instructions

        # Allow the orchestrator to inject mode-specific instructions cleanly
        # via the request context instead of polluting the user message.
        system_addon = request.context.get("_system_addon") or request.context.get(
            "system_prompt_addon"
        )
        if system_addon:
            system_content += (
                "\n\n"
                + "=" * 60
                + "\nMODE-SPECIFIC INSTRUCTIONS\n"
                + "=" * 60
                + "\n"
                + str(system_addon)
            )

        messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]

        # Inject relevant semantic memories asynchronously (non-blocking)
        if self.enable_memory:
            try:
                from backend.knowledge.memory import get_memory_store

                memory_store = get_memory_store()
                memory_context = await asyncio.wait_for(
                    memory_store.get_context(
                        request.query,
                        session_id=request.session_id,
                        project_id=request.project_path or "",
                        top_k=5,
                        max_tokens=1500,
                    ),
                    timeout=10.0,
                )
                if memory_context:
                    messages.append(
                        {
                            "role": "system",
                            "content": f"Relevant memories from past conversations:\n{memory_context}",
                        }
                    )
            except Exception as exc:
                logger.debug("[%s] Failed to load semantic memory context: %s", self.name, exc)

        if context:
            messages.append(
                {"role": "system", "content": f"Context from previous steps:\n{context}"}
            )
        for msg in request.history:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": request.query})

        # Deduplicate context blocks before sending to LLM
        # This prevents repeated instructions from inflating the context
        if len(messages) > 2:
            text_blocks = [m.get("content", "") for m in messages]
            if text_blocks:
                deduped_contents = deduplicate_context_blocks(text_blocks)
                for i, m in enumerate(messages):
                    if i < len(deduped_contents):
                        m["content"] = deduped_contents[i]
        return messages

    def build_messages(self, request: AgentRequest, context: str = "") -> list[dict[str, str]]:
        """Synchronous wrapper for :meth:`abuild_messages`.

        Prefer :meth:`abuild_messages` in async code to avoid event-loop
        conflicts. This wrapper is kept for backward compatibility and
        test helpers.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.abuild_messages(request, context))

        # Already inside an event loop: schedule and block the current
        # thread. This is safe when called from synchronous test code
        # that is itself running inside the async test runner.
        return asyncio.run_coroutine_threadsafe(
            self.abuild_messages(request, context), loop
        ).result(timeout=12.0)

    def _build_tool_instructions(self) -> str:
        """Build tool usage instructions for agents with ReAct support."""
        lines = [
            "=" * 60,
            "TOOL USAGE - You MUST use tools to act. Do not just describe actions.",
            "=" * 60,
            "",
            "Use EXACTLY ONE of these formats (Format 1 is preferred):",
            "",
            "Format 1 (JSON code block - preferred):",
            "```tool",
            '{"name": "tool_name", "arguments": {"arg1": "value1"}}',
            "```",
            "",
            "Format 2 (inline XML tags):",
            '<tool_call>{"name": "tool_name", "arguments": {"arg1": "value1"}}</tool_call>',
            "",
            "Format 3 (legacy inline tags):",
            '<tool>tool_name|{"arg1": "value1"}</tool>',
            "",
            "Available tools:",
        ]
        for action in self.supported_actions:
            mapping = get_action_registry().get(action.name)
            if mapping:
                tool_name = mapping.tool
                example_args = mapping.example_args
                lines.append(f"  - {tool_name}: {example_args}")

        lines.extend(
            [
                "",
                "CRITICAL RULES:",
                "1. When asked to create or modify files, IMMEDIATELY call write_file or write_file_absolute.",
                "2. Use write_file for paths relative to the project root.",
                "3. Use write_file_absolute for absolute paths outside the project (e.g. C:\\Users\\...).",
                "4. Use read_file before modifying an existing file.",
                "5. Use execute_code or execute_terminal to verify your work when applicable.",
                "6. You may emit MULTIPLE tool calls in a single response.",
                "7. After each tool result, decide the next action or give your final answer.",
                "8. NEVER apologise for not being able to act - just call the tool.",
                "9. Use CONSULT_AGENT when you need specialised expertise you do not have.",
                "   Examples: consult ARCHITECT for design, ANALYZER for review, DEBUGGER for bugs, RESEARCHER for external info.",
                "10. In MODO AUTÓNOMO / auto mode, act with maximum autonomy: plan, explore, consult, execute, verify, and summarise.",
                "",
                "EXAMPLE - create a file with an absolute path:",
                "```tool",
                '{"name": "write_file_absolute", "arguments": {"path": "C:\\\\Users\\\\rodri\\\\Desktop\\\\desligar\\\\teste.txt", "content": "Ola Mundo"}}',
                "```",
                "",
                "EXAMPLE - consult another agent:",
                "```tool",
                '{"name": "consult_agent", "arguments": {"agent": "ARCHITECT", "question": "What is the best design for a plugin registry?"}}',
                "```",
                "",
            ]
        )
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
        max_tokens = model_cfg.get("max_tokens", 2048)
        # Cap tokens for faster responses on simple tasks
        if max_tokens > 4096:
            max_tokens = 4096
        options: dict[str, Any] = {
            "temperature": temperature
            if temperature is not None
            else model_cfg.get("temperature", 0.7),
            "num_predict": max_tokens,
            "stop": ["<|im_end|>", "<|endoftext|>", "</tool_call>"],
        }
        messages = await self.abuild_messages(request, context)

        # Validate total token budget before sending to LLM
        try:
            total_input = sum(count_tokens(str(m), self.model_key) for m in messages)
            validate_total_budget(
                system_tokens=total_input,
                model_tier=self.model_key,
                output_reserve=max_tokens,
            )
        except ContextOverflowError as e:
            # If overflow, try trimming context and retry
            logger.warning("[%s] %s. Attempting context compression...", self.name, e)
            # Compress history by keeping only last 3 turns
            compressed_messages = [messages[0]]  # Keep system
            if len(messages) > 4:
                # Keep system, last 2 user/assistant pairs, current query
                compressed_messages.extend(messages[-3:])
            else:
                compressed_messages = messages[:3] + [messages[-1]]
            messages = compressed_messages
            # Re-validate
            total_input = sum(count_tokens(str(m), self.model_key) for m in messages)
            validate_total_budget(
                system_tokens=total_input,
                model_tier=self.model_key,
                output_reserve=max_tokens,
            )

        # Try primary model, then fallback
        fallback_id = model_cfg.get("fallback_id")
        models_to_try = [model_cfg["id"]]
        if fallback_id and fallback_id != model_cfg["id"]:
            models_to_try.append(fallback_id)

        # Optional test override: NEXUS_TEST_MODEL=<alias> forces every agent
        # to use a smaller, CPU-friendly model regardless of models.yaml.
        # Useful for CI / dev machines without GPU.
        import os

        test_model = os.environ.get("NEXUS_TEST_MODEL", "").strip()
        if test_model:
            models_to_try = [test_model]

        last_error: Exception | None = None
        for attempt_idx, model_id in enumerate(models_to_try):
            collector = get_metrics_collector()
            started_at = time.monotonic()
            tokens_out = 0

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
                        models_to_try[0],
                        model_id,
                        self.name,
                    )
                async for token in request.client.chat_stream(
                    model=model_id,
                    messages=messages,
                    options=options,
                    on_final_chunk=_capture_final_chunk,
                ):
                    tokens_out += 1
                    yield token
                latency_ms = (time.monotonic() - started_at) * 1000.0
                await collector.record_request(success=True, latency_ms=latency_ms)
                if tokens_out > 0:
                    await collector.record_token(model_id, tokens_out)
                # Record cost tracking
                if _HAVE_COST_TRACKER:
                    try:
                        tracker = get_cost_tracker()
                        # Estimate input tokens
                        input_tokens = sum(count_tokens(str(m), self.model_key) for m in messages)
                        tracker.record(
                            model=model_id,
                            input_tokens=input_tokens,
                            output_tokens=tokens_out,
                            session_id=request.session_id,
                            agent=self.name,
                        )
                    except Exception:
                        pass  # Cost tracking is best-effort
                return  # Success — done
            except Exception as exc:
                last_error = exc
                latency_ms = (time.monotonic() - started_at) * 1000.0
                is_last_model = attempt_idx >= len(models_to_try) - 1
                if is_last_model:
                    await collector.record_request(success=False, latency_ms=latency_ms)
                logger.warning(
                    "Model %s failed for agent %s: %s. Trying next fallback.",
                    model_id,
                    self.name,
                    exc,
                )
                continue

        # All models exhausted
        if last_error:
            raise last_error

    def _parse_tool_calls(self, content: str) -> list[tuple[str, dict]]:
        """Parse tool calls from LLM content.

        Supports many formats to maximise compatibility with local models:
        1. ```tool\n{"name": "...", "arguments": {...}}\n```  (JSON code block)
        2. <tool_call>{...}</tool_call>  (XML tag)
        3. <tool>name|json_args</tool>  (legacy)
        4. {"name": "...", "arguments": {...}} inline
        5. Arrays of tool calls: [{"name": ...}, {"name": ...}]

        Returns list of (tool_name, args_dict) tuples.
        """
        calls: list[tuple[str, dict]] = []
        seen: set[str] = set()

        def _add(tool_name: str, tool_args: Any) -> None:
            if not tool_name or not isinstance(tool_args, dict):
                return
            key = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"
            if key in seen:
                return
            seen.add(key)
            calls.append((tool_name, dict(tool_args)))

        def _extract_from_json(obj: Any) -> None:
            """Recursively extract tool calls from parsed JSON objects."""
            if isinstance(obj, list):
                for item in obj:
                    _extract_from_json(item)
                return
            if not isinstance(obj, dict):
                return
            name = (
                obj.get("name")
                or obj.get("tool")
                or obj.get("function")
                or obj.get("tool_name")
                or ""
            )
            args = (
                obj.get("arguments")
                or obj.get("args")
                or obj.get("parameters")
                or obj.get("params")
                or {}
            )
            if name and isinstance(args, dict):
                _add(str(name), args)
            if "function_call" in obj and isinstance(obj["function_call"], dict):
                _extract_from_json(obj["function_call"])

        # Format 1: JSON code blocks ```tool ... ``` or any code block that
        # contains a tool call (some models wrap it in ```bash or ```json).
        for match in re.finditer(
            r"```(?:tool|bash|json|shell|cmd)?\s*\n(.*?)```", content, re.DOTALL
        ):
            raw = match.group(1).strip()
            # If the block contains a <tool_call> tag, parse that instead
            if "<tool_call>" in raw:
                continue  # handled by Format 2
            try:
                _extract_from_json(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON tool block: %s", raw[:120])

        # Format 2: <tool_call>...</tool_call>
        for match in re.finditer(r"<tool_call>(.+?)</tool_call>", content, re.DOTALL):
            raw = match.group(1).strip()
            try:
                _extract_from_json(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning("Failed to parse Qwen tool_call: %s", raw[:120])

        # Format 3: Legacy <tool>name|json_args</tool>
        for match in re.finditer(r"<tool>(\w+)\|(.+?)</tool>", content):
            try:
                _add(match.group(1), json.loads(match.group(2)))
            except json.JSONDecodeError:
                logger.warning("Failed to parse legacy tool args: %s", match.group(2)[:120])

        def _extract_json_objects(text: str):
            """Single-pass JSON object/array extractor using brace counting.
            Yields parsed JSON objects found in the text.
            """
            i = 0
            text_len = len(text)
            while i < text_len:
                if text[i] not in ("{", "["):
                    i += 1
                    continue

                start = i
                depth = 0
                in_string = False
                is_array = text[i] == "["
                opening = text[i]
                closing = "]" if is_array else "}"

                while i < text_len:
                    ch = text[i]
                    if in_string:
                        if ch == "\\":
                            i += 2
                            continue
                        elif ch == '"':
                            in_string = False
                    else:
                        if ch == '"':
                            in_string = True
                        elif ch == opening:
                            depth += 1
                        elif ch == closing:
                            depth -= 1
                            if depth == 0:
                                snippet = text[start : i + 1]
                                with contextlib.suppress(json.JSONDecodeError):
                                    yield json.loads(snippet)
                                break
                    i += 1
                else:
                    snippet = text[start:]
                    with contextlib.suppress(json.JSONDecodeError):
                        yield json.loads(snippet)
                    break

                i += 1

        # Format 4: Scan for inline JSON objects using efficient brace-counting
        for obj in _extract_json_objects(content):
            try:
                _extract_from_json(obj)
            except Exception:
                continue

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

    def _estimate_tokens(self, text: str) -> int:
        """Token estimate: uses tiktoken if available, falls back to len//4."""
        return count_tokens(text, self.model_key)

    _FILE_TASK_MARKERS: tuple[str, ...] = (
        "create a file",
        "create file",
        "write a file",
        "write file",
        "criar ficheiro",
        "criar um ficheiro",
        "criar arquivo",
        "escrever ficheiro",
        "guardar ficheiro",
        "modificar ficheiro",
        ".txt",
    )

    def _is_file_task(self, query: str) -> bool:
        lowered = query.lower()
        return any(m in lowered for m in self._FILE_TASK_MARKERS) or bool(
            re.search(r"[A-Za-z]:\\|/Users/|/home/|Desktop", query)
        )

    def _is_code_only_file_response(self, answer: str) -> bool:
        """True when the model answered a file task with example code instead of tools."""
        lowered = answer.lower()
        if re.search(r"```(?:python|py|bash|shell|cmd)", answer, re.IGNORECASE):
            return True
        code_hints = ("with open(", "open(", "pathlib", "os.path", "writefile", "echo >")
        return any(h in lowered for h in code_hints)

    def _trim_context(self, context: str, iteration: int) -> str:
        """Trim context using structured iteration compression.

        Falls back to simple truncation if structured data is not available.
        """
        # Try to use structured trimming
        try:
            # Parse iterations from context
            iterations_raw = context.split("\nTool ")
            iterations = []
            for i, raw in enumerate(iterations_raw):
                if raw.strip():
                    iterations.append(
                        {
                            "thought": raw[:200],
                            "tool": "",
                            "result": raw,
                            "iteration": i,
                        }
                    )

            if len(iterations) > 3:
                trimmed = trim_context_structured(iterations, self.model_key, self.model_key)
                if trimmed:
                    result = "\n".join(
                        it.get("result", it.get("content", str(it))) for it in trimmed
                    )
                    # Log reduction
                    before_tok = count_tokens(context, self.model_key)
                    after_tok = count_tokens(result, self.model_key)
                    reduction = (1 - after_tok / max(1, before_tok)) * 100
                    logger.debug(
                        "[%s] Context trimmed: %d \u2192 %d tokens (%.0f%% reduction)",
                        self.name,
                        before_tok,
                        after_tok,
                        reduction,
                    )
                    return result
        except Exception as exc:
            logger.debug("[%s] Structured trimming failed: %s", self.name, exc)

        # Fallback: simple truncation (original behavior)
        token_count = self._estimate_tokens(context)
        if token_count <= dynamic_threshold(self.model_key):
            return context

        iterations_raw = context.split("\nTool ")
        if len(iterations_raw) > 3:
            summary_parts = []
            keep_start = max(0, len(iterations_raw) - 3)
            for i, it in enumerate(iterations_raw[:keep_start]):
                first_line = it.split("\n")[0] if "\n" in it else it[:60]
                summary_parts.append(f"[Iteration {i + 1}] {first_line}")
            digest = "\n".join(summary_parts)
            recent = "\nTool ".join(iterations_raw[keep_start:])
            trimmed = f"[Memory digest of earlier steps]\n{digest}\n\n[Recent steps]\n{recent}"

            before_tok = self._estimate_tokens(context)
            after_tok = self._estimate_tokens(trimmed)
            logger.debug(
                "[%s] Context trimmed (fallback): %d \u2192 %d tokens",
                self.name,
                before_tok,
                after_tok,
            )
            return trimmed

        # Very short context — just truncate
        excess = self._estimate_tokens(context) - dynamic_threshold(self.model_key)
        return context[excess * 4 :]

    async def _run_react_loop(
        self,
        request: AgentRequest,
    ) -> AsyncIterator[str]:
        """ReAct loop with tool calls, thinking blocks, and detailed logging."""
        context = ""
        iteration = 0
        previous_tool_calls: list[tuple[str, dict]] | None = None
        previous_thinking = ""  # Track to avoid repeating identical thinking blocks
        logger.info(
            "[%s] ReAct loop started | session=%s | query=%.80s | project=%s | max_iter=%d",
            self.name,
            request.session_id,
            request.query,
            request.project_path,
            request.max_iterations,
        )
        while iteration < request.max_iterations:
            iteration += 1
            logger.info(
                "[%s] ReAct iteration %d/%d | session=%s",
                self.name,
                iteration,
                request.max_iterations,
                request.session_id,
            )

            # Trim context before each iteration to prevent unbounded growth
            context = self._trim_context(context, iteration)

            # Yield thinking block if enabled
            if request.enable_thinking:
                yield f"<event>thinking|iteration:{iteration}</event>"

            # Stream LLM response
            full_response = ""
            token_count = 0
            stream_start = time.monotonic()
            try:
                async for token in self.stream_llm(request, context=context):
                    full_response += token
                    token_count += 1
                    yield token
            except Exception as exc:
                logger.error(
                    "[%s] LLM stream failed on iteration %d: %s",
                    self.name,
                    iteration,
                    exc,
                    exc_info=True,
                )
                yield f"<event>error|LLM stream failed: {exc}</event>"
                return
            stream_elapsed = time.monotonic() - stream_start
            logger.info(
                "[%s] LLM response received | iteration=%d | tokens=%d | elapsed_ms=%.1f",
                self.name,
                iteration,
                token_count,
                stream_elapsed * 1000,
            )

            # Extract thinking and final answer
            thinking, answer = self._extract_thinking(full_response)

            if thinking:
                # Skip if thinking block is identical to previous iteration
                if thinking == previous_thinking:
                    logger.debug("[%s] Skipping duplicate thinking block", self.name)
                else:
                    logger.debug("[%s] Thinking block extracted | len=%d", self.name, len(thinking))
                    yield "<event>thinking_end</event>"
                    yield f"<thinking>{thinking}</thinking>"
                    previous_thinking = thinking

            # Parse tool calls
            tool_calls = self._parse_tool_calls(answer)
            logger.info(
                "[%s] Tool calls parsed | iteration=%d | count=%d",
                self.name,
                iteration,
                len(tool_calls),
            )

            if not tool_calls:
                # Model sometimes returns Python "usage examples" instead of tool
                # calls for file tasks. Nudge once before accepting the answer.
                if (
                    iteration == 1
                    and self._is_file_task(request.query)
                    and self._is_code_only_file_response(answer)
                    and iteration < request.max_iterations
                ):
                    logger.warning(
                        "[%s] File task answered with code only — nudging model to call tools",
                        self.name,
                    )
                    context += (
                        "\n[SYSTEM] The user asked to create or modify a REAL file on disk. "
                        "Do NOT show Python or shell examples. Call write_file_absolute (for "
                        "absolute paths like C:\\Users\\...) or write_file (for project-relative "
                        "paths) NOW using the ```tool JSON format."
                    )
                    continue

                # No more tools, return final answer
                logger.info(
                    "[%s] No tool calls detected — emitting final answer | iteration=%d",
                    self.name,
                    iteration,
                )
                yield "<event>answer</event>"
                return

            # Detect duplicate tool-call loops (models sometimes repeat the same
            # call after a successful write). If the exact same calls appear twice
            # in a row, stop and return the last answer as final.
            if previous_tool_calls is not None:
                current_key = json.dumps(tool_calls, sort_keys=True, default=str)
                previous_key = json.dumps(previous_tool_calls, sort_keys=True, default=str)
                if current_key == previous_key:
                    logger.warning(
                        "[%s] Detected repeated identical tool calls — breaking loop | iteration=%d",
                        self.name,
                        iteration,
                    )
                    yield "<event>answer</event>"
                    return
            previous_tool_calls = tool_calls

            # Execute tools
            for tool_name, args in tool_calls:
                logger.info(
                    "[%s] Executing tool | iteration=%d | tool=%s | args=%s",
                    self.name,
                    iteration,
                    tool_name,
                    args,
                )
                yield f"<event>tool_call|{tool_name}|{json.dumps(args)}</event>"

                # Inject project_path from the request only if the tool schema accepts it.
                # This avoids TypeErrors for tools like write_file_absolute that do not
                # take a project_path argument.
                if request.project_path and "project_path" not in args:
                    from backend.tools.registry import get_tool

                    spec = get_tool(tool_name)
                    schema_props = (
                        spec.schema.get("properties", {})
                        if spec and isinstance(spec.schema, dict)
                        else {}
                    )
                    if "project_path" in schema_props:
                        args["project_path"] = request.project_path
                        logger.debug(
                            "[%s] Injected project_path=%s into tool args",
                            self.name,
                            request.project_path,
                        )

                # Auto-upgrade relative file tools to absolute variants when the
                # supplied path is absolute. Local models often pick the wrong tool.
                path_arg = args.get("path", "")
                if isinstance(path_arg, str):
                    norm_path = path_arg.replace("/", "\\")
                    if (
                        (
                            tool_name == "write_file"
                            and (
                                norm_path.startswith("\\\\")
                                or (len(norm_path) > 1 and norm_path[1] == ":")
                            )
                        )
                        or (
                            tool_name == "read_file"
                            and (
                                norm_path.startswith("\\\\")
                                or (len(norm_path) > 1 and norm_path[1] == ":")
                            )
                        )
                        or (
                            tool_name == "list_dir"
                            and (
                                norm_path.startswith("\\\\")
                                or (len(norm_path) > 1 and norm_path[1] == ":")
                            )
                        )
                    ):
                        upgraded = tool_name + "_absolute"
                        logger.info(
                            "[%s] Auto-upgraded %s -> %s for absolute path %s",
                            self.name,
                            tool_name,
                            upgraded,
                            path_arg,
                        )
                        tool_name = upgraded
                        # Absolute tools do not accept project_path; remove it if
                        # it was injected above.
                        args.pop("project_path", None)

                # Inject source_agent for inter-agent consultation so the
                # consulted agent knows who is calling and A2A traceability is complete.
                if tool_name == "consult_agent" and "source_agent" not in args:
                    args["source_agent"] = self.name
                    logger.debug(
                        "[%s] Injected source_agent=%s into consult_agent args",
                        self.name,
                        self.name,
                    )

                tool_start = time.monotonic()
                result = await execute_tool(tool_name, request.session_id, args)
                tool_elapsed = time.monotonic() - tool_start

                if "error" in result:
                    logger.warning(
                        "[%s] Tool error | iteration=%d | tool=%s | error=%s | elapsed_ms=%.1f",
                        self.name,
                        iteration,
                        tool_name,
                        result["error"],
                        tool_elapsed * 1000,
                    )
                    yield f"<event>tool_error|{result['error']}</event>"
                else:
                    logger.info(
                        "[%s] Tool success | iteration=%d | tool=%s | elapsed_ms=%.1f",
                        self.name,
                        iteration,
                        tool_name,
                        tool_elapsed * 1000,
                    )
                    yield f"<event>tool_result|{tool_name}|{json.dumps(result.get('result', ''))}</event>"

                context += f"\nTool {tool_name} returned: {json.dumps(result, default=str)}"

                # If a write succeeded, strongly signal that the task is done so
                # the model does not loop repeating the same call.
                inner = result.get("result")
                write_confirmed = (
                    isinstance(inner, dict)
                    and inner.get("written") is True
                    and not inner.get("error")
                )
                if (
                    tool_name in ("write_file", "write_file_absolute")
                    and "error" not in result
                    and write_confirmed
                ):
                    yield "<event>answer</event>"
                    return

            # Continue loop with context

        logger.warning(
            "[%s] ReAct loop reached max iterations (%d) | session=%s",
            self.name,
            request.max_iterations,
            request.session_id,
        )
        yield f"<event>warning|Reached maximum iterations ({request.max_iterations})</event>"
        yield "<event>answer</event>"
        yield f"Concluído com {request.max_iterations} passos."

    # ------------------------------------------------------------------
    # Agent Bus helpers (pub/sub inter-agent communication)
    # ------------------------------------------------------------------
    async def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        target_agents: list[str] | None = None,
        priority: int = 3,
        ttl_seconds: int = 3600,
    ) -> None:
        """Publish a message to the Agent Bus on *topic*.

        Args:
            topic: Bus topic, e.g. ``code.changes``.
            payload: JSON-serialisable dict with the message content.
            target_agents: If provided, only those agents receive the message.
            priority: 1 (lowest) to 5 (highest).
            ttl_seconds: How long to retain the message in persistence.
        """
        import uuid

        from backend.core.agent_bus import BusMessage, get_agent_bus

        bus = get_agent_bus()
        msg = BusMessage(
            message_id=uuid.uuid4().hex[:16],
            topic=topic,
            source_agent=self.name,
            target_agents=target_agents or [],
            payload=payload,
            priority=priority,
            ttl_seconds=ttl_seconds,
        )
        await bus.publish(topic, msg)

    async def subscribe(
        self,
        topic: str,
        callback: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Subscribe this agent to a bus topic.

        Args:
            topic: Topic to listen on, e.g. ``errors.found``.
            callback: Async callable accepting a :class:`BusMessage`.

        Returns:
            A :class:`Subscription` handle that can be passed to ``unsubscribe``.
        """
        from backend.core.agent_bus import get_agent_bus

        bus = get_agent_bus()
        return await bus.subscribe(topic, callback)

    # ------------------------------------------------------------------
    # Default implementation — can be overridden by agents that need
    # custom behavior (e.g. RouterAgent, MicroAgent, SupervisorAgent).
    # Previously ~16 agents duplicated this same 4-line body.
    # ------------------------------------------------------------------
    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run the ReAct loop. Override for custom execution logic."""
        async for token in self._run_react_loop(request):
            yield token

    # ------------------------------------------------------------------
    # State-aware entry point
    # ------------------------------------------------------------------
    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Execute the agent with automatic state load / save.

        Loads existing memories into ``request.context["_agent_memories"]``
        before calling :meth:`_execute`, then persists a short-term memory
        entry after the iterator completes.
        """
        from backend.core.agent_state import AgentStateStore
        from backend.core.shared_memory import get_shared_memory

        store = AgentStateStore()
        brain = store.get_agent_brain(self.name)
        request.context["_agent_memories"] = brain.model_dump(mode="json")

        started_at = datetime.now(UTC)
        output_parts: list[str] = []
        try:
            async for token in self._execute(request):
                output_parts.append(token)
                yield token
        finally:
            elapsed = (datetime.now(UTC) - started_at).total_seconds()
            try:
                store.save_state(
                    agent_name=self.name,
                    session_id=request.session_id,
                    project_path=request.project_path or "",
                    tier="short_term",
                    key=f"run_{started_at.isoformat()}",
                    value={"query": request.query, "elapsed_seconds": round(elapsed, 3)},
                    importance=0.3,
                )
            except Exception as exc:
                logger.warning("[%s] Failed to save agent state: %s", self.name, exc)

            # Write execution summary to shared memory (swarm intelligence)
            try:
                shm = get_shared_memory()
                content = "".join(output_parts)
                await shm.write_entry(
                    agent_name=self.name,
                    topic=f"agent.execution.{self.name.lower()}",
                    content=(
                        f"Query: {request.query}\n"
                        f"Output (truncated): {content[:2000]}\n"
                        f"Elapsed: {elapsed:.3f}s"
                    ),
                    importance=0.5,
                    tags=["agent.run", self.name.lower()],
                )
            except Exception as exc:
                logger.warning("[%s] Failed to write shared memory: %s", self.name, exc)

            # Persist a semantic memory of this exchange for future recall
            if self.enable_memory:
                try:
                    from backend.knowledge.memory import MemoryType, get_memory_store

                    mem_store = get_memory_store()
                    summary = (
                        f"Agent {self.name} answered query: {request.query[:200]}\n"
                        f"Response (truncated): {''.join(output_parts)[:1000]}"
                    )
                    await mem_store.store(
                        content=summary,
                        memory_type=MemoryType.CONVERSATION,
                        session_id=request.session_id,
                        project_id=request.project_path or "",
                        source=self.name,
                        tags=["agent.run", self.name.lower(), "auto_memory"],
                        importance=0.5,
                    )
                except Exception as exc:
                    logger.debug("[%s] Failed to store semantic memory: %s", self.name, exc)
