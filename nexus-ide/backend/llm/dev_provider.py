"""Development provider — returns plausible AI responses without any LLM inference.

This is useful for:
- Development and testing when no local models or API keys are available
- CI pipelines that need deterministic responses
- Demos and screenshots

The responses are structured to look realistic while being fast and zero-cost.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator
from typing import Any

from backend.llm.airllm_provider import ChatMessage


class DevProvider:
    """Zero-cost provider for development and testing."""

    # Pre-canned responses for common intents
    _RESPONSES: dict[str, list[str]] = {
        "greeting": [
            "Hello! I'm NEXUS, your AI-powered IDE assistant. How can I help you today?",
            "Hi there! Ready to code, debug, or architect something amazing?",
            "Welcome back! What are we building today?",
        ],
        "code": [
            "Here's a clean implementation:\n\n```python\ndef solve(data):\n    return sorted(set(data))\n```\n\nThis removes duplicates and sorts in O(n log n).",
            "I'll scaffold that for you:\n\n```typescript\ninterface User {\n  id: string;\n  name: string;\n  email: string;\n}\n```",
            "Consider this refactor:\n\n```python\n# Before: nested loops\n# After: dictionary comprehension\nresult = {k: v for k, v in items if v > 0}\n```",
        ],
        "debug": [
            "The issue is likely a null pointer on line 42. Add a guard clause:\n\n```python\nif user is None:\n    return None\n```",
            "Check your async/await — you may be missing `await` on the database call.",
            "Memory leak detected: the event listener isn't being removed on unmount.",
        ],
        "explain": [
            "This pattern is called Dependency Injection. It decouples the service from its dependencies, making testing easier.",
            "The algorithm uses dynamic programming with memoization to achieve O(n) time complexity.",
            "React's reconciliation algorithm compares the virtual DOM trees and applies minimal updates to the real DOM.",
        ],
        "plan": [
            "Here's a phased plan:\n\n1. **Discovery** — audit current codebase\n2. **Design** — draft architecture RFC\n3. **MVP** — implement core loop with tests\n4. ** Polish** — add observability and docs",
            "Roadmap:\n\n- Week 1: Scaffold API + DB schema\n- Week 2: Auth + core features\n- Week 3: Frontend integration\n- Week 4: E2E tests + deploy",
        ],
        "search": [
            "Based on my search, the recommended approach is to use `httpx` with `async` sessions for concurrent API calls.",
            "The latest best practice (2026) is to use structured outputs with JSON schema validation instead of free-form parsing.",
        ],
        "default": [
            "I understand. Let me analyze that for you...\n\nThe most robust approach would be to encapsulate the logic in a dedicated service class with clear interfaces.",
            "Interesting question. From an architecture perspective, I'd recommend keeping the domain layer pure and pushing side effects to the infrastructure layer.",
            "Let me think through this step by step...\n\n1. Identify the core entities\n2. Define their relationships\n3. Choose the persistence strategy\n4. Add validation and error handling",
        ],
    }

    async def aclose(self) -> None:
        pass

    def _classify(self, messages: list[dict[str, str]]) -> str:
        text = " ".join(m.get("content", "") for m in messages).lower()
        if any(w in text for w in ("hello", "hi ", "hey", "good morning", "good afternoon")):
            return "greeting"
        if any(w in text for w in ("code", "function", "class", "implement", "refactor", "write")):
            return "code"
        if any(w in text for w in ("bug", "error", "fix", "debug", "exception", "crash")):
            return "debug"
        if any(w in text for w in ("explain", "what is", "how does", "why ", "compare")):
            return "explain"
        if any(w in text for w in ("plan", "roadmap", "strategy", "design system", "architecture")):
            return "plan"
        if any(w in text for w in ("search", "find", "lookup", "latest", "news")):
            return "search"
        return "default"

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]] | list[ChatMessage],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        text = await self.chat_complete(model, messages, **kwargs)
        # Simulate streaming by yielding word-by-word
        for word in text.split():
            yield word + " "

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]] | list[ChatMessage],
        **kwargs: Any,
    ) -> str:
        dict_messages = [
            m if isinstance(m, dict) else {"role": m.role, "content": m.content} for m in messages
        ]
        intent = self._classify(dict_messages)
        candidates = self._RESPONSES.get(intent, self._RESPONSES["default"])
        return random.choice(candidates)

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        # Deterministic pseudo-random embeddings for dev
        dim = 384
        results: list[list[float]] = []
        for text in texts:
            seed = sum(ord(c) for c in text)
            rng = random.Random(seed)
            vec = [rng.uniform(-1.0, 1.0) for _ in range(dim)]
            # Normalize
            norm = sum(v * v for v in vec) ** 0.5
            vec = [v / norm for v in vec]
            results.append(vec)
        return results

    async def health_check(self) -> bool:
        return True
