"""Mock LLM client for testing."""
from __future__ import annotations

from typing import Any, AsyncIterator
from dataclasses import dataclass


@dataclass
class MockMessage:
    """Mock message."""
    role: str
    content: str


@dataclass
class MockChoice:
    """Mock choice."""
    message: MockMessage
    finish_reason: str = "stop"


@dataclass
class MockResponse:
    """Mock LLM response."""
    choices: list[MockChoice]
    usage: dict[str, int]


class MockLLMClient:
    """Mock LLM client for testing."""
    
    def __init__(self):
        self._responses = [
            "This is a mock response from the LLM.",
            "I can help you with that task.",
            "Here's the solution you requested.",
        ]
        self._response_index = 0
    
    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> MockResponse:
        """Mock chat completion."""
        response_text = self._responses[self._response_index % len(self._responses)]
        self._response_index += 1
        
        return MockResponse(
            choices=[
                MockChoice(
                    message=MockMessage(role="assistant", content=response_text),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )
    
    async def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> AsyncIterator[str]:
        """Mock streaming response."""
        response_text = self._responses[self._response_index % len(self._responses)]
        self._response_index += 1
        
        # Yield response in chunks
        for i in range(0, len(response_text), 10):
            yield response_text[i:i+10]
    
    async def close(self) -> None:
        """Mock close operation."""
        pass
    
    def set_responses(self, responses: list[str]) -> None:
        """Set custom responses for testing."""
        self._responses = responses
        self._response_index = 0
