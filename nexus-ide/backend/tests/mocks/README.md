# Test Mocks for Isolated Testing

This directory contains mock implementations of external dependencies for isolated testing.

## Available Mocks

### 1. MockRedisBackend (`mock_redis.py`)
Mock implementation of Redis backend for testing without a real Redis instance.

**Features:**
- In-memory key-value storage
- Supports get, set, delete, exists operations
- Supports scan_iter for pattern matching
- Simulates memory usage

**Usage:**
```python
from tests.mocks.mock_redis import MockRedisBackend

redis = MockRedisBackend()
redis.set("test_key", "test_value")
value = redis.get("test_key")
```

### 2. MockQdrantBackend (`mock_qdrant.py`)
Mock implementation of Qdrant vector database for testing without a real Qdrant instance.

**Features:**
- In-memory collection storage
- Supports count, search, upsert operations
- Returns mock search results

**Usage:**
```python
from tests.mocks.mock_qdrant import MockQdrantBackend

qdrant = MockQdrantBackend()
count = qdrant.count()
results = qdrant.search([0.1, 0.2, 0.3])
```

### 3. MockEventBus (`mock_event_bus.py`)
Mock implementation of EventBus for testing event-driven components.

**Features:**
- In-memory event storage
- Supports publish/subscribe pattern
- Tracks all published events
- Async-safe

**Usage:**
```python
from tests.mocks.mock_event_bus import MockEventBus, MockEvent

bus = MockEventBus()
event = MockEvent(type="test_event", agent="test_agent", payload={"test": "data"})
await bus.publish(event)
events = bus.get_events()
```

### 4. MockAgentRegistry (`mock_registry.py`)
Mock implementation of Agent Registry for testing agent-related functionality.

**Features:**
- Pre-configured mock agents (router, architect, researcher, coder, debugger, documenter)
- Supports get_agent, list_agents operations
- Provides mock topology data

**Usage:**
```python
from tests.mocks.mock_registry import MockAgentRegistry

registry = MockAgentRegistry()
agents = registry.list_agents()
topology = registry.get_topology()
```

### 5. MockLLMClient (`mock_llm.py`)
Mock implementation of LLM client (OpenAI/Ollama) for testing AI interactions.

**Features:**
- Pre-configured mock responses
- Supports chat and stream operations
- Customizable responses for testing

**Usage:**
```python
from tests.mocks.mock_llm import MockLLMClient

client = MockLLMClient()
response = await client.chat([{"role": "user", "content": "Hello"}])
async for chunk in client.stream([{"role": "user", "content": "Hello"}]):
    print(chunk)
```

## Pytest Fixtures

The `conftest.py` file provides pytest fixtures for easy use in tests:

- `mock_redis` - MockRedisBackend instance
- `mock_qdrant` - MockQdrantBackend instance
- `mock_event_bus` - MockEventBus instance
- `mock_agent_registry` - MockAgentRegistry instance
- `mock_llm_client` - MockLLMClient instance
- `mock_dependencies` - All mocks in a dictionary

**Usage in tests:**
```python
def test_something(mock_redis, mock_qdrant):
    # Use mock dependencies
    mock_redis.set("key", "value")
    count = mock_qdrant.count()
```

## Benefits

1. **Isolation**: Tests run without external dependencies
2. **Speed**: No network calls or external service startup time
3. **Determinism**: Mocks provide consistent behavior
4. **Control**: Can simulate various scenarios (errors, edge cases)
5. **CI/CD Friendly**: No need for external services in CI pipelines

## Limitations

- Mocks are simplified implementations
- Not a replacement for integration tests with real services
- May not capture all edge cases of real implementations
- Need to be kept in sync with real API changes

## Best Practices

1. Use mocks for unit tests and integration tests where external services aren't critical
2. Write integration tests with real services for critical paths
3. Keep mocks updated when real implementations change
4. Document mock behavior and limitations
5. Use fixtures to ensure proper cleanup between tests
