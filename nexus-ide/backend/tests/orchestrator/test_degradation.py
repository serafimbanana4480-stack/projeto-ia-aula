"""Tests for graceful degradation and escalation system."""
import pytest
from backend.orchestrator.degradation import DegradationManager, RetryPolicy, AgentType
from backend.orchestrator.events import EventBus
from backend.observability.workflow_tracker import WorkflowTracker


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def workflow_tracker():
    return WorkflowTracker()


@pytest.fixture
def retry_policy():
    return RetryPolicy(max_attempts=2, base_delay_ms=100, max_delay_ms=1000, backoff_multiplier=2.0, jitter_ratio=0.1)


@pytest.fixture
def degradation_manager(event_bus, workflow_tracker, retry_policy):
    return DegradationManager(event_bus=event_bus, workflow_tracker=workflow_tracker, retry_policy=retry_policy)


class TestAgentTypeClassification:
    def test_classify_specialized_agent(self, degradation_manager):
        assert degradation_manager.classify_agent("CODER") == AgentType.SPECIALIZED
        assert degradation_manager.classify_agent("ARCHITECT") == AgentType.SPECIALIZED

    def test_classify_general_agent(self, degradation_manager):
        assert degradation_manager.classify_agent("MICRO") == AgentType.GENERAL
        assert degradation_manager.classify_agent("FAST") == AgentType.GENERAL

    def test_classify_fallback_agent(self, degradation_manager):
        assert degradation_manager.classify_agent("NANO") == AgentType.FALLBACK


class TestFallbackChain:
    def test_fallback_chain_for_specialized(self, degradation_manager):
        chain = degradation_manager.get_fallback_chain("CODER")
        assert "CODER" not in chain
        assert len(chain) > 0

    def test_fallback_chain_for_fallback(self, degradation_manager):
        chain = degradation_manager.get_fallback_chain("NANO")
        assert chain == []


class TestRetryPolicy:
    def test_backoff_delay_calculation(self, degradation_manager):
        delay1 = degradation_manager._calculate_backoff_delay(1)
        assert 90 <= delay1 <= 110
        delay2 = degradation_manager._calculate_backoff_delay(2)
        assert 180 <= delay2 <= 220

    def test_retryable_error_detection(self, degradation_manager):
        assert degradation_manager._is_retryable_error("timeout error")
        assert not degradation_manager._is_retryable_error("permission denied")
