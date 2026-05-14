"""Contract tests for API models.

These tests verify that the API contracts (Pydantic models) are correctly defined
and can be serialized/deserialized properly.
"""

import json

import pytest

from backend.models.api import (
    ChatRequest,
    FileListRequest,
    FileReadRequest,
    FileTreeEntry,
    FileWriteRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    RoutingDecision,
    StreamEvent,
    TerminalExecuteRequest,
    TerminalExecuteResponse,
)


@pytest.mark.contract
class TestChatRequestContract:
    """Test ChatRequest contract."""

    def test_serialization(self) -> None:
        """Test that ChatRequest can be serialized to JSON."""
        request = ChatRequest(message="Hello", session_id="test")
        json_str = request.model_dump_json()
        assert json_str is not None

    def test_deserialization(self) -> None:
        """Test that ChatRequest can be deserialized from JSON."""
        json_str = '{"message":"Hello","session_id":"test","mode":"agent"}'
        request = ChatRequest.model_validate_json(json_str)
        assert request.message == "Hello"
        assert request.session_id == "test"

    def test_schema_is_valid(self) -> None:
        """Test that ChatRequest schema is valid."""
        schema = ChatRequest.model_json_schema()
        assert "properties" in schema
        assert "message" in schema["properties"]
        assert "session_id" in schema["properties"]


@pytest.mark.contract
class TestRoutingDecisionContract:
    """Test RoutingDecision contract."""

    def test_serialization(self) -> None:
        """Test that RoutingDecision can be serialized to JSON."""
        decision = RoutingDecision(primary_agent="CODER", estimated_complexity=5)
        json_str = decision.model_dump_json()
        assert json_str is not None

    def test_deserialization(self) -> None:
        """Test that RoutingDecision can be deserialized from JSON."""
        json_str = '{"primary_agent":"CODER","estimated_complexity":5}'
        decision = RoutingDecision.model_validate_json(json_str)
        assert decision.primary_agent == "CODER"
        assert decision.estimated_complexity == 5

    def test_schema_is_valid(self) -> None:
        """Test that RoutingDecision schema is valid."""
        schema = RoutingDecision.model_json_schema()
        assert "properties" in schema
        assert "primary_agent" in schema["properties"]


@pytest.mark.contract
class TestStreamEventContract:
    """Test StreamEvent contract."""

    def test_serialization(self) -> None:
        """Test that StreamEvent can be serialized to JSON."""
        event = StreamEvent(type="token", agent="CODER", content="Hello")
        json_str = event.model_dump_json()
        assert json_str is not None

    def test_deserialization(self) -> None:
        """Test that StreamEvent can be deserialized from JSON."""
        json_str = '{"type":"token","agent":"CODER","content":"Hello"}'
        event = StreamEvent.model_validate_json(json_str)
        assert event.type == "token"
        assert event.agent == "CODER"
        assert event.content == "Hello"

    def test_schema_is_valid(self) -> None:
        """Test that StreamEvent schema is valid."""
        schema = StreamEvent.model_json_schema()
        assert "properties" in schema
        assert "type" in schema["properties"]


@pytest.mark.contract
class TestProjectCreateRequestContract:
    """Test ProjectCreateRequest contract."""

    def test_serialization(self) -> None:
        """Test that ProjectCreateRequest can be serialized to JSON."""
        request = ProjectCreateRequest(name="Test", path="/path")
        json_str = request.model_dump_json()
        assert json_str is not None

    def test_deserialization(self) -> None:
        """Test that ProjectCreateRequest can be deserialized from JSON."""
        json_str = '{"name":"Test","path":"/path"}'
        request = ProjectCreateRequest.model_validate_json(json_str)
        assert request.name == "Test"
        assert request.path == "/path"


@pytest.mark.contract
class TestFileTreeEntryContract:
    """Test FileTreeEntry contract."""

    def test_serialization(self) -> None:
        """Test that FileTreeEntry can be serialized to JSON."""
        entry = FileTreeEntry(path="/file.txt", name="file.txt", type="file")
        json_str = entry.model_dump_json()
        assert json_str is not None

    def test_deserialization(self) -> None:
        """Test that FileTreeEntry can be deserialized from JSON."""
        json_str = '{"path":"/file.txt","name":"file.txt","type":"file"}'
        entry = FileTreeEntry.model_validate_json(json_str)
        assert entry.path == "/file.txt"
        assert entry.type == "file"

    def test_nested_structure(self) -> None:
        """Test that nested FileTreeEntry structures work."""
        child = FileTreeEntry(path="/dir/file.txt", name="file.txt", type="file")
        entry = FileTreeEntry(
            path="/dir", name="dir", type="directory", children=[child]
        )
        json_str = entry.model_dump_json()
        parsed = FileTreeEntry.model_validate_json(json_str)
        assert len(parsed.children) == 1
        assert parsed.children[0].name == "file.txt"


@pytest.mark.contract
class TestTerminalExecuteRequestContract:
    """Test TerminalExecuteRequest contract."""

    def test_serialization(self) -> None:
        """Test that TerminalExecuteRequest can be serialized to JSON."""
        request = TerminalExecuteRequest(command="ls")
        json_str = request.model_dump_json()
        assert json_str is not None

    def test_deserialization(self) -> None:
        """Test that TerminalExecuteRequest can be deserialized from JSON."""
        json_str = '{"command":"ls"}'
        request = TerminalExecuteRequest.model_validate_json(json_str)
        assert request.command == "ls"


@pytest.mark.contract
class TestTerminalExecuteResponseContract:
    """Test TerminalExecuteResponse contract."""

    def test_serialization(self) -> None:
        """Test that TerminalExecuteResponse can be serialized to JSON."""
        response = TerminalExecuteResponse(
            execution_id="exec-123",
            command="ls",
            stdout="file.txt",
            stderr="",
            exit_code=0,
            timed_out=False,
            duration_ms=100,
            risk_level="low",
        )
        json_str = response.model_dump_json()
        assert json_str is not None

    def test_deserialization(self) -> None:
        """Test that TerminalExecuteResponse can be deserialized from JSON."""
        json_str = '{"execution_id":"exec-123","command":"ls","stdout":"file.txt","stderr":"","exit_code":0,"timed_out":false,"duration_ms":100,"risk_level":"low"}'
        response = TerminalExecuteResponse.model_validate_json(json_str)
        assert response.execution_id == "exec-123"
        assert response.exit_code == 0