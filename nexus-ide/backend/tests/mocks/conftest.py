"""Test fixtures using mocks for isolated testing."""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

# Add mocks directory to path
mocks_dir = Path(__file__).parent
sys.path.insert(0, str(mocks_dir))

from mock_redis import MockRedisBackend
from mock_qdrant import MockQdrantBackend
from mock_event_bus import MockEventBus
from mock_registry import MockAgentRegistry
from mock_llm import MockLLMClient


@pytest.fixture
def mock_redis():
    """Mock Redis backend fixture."""
    redis = MockRedisBackend()
    yield redis
    redis.clear()


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant backend fixture."""
    qdrant = MockQdrantBackend()
    yield qdrant


@pytest.fixture
def mock_event_bus():
    """Mock EventBus fixture."""
    bus = MockEventBus()
    yield bus
    # Clean up
    import asyncio
    asyncio.run(bus.close())


@pytest.fixture
def mock_agent_registry():
    """Mock Agent Registry fixture."""
    registry = MockAgentRegistry()
    yield registry


@pytest.fixture
def mock_llm_client():
    """Mock LLM client fixture."""
    client = MockLLMClient()
    yield client
    import asyncio
    asyncio.run(client.close())


@pytest.fixture
def mock_dependencies(mock_redis, mock_qdrant, mock_event_bus, mock_agent_registry):
    """Fixture that provides all mock dependencies."""
    return {
        "redis": mock_redis,
        "qdrant": mock_qdrant,
        "event_bus": mock_event_bus,
        "agent_registry": mock_agent_registry,
    }
