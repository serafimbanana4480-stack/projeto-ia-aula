"""Tests for API models."""

import pytest
from pydantic import ValidationError

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


class TestChatRequest:
    """Test ChatRequest model."""

    def test_valid_chat_request(self) -> None:
        """Test creating a valid ChatRequest."""
        request = ChatRequest(message="Hello", session_id="test-session")
        assert request.message == "Hello"
        assert request.session_id == "test-session"
        assert request.mode == "auto"
        assert request.model == ""
        assert request.project_path == ""

    def test_chat_request_with_model(self) -> None:
        """Test creating a ChatRequest with explicit model selection."""
        request = ChatRequest(message="Hello", session_id="test-session", model="deep")
        assert request.model == "deep"

    def test_chat_request_with_project_path(self) -> None:
        """Test creating a ChatRequest with project path."""
        request = ChatRequest(
            message="Hello",
            session_id="test-session",
            project_path="/home/user/project",
        )
        assert request.project_path == "/home/user/project"

    def test_message_too_short_raises_validation_error(self) -> None:
        """Test that empty message raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="")
        assert "at least 1" in str(exc_info.value).lower()

    def test_message_too_long_raises_validation_error(self) -> None:
        """Test that too long message raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="x" * 50001)
        assert "at most 50000 characters" in str(exc_info.value)

    def test_session_id_too_long_raises_validation_error(self) -> None:
        """Test that too long session_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="Hello", session_id="x" * 129)
        assert "at most 128 characters" in str(exc_info.value)

    def test_default_session_id(self) -> None:
        """Test that session_id defaults to 'default'."""
        request = ChatRequest(message="Hello")
        assert request.session_id == "default"


class TestProjectCreateRequest:
    """Test ProjectCreateRequest model."""

    def test_valid_project_create_request(self) -> None:
        """Test creating a valid ProjectCreateRequest."""
        request = ProjectCreateRequest(name="Test Project", path="/path/to/project")
        assert request.name == "Test Project"
        assert request.path == "/path/to/project"
        assert request.description == ""
        assert request.mode == "auto"
        assert request.trust is False

    def test_name_too_short_raises_validation_error(self) -> None:
        """Test that empty name raises ValidationError."""
        with pytest.raises(ValidationError):
            ProjectCreateRequest(name="", path="/path")

    def test_path_too_short_raises_validation_error(self) -> None:
        """Test that empty path raises ValidationError."""
        with pytest.raises(ValidationError):
            ProjectCreateRequest(name="Test", path="")


class TestProjectUpdateRequest:
    """Test ProjectUpdateRequest model."""

    def test_valid_project_update_request(self) -> None:
        """Test creating a valid ProjectUpdateRequest."""
        request = ProjectUpdateRequest(name="Updated Name")
        assert request.name == "Updated Name"
        assert request.description is None

    def test_all_fields_optional(self) -> None:
        """Test that all fields are optional."""
        request = ProjectUpdateRequest()
        assert request.name is None
        assert request.description is None
        assert request.mode is None


class TestFileReadRequest:
    """Test FileReadRequest model."""

    def test_valid_file_read_request(self) -> None:
        """Test creating a valid FileReadRequest."""
        request = FileReadRequest(path="/path/to/file.txt")
        assert request.path == "/path/to/file.txt"
        assert request.project_path == "."

    def test_path_required(self) -> None:
        """Test that path is required."""
        with pytest.raises(ValidationError):
            FileReadRequest(path="")


class TestFileWriteRequest:
    """Test FileWriteRequest model."""

    def test_valid_file_write_request(self) -> None:
        """Test creating a valid FileWriteRequest."""
        request = FileWriteRequest(path="/path/to/file.txt", content="Hello World")
        assert request.path == "/path/to/file.txt"
        assert request.content == "Hello World"
        assert request.project_path == "."


class TestFileListRequest:
    """Test FileListRequest model."""

    def test_valid_file_list_request(self) -> None:
        """Test creating a valid FileListRequest."""
        request = FileListRequest(path="/path")
        assert request.path == "/path"
        assert request.recursive is True


class TestFileTreeEntry:
    """Test FileTreeEntry model."""

    def test_valid_file_tree_entry(self) -> None:
        """Test creating a valid FileTreeEntry."""
        entry = FileTreeEntry(path="/file.txt", name="file.txt", type="file", size=100)
        assert entry.path == "/file.txt"
        assert entry.name == "file.txt"
        assert entry.type == "file"
        assert entry.size == 100
        assert entry.children == []

    def test_directory_with_children(self) -> None:
        """Test creating a directory with children."""
        child = FileTreeEntry(path="/dir/file.txt", name="file.txt", type="file")
        entry = FileTreeEntry(path="/dir", name="dir", type="directory", children=[child])
        assert len(entry.children) == 1


class TestTerminalExecuteRequest:
    """Test TerminalExecuteRequest model."""

    def test_valid_terminal_execute_request(self) -> None:
        """Test creating a valid TerminalExecuteRequest."""
        request = TerminalExecuteRequest(command="ls -la")
        assert request.command == "ls -la"
        assert request.timeout_seconds == 30

    def test_timeout_bounds(self) -> None:
        """Test that timeout is within bounds."""
        request = TerminalExecuteRequest(command="ls", timeout_seconds=600)
        assert request.timeout_seconds == 600

    def test_timeout_too_low_raises_validation_error(self) -> None:
        """Test that timeout too low raises ValidationError."""
        with pytest.raises(ValidationError):
            TerminalExecuteRequest(command="ls", timeout_seconds=0)

    def test_timeout_too_high_raises_validation_error(self) -> None:
        """Test that timeout too high raises ValidationError."""
        with pytest.raises(ValidationError):
            TerminalExecuteRequest(command="ls", timeout_seconds=601)


class TestTerminalExecuteResponse:
    """Test TerminalExecuteResponse model."""

    def test_valid_terminal_execute_response(self) -> None:
        """Test creating a valid TerminalExecuteResponse."""
        response = TerminalExecuteResponse(
            execution_id="exec-123",
            command="ls",
            stdout="file1.txt\nfile2.txt",
            stderr="",
            exit_code=0,
            timed_out=False,
            duration_ms=100,
            risk_level="low",
        )
        assert response.execution_id == "exec-123"
        assert response.exit_code == 0
        assert response.timed_out is False


class TestRoutingDecision:
    """Test RoutingDecision model."""

    def test_valid_routing_decision(self) -> None:
        """Test creating a valid RoutingDecision."""
        decision = RoutingDecision(
            primary_agent="CODER",
            estimated_complexity=5,
            routing_confidence=0.8,
        )
        assert decision.primary_agent == "CODER"
        assert decision.estimated_complexity == 5
        assert decision.routing_confidence == 0.8

    def test_complexity_bounds(self) -> None:
        """Test that complexity is within bounds."""
        decision = RoutingDecision(primary_agent="CODER", estimated_complexity=10)
        assert decision.estimated_complexity == 10

    def test_complexity_too_low_raises_validation_error(self) -> None:
        """Test that complexity too low raises ValidationError."""
        with pytest.raises(ValidationError):
            RoutingDecision(primary_agent="CODER", estimated_complexity=0)

    def test_complexity_too_high_raises_validation_error(self) -> None:
        """Test that complexity too high raises ValidationError."""
        with pytest.raises(ValidationError):
            RoutingDecision(primary_agent="CODER", estimated_complexity=11)

    def test_routing_confidence_bounds(self) -> None:
        """Test that routing_confidence is within bounds."""
        decision = RoutingDecision(primary_agent="CODER", routing_confidence=1.0)
        assert decision.routing_confidence == 1.0

    def test_routing_confidence_too_low_raises_validation_error(self) -> None:
        """Test that routing_confidence too low raises ValidationError."""
        with pytest.raises(ValidationError):
            RoutingDecision(primary_agent="CODER", routing_confidence=-0.1)

    def test_routing_confidence_too_high_raises_validation_error(self) -> None:
        """Test that routing_confidence too high raises ValidationError."""
        with pytest.raises(ValidationError):
            RoutingDecision(primary_agent="CODER", routing_confidence=1.1)


class TestStreamEvent:
    """Test StreamEvent model."""

    def test_valid_stream_event(self) -> None:
        """Test creating a valid StreamEvent."""
        event = StreamEvent(type="token", agent="CODER", content="Hello")
        assert event.type == "token"
        assert event.agent == "CODER"
        assert event.content == "Hello"
        assert event.timestamp is not None

    def test_event_with_routing_decision(self) -> None:
        """Test creating an event with routing decision."""
        routing = RoutingDecision(primary_agent="CODER")
        event = StreamEvent(type="routing", routing=routing)
        assert event.routing is not None
        assert event.routing.primary_agent == "CODER"

    def test_timestamp_auto_generated(self) -> None:
        """Test that timestamp is auto-generated."""
        event = StreamEvent(type="token")
        assert event.timestamp is not None
        assert isinstance(event.timestamp, str)
