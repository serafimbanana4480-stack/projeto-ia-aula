"""MICRO — fast factoid agent.

Not listed among the 9 specialised roles in §3 of the architecture, but the
Router prompt can legitimately route here for trivial questions (e.g. "what is
HTTP?"). Using the SMALL model with a concise-answer instruction keeps latency
well under one second on common hardware.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from .base import AgentAction, AgentBase, AgentRequest

_SYSTEM = (
    "You are NEXUS-MICRO, a concise and factual assistant. Match the language, "
    "format, and level of detail the user explicitly requests. For a simple question "
    "with no requested structure or length, answer in at most three sentences. "
    "If the user asks for a detailed or structured response, follow that request "
    "within the available output limit. If you are not sure, say so; never speculate."
)


class MicroAgent(AgentBase):
    name = "MICRO"
    model_key = "micro"
    prompt_file = "router"  # unused — kept for compatibility

    _delegated_mode = False

    # p37: root cause of MICRO never calling tools as a subagent: it had no
    # supported_actions, so no tool schema/contract was advertised. Expose
    # read-only actions ONLY while delegated (the plain factoid path cannot
    # execute tools and must not be told it has them).
    @property
    def supported_actions(self):  # type: ignore[override]
        if self._delegated_mode:
            return {AgentAction.READ_FILE, AgentAction.SEARCH_CODEBASE}
        return set()

    def system_prompt(self) -> str:
        if self._delegated_mode:
            # p35: as a delegated subagent MICRO must actually call its tools.
            return _SYSTEM + (
                " You are running as a delegated subagent with tools. When the task "
                "mentions files, you MUST call the file tools (e.g. read_file) and wait "
                "for their results before concluding. Never narrate that you will read "
                "a file without calling the tool, and never invent file contents."
            )
        return _SYSTEM

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        # p31: as a delegated subagent MICRO must be able to read files; the
        # plain stream path has no tools, so the model wrote tool-call markup
        # as its "answer" and the run was recorded as a success.
        if request.context.get("_delegated_by"):
            self._delegated_mode = True
            try:
                async for token in self._run_react_loop(request):
                    yield token
            finally:
                self._delegated_mode = False
            # p35: a file task finished without any successful tool is not a
            # success (MICRO narrated "Vou ler..." and invented a conclusion).
            needs_files = re.search(
                r"\.py\b|ficheiro|arquivo|\bfiles?\b|read_file|\bler\b",
                str(request.query or ""), re.IGNORECASE,
            )
            if needs_files and not request.context.get("_successful_tools"):
                self._record_run_success(request, False)
            return
        parts: list[str] = []
        async for token in self.stream_llm(request, temperature=0.3):
            parts.append(token if isinstance(token, str) else "")
            yield token
        if re.search(r"<\|?tool_call|<tool_call>|```tool", "".join(parts)):
            # Unexecuted tool-call markup is not an answer.
            self._record_run_success(request, False)
            return
        # The stream completed without raising, so the run succeeded.  The
        # verdict is instance state and ``AgentBase.run`` resets it to False
        # before every run: an agent that never sets it (this one overrides
        # ``_execute`` and never calls the ReAct loop) would never be
        # remembered, and — worse — a run that RAISED would be remembered as
        # "Agent MICRO completed a task".
        self._record_run_success(request, True)
